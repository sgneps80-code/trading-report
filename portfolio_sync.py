#!/usr/bin/env python3
"""
Sincronizzazione posizioni aperte dal dossier titoli (export del broker).

Riconosce automaticamente DUE formati di export (per intestazione, non per
nome file), perché i broker offrono entrambi e non è garantito quale un
utente carichi:

- "Movimenti Dossier Titoli" (storico movimenti: Operazione, Data valuta,
  Descrizione, Titolo, ISIN, Segno A/V, Quantità, Divisa, Prezzo, Cambio,
  Controvalore) — ricostruisce le posizioni aperte in FIFO. Dà anche la
  data di apertura reale (quindi i giorni di detenzione).
- "Portafoglio di sintesi" (snapshot delle posizioni attuali: Titolo, ISIN,
  Simbolo, Mercato, Strumento, Valuta, Quantità, P.zo medio di carico...) —
  ogni riga è già una posizione aperta, niente FIFO da fare. Non contiene
  una data di apertura: i giorni di detenzione restano n.d. per queste
  posizioni, non è un dato che questo export fornisce.

Entrambi i formati arrivano sia come .xlsx (ZIP/OOXML, letto con openpyxl)
sia come .xls vecchio formato binario (OLE2/Compound File, letto con xlrd —
openpyxl non sa aprirlo, non è uno ZIP).

Il repo e' pubblico: dossier XLS e mappa ISIN sono dati personali, quindi
non vengono committati in chiaro. Fonte primaria = GitHub Secret
(MOVIMENTI_XLSX_B64 in base64, ISIN_MAP_JSON come stringa JSON), mai
scritto su disco nel repo. Se il secret non c'e' (uso locale/di test),
si legge il file committato in data/ — che quindi deve restare un
template vuoto/pseudonimo, non i tuoi dati reali.

Le posizioni chiuse (quantita residua zero dopo il FIFO, o assenti dallo
snapshot) non vengono restituite: spariscono dal report senza bisogno di
un intervento manuale.
"""
import base64
import io
import json
import logging
import os
from collections import deque
from datetime import date, datetime

logger = logging.getLogger(__name__)

MOVIMENTI_PATH = os.environ.get("MOVIMENTI_PATH", "data/movimenti_dossier.xlsx")
ISIN_MAP_PATH = os.environ.get("ISIN_MAP_PATH", "data/isin_map.json")
MOVIMENTI_XLSX_B64 = os.environ.get("MOVIMENTI_XLSX_B64", "")
ISIN_MAP_JSON = os.environ.get("ISIN_MAP_JSON", "")


def dossier_disponibile():
    """True se c'e' un dossier da sincronizzare, come secret o come file
    committato. Usato da generate_report.py per decidere se sincronizzare
    dal dossier o ricadere sul vecchio secret PORTFOLIO_JSON."""
    return bool(MOVIMENTI_XLSX_B64) or os.path.exists(MOVIMENTI_PATH)


# Intestazioni del formato "Movimenti Dossier Titoli" (storico), normalizzate
# in minuscolo. L'ordine delle colonne nel file non conta: si legge per nome.
_HEADER_MOVIMENTI = {
    "operazione": "operazione",
    "data valuta": "data_valuta",
    "descrizione": "descrizione",
    "titolo": "titolo",
    "isin": "isin",
    "segno a/v": "segno",
    "quantità": "quantita",
    "quantita": "quantita",
    "divisa": "divisa",
    "prezzo": "prezzo",
    "cambio": "cambio",
    "controvalore": "controvalore",
}

# Intestazioni del formato "Portafoglio di sintesi" (snapshot).
_HEADER_SINTESI = {
    "titolo": "titolo",
    "isin": "isin",
    "simbolo": "simbolo",
    "mercato": "mercato",
    "strumento": "strumento",
    "valuta": "divisa",
    "quantità": "quantita",
    "quantita": "quantita",
    "p.zo medio di carico": "prezzo_medio",
    "prezzo medio di carico": "prezzo_medio",
}

# Suffisso stile Yahoo/broker (es. "ISP.MI") -> prefisso exchange TradingView.
# Serve solo a suggerire un ticker di partenza nell'editor: l'utente lo
# corregge se sbagliato, non viene mai usato come dato certo.
_SUFFISSO_A_EXCHANGE_TV = {
    "MI": "MIL", "PA": "EURONEXT", "AS": "EURONEXT", "BR": "EURONEXT", "LS": "EURONEXT",
    "DE": "XETR", "F": "FWB", "L": "LSE", "SW": "XSWX", "MC": "BME",
}


