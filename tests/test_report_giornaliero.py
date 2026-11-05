"""
Report giornaliero (generate_report.py, storico.py, portfolio_sync.py) su dati
SINTETICI, nessuna rete. I numeri ricalcano i casi segnalati, non dati reali.
"""
import csv
from datetime import date, timedelta

import generate_report as G
import storico


def _pos(**kw):
    p = {"price": 7.196, "ema20": 7.1, "ema50": 7.0, "ema200": 6.8, "day_high": 7.2, "day_low": 7.1,
         "macd_hist": 0.01, "rsi": 55.0, "perf_1m": 2.0, "divisa": "EUR", "prezzo_medio": 6.245}
    p.update(kw)
    return p


# ─── Bug 1: valuta del prezzo ────────────────────────────────────────────────

def test_prezzo_usd_convertito_prima_della_variazione():
    # 6,40 EUR quotati, arrivati come 7,196 USD con EUR/USD 1,1244
    p = G.allinea_valuta(_pos(), "USD", {("USD", "EUR"): (1 / 1.1244, "FX_IDC:USDEUR")})
    assert p["valuta_stato"] == "convertita"
    assert abs(p["price"] - 6.40) < 0.005
    assert abs(p["ema50"] - 7.0 / 1.1244) < 1e-9          # tutti i livelli, non solo il prezzo
    assert p["rsi"] == 55.0 and p["perf_1m"] == 2.0         # rapporti: invariati
    assert "+2.5%" in G.var_da_carico_html(p["price"], p["prezzo_medio"], p["valuta_stato"])
    cella = G.prezzo_html(p)
    assert "6.40 EUR" in cella and "7.20 USD" in cella and "FX_IDC:USDEUR" in cella


def test_stessa_valuta_nessuna_conversione():
    p = G.allinea_valuta(_pos(price=6.40), "EUR", {})
    assert p["valuta_stato"] == "ok" and p["price"] == 6.40
    assert G.prezzo_html(p) == "6.40 EUR"


def test_cambio_mancante_niente_numero_falso():
    p = G.allinea_valuta(_pos(), "USD", {})
    assert p["valuta_stato"] == "cambio_mancante"
    assert p["price"] is None and p["ema50"] is None
    assert "cambio non disponibile" in G.prezzo_html(p)
    assert "n.d." in G.var_da_carico_html(p["price"], p["prezzo_medio"], p["valuta_stato"])


def test_valuta_non_verificata_segnalata():
    p = G.allinea_valuta(_pos(price=6.40), None, {})
    assert p["valuta_stato"] == "non_verificata"
    assert "non verificata" in G.prezzo_html(p)
    assert "non verificata" in G.var_da_carico_html(p["price"], p["prezzo_medio"], p["valuta_stato"])


def test_storico_aggiunge_colonna_valuta_e_confronto_ieri(tmp_path, monkeypatch):
    path = tmp_path / "storico.csv"
    ieri = (date.today() - timedelta(days=1)).isoformat()
    vecchie = ["data", "categoria", "symbol", "isin", "close", "high", "low", "volume", "vol_10d",
               "rsi", "ema20", "ema50", "ema200", "macd_hist", "perf_1m", "perf_3m"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=vecchie)
        w.writeheader()
        w.writerow({"data": ieri, "categoria": "posizione", "symbol": "XUSE", "isin": "IE000TEST",
                    "close": 7.04})
    monkeypatch.setattr(storico, "STORICO_PATH", str(path))
    monkeypatch.setattr(storico, "STORICO_SALT", "")

    # Oggi convertito da USD: ieri (in USD, senza valuta annotata) non e' confrontabile
    oggi = G.allinea_valuta(_pos(isin="IE000TEST", symbol="XUSE"), "USD",
                            {("USD", "EUR"): (1 / 1.1244, "FX_IDC:USDEUR")})
    testo = G._confronto_ieri(oggi)
    assert "non significativo" in testo and "-11" not in testo

    storico.record_daily([oggi], [])
    with open(path, newline="", encoding="utf-8") as f:
        righe = list(csv.DictReader(f))
    assert righe[0]["valuta"] == "" and righe[0]["close"] == "7.04"   # riga vecchia intatta
    assert righe[1]["valuta"] == "EUR"

    # Senza conversione e senza valuta annotata ieri: confronto normale
    normale = G.allinea_valuta(_pos(isin="IE000TEST", price=7.10), "EUR", {})
    assert "da 7.04 a 7.10" in G._confronto_ieri(normale)


