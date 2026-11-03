"""
Generazione completa dei due documenti su dati SINTETICI (nessuna rete):
controlla che tutte le sezioni ci siano, i limiti di lunghezza e la
cifratura andata e ritorno. I numeri non hanno significato di mercato.
"""
import zlib

import numpy as np
import pandas as pd
import pytest

from analisi import dati as D
from analisi import report as R


def _serie_finta(simbolo, intraday=True, eventi=True):
    if simbolo == "1SAN.MI":                       # listino secondario: stesso titolo di SAN.PA
        return _listino_secondario()
    rng = np.random.default_rng(zlib.crc32(simbolo.encode()))
    idx = pd.bdate_range("2014-01-02", "2026-10-30")
    c = 50 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, len(idx))))
    o = c * np.exp(rng.normal(0, 0.006, len(idx)))
    h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.007, len(idx))))
    l = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.007, len(idx))))
    v = rng.integers(1e5, 1e6, len(idx)).astype(float)
    o, h, l, c = (np.round(x, 2) for x in (o, h, l, c))     # prezzi reali: 2 decimali
    v = v * 10                                                 # volumi a 7 cifre
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v,
                       "Dividends": 0.0, "Stock Splits": 0.0}, index=idx)
    df.loc[idx[-100], "Dividends"] = 1.2
    s = D.Serie(simbolo=simbolo, giornaliero=df, scaricato_alle=D.ora_roma(), fonte="SINTETICO")
    s.settimanale = df.resample("W-MON", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    if intraday:
        t = pd.date_range("2026-10-26 09:00", "2026-10-30 17:00", freq="30min", tz=D.ROMA)
        t = t[(t.hour >= 9) & (t.hour < 18)]
        s.m30 = pd.DataFrame({"Open": 50.0, "High": 51.0, "Low": 49.0, "Close": 50.5, "Volume": 1000.0}, index=t)
    s.meta = {"currency": "EUR", "longName": f"Finta {simbolo}", "regularMarketTime": 1761840000}
    s.calendario = {"Earnings Date": [pd.Timestamp("2027-01-30").date()]}
    s.date_conti = [idx[-60].date()]
    return s


def _listino_secondario():
    """1SAN.MI: prezzi di SAN.PA +0.2%, 10 barre incoerenti, una stampa fuori range, metadati assenti."""
    p = _serie_finta("SAN.PA")
    df = p.giornaliero.copy()
    for k in ("Open", "High", "Low", "Close"):
        df[k] = (df[k] * 1.002).round(2)
    df["Volume"] = (df["Volume"] / 100).round()
    for i in range(1, 11):                          # chiusura sopra il massimo
        df.iloc[-i * 7, df.columns.get_loc("Close")] = df["High"].iloc[-i * 7] + 0.5
    df.iloc[-3, df.columns.get_loc("High")] = df["High"].iloc[-3] * 1.15
    s = D.Serie(simbolo="1SAN.MI", giornaliero=df, scaricato_alle=D.ora_roma(), fonte="SINTETICO")
    s.errori["meta"] = "KeyError: 'currentTradingPeriod'"
    return s


@pytest.fixture(autouse=True)
def niente_rete(monkeypatch):
    monkeypatch.setattr(D, "scarica", _serie_finta)
    monkeypatch.setattr(D, "screener_tv", lambda c: (None, {}, "test offline"))


CFG = {
    "dati_di_prova": True, "liquidita": 5000, "zigzag_atr": 1.5,
    "strumenti": [
        {"simbolo": "SAN.PA", "nome": "Sanofi", "tipo": "azione", "valuta": "EUR", "benchmark": "^FCHI",
         "collegati": [{"simbolo": "SNY", "tipo": "adr", "rapporto": 0.5, "cambio": "EURUSD=X"}],
         "posizione": {"quantita": 50, "carico": 45, "stop": 40, "target": 70, "uscita": "2027-03-31"}},
        {"simbolo": "SGLD.MI", "nome": "ETC oro", "tipo": "etc", "valuta": "EUR",
         "collegati": [{"simbolo": "GC=F", "tipo": "sottostante", "cambio": "EURUSD=X"}]},
    ] + [{"simbolo": f"T{k}.MI", "tipo": "azione"} for k in range(10)],
}


def test_titolo():
    st = R.Strumento.da_dict(CFG["strumenti"][0])
    md = R.documento_titolo(st, CFG)
    for k in range(1, 16):
        assert f"\n## {k}. " in md, f"manca la sezione {k}"
    assert "```csv" in md and "FILE DI PROVA" in md
    assert "errore di calcolo" not in md, md[md.find("errore di calcolo") - 300:][:600]
    assert len(md) < R.LIMITE_TITOLO, len(md)
    assert "oltre il limite indicativo" not in md


def test_mercato_principale_e_qualita():
    st = R.Strumento.da_dict({"simbolo": "1SAN.MI", "isin": "FR0000120578", "valuta": "EUR", "tipo": "azione",
                              "posizione": {"quantita": 10, "carico": 40, "stop": 30}})
    md = R.documento_titolo(st, CFG)
    assert "errore di calcolo" not in md
    assert "Analisi tecnica — SAN.PA" in md and "ordini su 1SAN.MI" in md
    assert "Listino di esecuzione 1SAN.MI" in md
    assert "barre incoerenti (O o C fuori da L–H) 10" in md
    assert "oltre il range del principale di più di 0.5 ATR 1" in md
    assert "ultima chiusura del listino di esecuzione 1SAN.MI" in md
    sts = [R.Strumento.da_dict({"simbolo": "1SAN.MI", "isin": "FR0000120578", "valuta": "EUR"})]
    mp = R.documento_portafoglio(sts, CFG)
    assert "errore di calcolo" not in mp and "SAN.PA (ordini su 1SAN.MI)" in mp
    assert mp.count("Listino di esecuzione 1SAN.MI") == 1


def test_principale_da_isin_e_wilson():
    from analisi.qualita import principale_da_isin, wilson
    assert principale_da_isin("1SAN.MI", "FR0000120578") == "SAN.PA"
    assert principale_da_isin("1BAYN.MI", "DE000BAY0017") == "BAYN.DE"
    assert principale_da_isin("1AAPL.MI", "US0378331005") == "AAPL"
    assert principale_da_isin("ISP.MI", "IT0000072618") is None
    lo, hi = wilson(5, 10)
    assert abs(lo - 23.659) < 0.01 and abs(hi - 76.341) < 0.01


def test_incoerenti_e_ombre():
    from analisi.qualita import incoerenti, ombre_anomale
    df = pd.DataFrame({"Open": [10, 10, 10.0], "High": [11, 11, 11.0], "Low": [9, 9, 9.0], "Close": [10.5, 11.2, 9.5],
                       "Volume": [100, 100, 10.0]})
    assert incoerenti(df).tolist() == [False, True, False]
    atr = pd.Series([0.5, 0.5, 0.5]); v20 = pd.Series([100, 100, 100.0])
    df2 = df.copy(); df2.loc[2, "High"] = 13.0          # ombra superiore 2.5 > 3*0.5, volume 10 < 50
    df2.loc[1, "Close"] = 10.5
    assert ombre_anomale(df2, atr, v20).tolist() == [False, False, True]


def test_seduta_odierna_assente(monkeypatch):
    """Mercato aperto, ultima barra giornaliera di giorni fa, barre a 30 minuti di oggi."""
    base = _serie_finta

    def finta(simbolo, intraday=True, eventi=True):
        s = base(simbolo, intraday, eventi)
        if simbolo == "ENI.MI":
            adesso = pd.Timestamp(D.ora_roma())
            s.meta = {"currency": "EUR", "currentTradingPeriod": {"regular": {
                "start": adesso - pd.Timedelta(hours=1), "end": adesso + pd.Timedelta(hours=1)}}}
            oggi = pd.date_range(adesso.normalize() + pd.Timedelta(hours=9), periods=3, freq="30min")
            extra = pd.DataFrame({"Open": 50.0, "High": 51.0, "Low": 49.0, "Close": 50.25, "Volume": 10.0}, index=oggi)
            s.m30 = pd.concat([s.m30, extra])
        return s
    monkeypatch.setattr(D, "scarica", finta)
    md = R.documento_titolo(R.Strumento.da_dict({"simbolo": "ENI.MI", "tipo": "azione"}), CFG)
    assert "errore di calcolo" not in md
    testa = md[:md.index("## Definizioni")]
    assert "la seduta di oggi MANCA" in testa and "Ultimo prezzo intraday: 50.25" in testa
    oggi = D.ora_roma().strftime("%Y-%m-%d")
    assert f"{oggi} (in corso):" in md                     # 30 minuti: oggi compreso nelle ultime 5 sedute


def test_portafoglio():
    sts = [R.Strumento.da_dict(x) for x in CFG["strumenti"]]
    md = R.documento_portafoglio(sts, CFG)
    assert "Riepilogo conto" in md and "```csv" not in md
    assert "errore di calcolo" not in md, md[md.find("errore di calcolo") - 300:][:600]
    assert len(md) < 60000, len(md)


def test_cifratura():
    import base64
    import os
    from analisi.cifra import chiave_da_b64, cifra, decifra
    k = chiave_da_b64(base64.b64encode(os.urandom(32)).decode())
    blob = cifra("testo è", "a.md", k)
    assert decifra(blob, k) == {"nome": "a.md", "md": "testo è"}
    with pytest.raises(ValueError):
        chiave_da_b64(base64.b64encode(b"corta").decode())