def _norm_header(h, alias_map):
    return alias_map.get(str(h or "").strip().lower())


def _parse_number(v):
    """Coerce numeri che arrivano come stringa con virgola decimale (export italiani)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    return None


def guess_tv_symbol(simbolo_broker):
    """Da un simbolo stile Yahoo/broker (es. 'ISP.MI') un ticker TradingView
    plausibile (es. 'MIL:ISP') — solo un suggerimento di partenza per
    l'editor, mai un dato certo. Se il suffisso non e' riconosciuto, o non
    c'e' un suffisso, restituisce il simbolo originale invariato."""
    simbolo_broker = (simbolo_broker or "").strip()
    if not simbolo_broker or "." not in simbolo_broker:
        return simbolo_broker
    base, suffisso = simbolo_broker.rsplit(".", 1)
    exch = _SUFFISSO_A_EXCHANGE_TV.get(suffisso.upper())
    return f"{exch}:{base}" if exch else simbolo_broker


def _tipo_da_strumento(strumento):
    """'Azione' resta 'Azione'; ETF/ETC/ETN confluiscono in 'ETF' (unica
    altra categoria usata dal report per il portafoglio)."""
    s = (strumento or "").strip().lower()
    return "Azione" if s == "azione" else "ETF"


def _righe_da_file(sorgente):
    """sorgente: path (str) o bytes. Restituisce la lista di righe (liste di
    celle) del primo foglio, leggendo .xlsx (ZIP, openpyxl) o .xls vecchio
    formato (OLE2/Compound File, xlrd) in base alla firma dei byte —
    l'estensione del file non e' attendibile quanto il contenuto reale."""
    if isinstance(sorgente, (bytes, bytearray)):
        dati = bytes(sorgente)
    else:
        with open(sorgente, "rb") as f:
            dati = f.read()

    if dati[:2] == b"PK":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(dati), data_only=True, read_only=True)
        ws = wb.active
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if dati[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        import xlrd
        wb = xlrd.open_workbook(file_contents=dati)
        ws = wb.sheet_by_index(0)
        return [[ws.cell_value(r, c) for c in range(ws.ncols)] for r in range(ws.nrows)]
    raise ValueError(f"formato file non riconosciuto: non e' .xlsx né .xls ({len(dati)} byte)")


def _trova_header(righe, alias_map, richieste, max_righe=10):
    """Cerca tra le prime `max_righe` quella che, una volta le celle
    normalizzate con `alias_map`, contiene tutte le colonne in `richieste`.
    Serve perche' alcuni export hanno un titolo e una riga vuota prima
    dell'intestazione vera (es. 'Portafoglio di sintesi'). Ritorna
    (indice, colonne_normalizzate) o (None, None) se non trovata."""
    for i, riga in enumerate(righe[:max_righe]):
        cols = [_norm_header(h, alias_map) for h in riga]
        if all(r in cols for r in richieste):
            return i, cols
    return None, None


def _estrai_movimenti(righe, cols):
    """Formato 'Movimenti Dossier Titoli': ogni riga e' un acquisto o una
    vendita. Righe non riconducibili a un movimento titoli (cedole,
    commissioni, bonifici...) vengono scartate silenziosamente."""
    out = []
    for raw in righe:
        rec = {c: v for c, v in zip(cols, raw) if c}
        isin = str(rec.get("isin") or "").strip()
        segno = str(rec.get("segno") or "").strip().upper()
        qty = _parse_number(rec.get("quantita"))
        if not isin or segno not in ("A", "V") or not qty:
            continue
        data_val = _parse_date(rec.get("data_valuta"))
        prezzo = _parse_number(rec.get("prezzo"))
        if not data_val or prezzo is None:
            continue
        out.append({
            "isin": isin,
            "titolo": str(rec.get("titolo") or rec.get("descrizione") or isin).strip(),
            "segno": segno,
            "quantita": abs(qty),
            "prezzo": prezzo,
            "divisa": str(rec.get("divisa") or "EUR").strip(),
            "data_valuta": data_val,
        })
    logger.info(f"Movimenti letti: {len(out)} righe valide (acquisto/vendita titoli)")
    return out


def build_fifo_positions(movimenti):
    """Ricostruisce le posizioni aperte in FIFO, per ISIN, dal formato
    'Movimenti Dossier Titoli'. Le vendite consumano i lotti piu' vecchi;
    le posizioni chiuse (quantita residua zero) non compaiono nel risultato."""
    by_isin = {}
    for m in movimenti:
        by_isin.setdefault(m["isin"], []).append(m)

    positions = []
    for isin, righe in by_isin.items():
        righe = sorted(righe, key=lambda r: r["data_valuta"])
        lots = deque()  # ognuno: {"qty", "prezzo", "data"}
        titolo, divisa = righe[-1]["titolo"], righe[-1]["divisa"]

        for r in righe:
            if r["segno"] == "A":
                lots.append({"qty": r["quantita"], "prezzo": r["prezzo"], "data": r["data_valuta"]})
            else:  # "V"
                da_vendere = r["quantita"]
                while da_vendere > 1e-9 and lots:
                    lotto = lots[0]
                    consumato = min(lotto["qty"], da_vendere)
                    lotto["qty"] -= consumato
                    da_vendere -= consumato
                    if lotto["qty"] <= 1e-9:
                        lots.popleft()
                if da_vendere > 1e-9:
                    # Vendita superiore ai lotti registrati: probabile acquisto
                    # precedente all'inizio dello storico esportato. Segnala e
                    # ignora l'eccedenza, senza far esplodere il calcolo.
                    logger.warning(
                        f"{isin}: vendute {da_vendere:.2f} unita' senza lotto "
                        f"corrispondente (storico movimenti incompleto?)"
                    )

        if not lots:
            continue  # posizione chiusa: non compare nel report

        tot_qty = sum(l["qty"] for l in lots)
        avg_price = sum(l["qty"] * l["prezzo"] for l in lots) / tot_qty
        # Data di apertura media, pesata per quantita' sui lotti ancora aperti
        avg_ord = sum(l["qty"] * l["data"].toordinal() for l in lots) / tot_qty
        entry_date = date.fromordinal(round(avg_ord))
        holding_days = (date.today() - entry_date).days

        positions.append({
            "isin": isin,
            "titolo": titolo,
            "divisa": divisa,
            "quantita": round(tot_qty, 4),
            "prezzo_medio": round(avg_price, 4),
            "data_apertura": entry_date.isoformat(),
            "giorni_detenzione": holding_days,
            "simbolo_broker": "",
            "tipo_broker": "Azione",
        })

    positions.sort(key=lambda p: p["giorni_detenzione"], reverse=True)
    logger.info(f"Posizioni aperte ricostruite (FIFO): {len(positions)}")
    return positions


def _estrai_posizioni_sintesi(righe, cols):
    """Formato 'Portafoglio di sintesi': ogni riga E' GIA' una posizione
    aperta (non un movimento) — niente FIFO, il broker da' gia' quantita' e
    prezzo medio di carico. Manca la data di apertura: giorni di detenzione
    resta n.d. per queste posizioni, il report lo mostra come tale invece
    di inventare un numero."""
    out = []
    for raw in righe:
        rec = {c: v for c, v in zip(cols, raw) if c}
        isin = str(rec.get("isin") or "").strip()
        qty = _parse_number(rec.get("quantita"))
        if not isin or not qty:
            continue
        prezzo_medio = _parse_number(rec.get("prezzo_medio"))
        out.append({
            "isin": isin,
            "titolo": str(rec.get("titolo") or isin).strip(),
            "divisa": str(rec.get("divisa") or "EUR").strip(),
            "quantita": round(abs(qty), 4),
            "prezzo_medio": round(prezzo_medio, 4) if prezzo_medio is not None else None,
            "data_apertura": None,
            "giorni_detenzione": None,
            "simbolo_broker": str(rec.get("simbolo") or "").strip(),
            "tipo_broker": _tipo_da_strumento(rec.get("strumento")),
        })
    logger.info(f"Posizioni lette da 'Portafoglio di sintesi': {len(out)}")
    return out


def _carica_posizioni():
    """Legge il dossier (secret MOVIMENTI_XLSX_B64 se presente, altrimenti il
    file committato), riconosce il formato dall'intestazione e restituisce
    le posizioni aperte in una forma unica, indipendente dal formato di
    origine. [] con un log chiaro se il dossier manca o non e' valido —
    mai un'eccezione che fa fallire il resto del report."""
    if MOVIMENTI_XLSX_B64:
        try:
            sorgente = base64.b64decode(MOVIMENTI_XLSX_B64)
        except Exception as e:
            logger.error(f"MOVIMENTI_XLSX_B64 illeggibile ({e})")
            return []
        origine = f"secret MOVIMENTI_XLSX_B64 ({len(sorgente)} byte)"
    elif os.path.exists(MOVIMENTI_PATH):
        sorgente = MOVIMENTI_PATH
        origine = MOVIMENTI_PATH
    else:
        logger.warning(f"Dossier movimenti non trovato: né secret MOVIMENTI_XLSX_B64 né {MOVIMENTI_PATH}")
        return []

    try:
        righe = _righe_da_file(sorgente)
    except Exception as e:
        logger.error(
            f"Dossier illeggibile da {origine} ({e}). Verifica che sia un "
            "export .xlsx o .xls valido del tuo broker."
        )
        return []

    i, cols = _trova_header(righe, _HEADER_MOVIMENTI, ["isin", "segno", "quantita"])
    if i is not None:
        logger.info(f"Formato dossier rilevato: Movimenti Dossier Titoli (da {origine})")
        return build_fifo_positions(_estrai_movimenti(righe[i + 1:], cols))

    i, cols = _trova_header(righe, _HEADER_SINTESI, ["isin", "prezzo_medio", "quantita"])
    if i is not None:
        logger.info(f"Formato dossier rilevato: Portafoglio di sintesi (da {origine})")
        return _estrai_posizioni_sintesi(righe[i + 1:], cols)

    logger.error(
        f"Intestazioni non riconosciute in {origine}: non corrispondono né a "
        "'Movimenti Dossier Titoli' né a 'Portafoglio di sintesi'."
    )
    return []