# ─── Bug 2: giorni di detenzione ─────────────────────────────────────────────

import portfolio_sync as PS
import regole


def _mov(isin, segno, qty, giorni_fa, prezzo=10.0):
    return {"isin": isin, "titolo": isin, "segno": segno, "quantita": qty, "prezzo": prezzo,
            "divisa": "EUR", "data_valuta": date.today() - timedelta(days=giorni_fa)}


def test_fifo_data_primo_lotto_in_essere_e_tranche():
    mov = [_mov("A", "A", 100, 120), _mov("A", "A", 50, 90), _mov("A", "V", 100, 70),  # primo lotto chiuso
           _mov("A", "A", 30, 40), _mov("A", "A", 20, 10)]
    (p,) = PS.build_fifo_positions(mov)
    assert p["quantita"] == 100
    assert p["giorni_detenzione"] == 90          # il lotto da 50 di 90gg fa, non la media pesata
    assert p["tranche"] == 3


def test_sintesi_prende_data_dallo_storico_se_quantita_combacia():
    sintesi = [{"isin": "A", "quantita": 100.0, "giorni_detenzione": None, "data_apertura": None},
               {"isin": "B", "quantita": 60.0, "giorni_detenzione": None, "data_apertura": None},
               {"isin": "C", "quantita": 5.0, "giorni_detenzione": None, "data_apertura": None}]
    storico_mov = [_mov("A", "A", 100, 75), _mov("B", "A", 40, 30)]
    PS.date_da_storico(sintesi, storico_mov)
    a, b, c = sintesi
    assert a["giorni_detenzione"] == 75 and a["tranche"] == 1 and a["data_apertura_motivo"] is None
    assert b["giorni_detenzione"] is None and "40" in b["data_apertura_motivo"] and "60" in b["data_apertura_motivo"]
    assert c["giorni_detenzione"] is None and "non risulta aperta" in c["data_apertura_motivo"]


def test_sintesi_senza_storico_dice_perche():
    sintesi = [{"isin": "A", "quantita": 1.0, "giorni_detenzione": None}]
    PS.date_da_storico(sintesi, [])
    assert "storico movimenti" in sintesi[0]["data_apertura_motivo"]


def test_data_manuale_solo_come_ripiego():
    oggi = date(2026, 11, 5)
    portafoglio = [{"isin": "A", "giorni_detenzione": None},
                   {"isin": "B", "giorni_detenzione": 30, "data_apertura": "2026-10-06", "data_apertura_fonte": "movimenti"}]
    regole_map = {"A": {"data_apertura": date(2026, 8, 17)}, "B": {"data_apertura": date(2026, 1, 1)}}
    G.applica_data_manuale(portafoglio, regole_map, oggi=oggi)
    assert portafoglio[0]["giorni_detenzione"] == 80 and portafoglio[0]["data_apertura_fonte"] == "manuale"
    assert portafoglio[1]["giorni_detenzione"] == 30            # la data dai movimenti resta prioritaria


def test_giorni_html_fasce_tranche_e_motivo():
    assert "#16a34a" in G.giorni_detenzione_html(59)
    assert "#d97706" in G.giorni_detenzione_html(60) and "#d97706" in G.giorni_detenzione_html(80)
    assert "#dc2626" in G.giorni_detenzione_html(81)
    cella = G.giorni_detenzione_html(90, "2026-08-07", 3, "movimenti")
    assert "dal 07/08/2026" in cella and "3 tranche" in cella
    assert "inserita a mano" in G.giorni_detenzione_html(10, "2026-10-26", 1, "manuale")
    assert "Portafoglio di sintesi" in G.giorni_detenzione_html(None, motivo="l'export 'Portafoglio di sintesi' non contiene date")


def test_regole_leggono_data_apertura(monkeypatch):
    monkeypatch.setattr(regole, "REGOLE_POSIZIONI_YAML", '{"A": {"stop": 1, "data_apertura": "2026-08-17"}}')
    assert regole.load_regole()["A"]["data_apertura"] == date(2026, 8, 17)