def load_isin_map(path=None):
    """Mappa ISIN -> ticker TradingView: secret ISIN_MAP_JSON se presente,
    altrimenti il file committato (che deve restare un template vuoto)."""
    if ISIN_MAP_JSON:
        try:
            return json.loads(ISIN_MAP_JSON)
        except Exception as e:
            logger.warning(f"ISIN_MAP_JSON illeggibile ({e})")
            return {}
    path = path or ISIN_MAP_PATH
    if not os.path.exists(path):
        logger.warning(f"Mappa ISIN→TradingView non trovata: né secret ISIN_MAP_JSON né {path}")
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Mappa ISIN→TradingView illeggibile ({e})")
        return {}


def sync_portfolio():
    """Punto d'ingresso: dossier → posizioni aperte → ticker TradingView.
    Restituisce la stessa forma di lista che il resto della pipeline si aspetta
    da PORTFOLIO ([{"symbol","name","type",...}]), con i campi aggiuntivi.
    Se l'ISIN non e' ancora mappato in data/isin_map.json, usa come
    suggerimento il ticker del broker (guess_tv_symbol) invece dell'ISIN
    nudo — resta comunque solo un suggerimento, mai un dato certo."""
    posizioni = _carica_posizioni()
    isin_map = load_isin_map()

    non_mappati = []
    out = []
    for p in posizioni:
        mapped = isin_map.get(p["isin"])
        if not mapped:
            non_mappati.append(f'{p["isin"]} ({p["titolo"]})')
        symbol = (mapped or {}).get("tv_symbol") or guess_tv_symbol(p.get("simbolo_broker")) or p["isin"]
        out.append({
            "symbol": symbol,
            "name": (mapped or {}).get("name", p["titolo"]),
            "type": (mapped or {}).get("type", p.get("tipo_broker", "Azione")),
            "isin": p["isin"],
            "quantita": p["quantita"],
            "prezzo_medio": p["prezzo_medio"],
            "divisa": p["divisa"],
            "data_apertura": p["data_apertura"],
            "giorni_detenzione": p["giorni_detenzione"],
        })
    if non_mappati:
        logger.warning(
            f"ISIN senza ticker TradingView confermato in {ISIN_MAP_PATH} (usato un "
            "suggerimento dal simbolo broker, da verificare nell'editor delle regole): "
            + "; ".join(non_mappati)
        )
    return out
