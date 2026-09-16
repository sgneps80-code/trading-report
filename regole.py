#!/usr/bin/env python3
"""
Regole di posizione (Fase 3): stop, target, data di revisione, tesi ed
eventi noti per ogni ISIN, scritti a mano in data/regole_posizioni.yaml.
Il report confronta lo stato attuale con questi valori — non genera
giudizi propri (niente "compra/vendi": solo fatti da mettere a confronto
con quello che hai scritto tu).

Legge anche data/eventi_macro.yaml (riunioni BCE/Fed): sono date ufficiali
pubbliche, non richiedono un provider a pagamento, quindi restano un file
versionato da aggiornare una volta l'anno.

Legge anche data/watchlist.yaml: i titoli, oltre alle posizioni aperte, su
cui calcolare i segnali di medio periodo (Sezione 4) — scritta a mano,
niente scansione di tutto il mercato.

Il repo e' pubblico: regole (stop/target/tesi) e watchlist sono dati
personali. Fonte primaria = GitHub Secret (REGOLE_POSIZIONI_YAML,
WATCHLIST_YAML, entrambi YAML come stringa), mai committato in chiaro.
Senza secret si legge il file in data/ — che deve restare un template
vuoto. Le date BCE/Fed non sono sensibili: eventi_macro.yaml resta
sempre un file committato normale.
"""
import logging
import os
from datetime import date, datetime

logger = logging.getLogger(__name__)

REGOLE_PATH = os.environ.get("REGOLE_PATH", "data/regole_posizioni.yaml")
EVENTI_MACRO_PATH = os.environ.get("EVENTI_MACRO_PATH", "data/eventi_macro.yaml")
WATCHLIST_PATH = os.environ.get("WATCHLIST_PATH", "data/watchlist.yaml")
REGOLE_POSIZIONI_YAML = os.environ.get("REGOLE_POSIZIONI_YAML", "")
WATCHLIST_YAML = os.environ.get("WATCHLIST_YAML", "")

_NOMI_MACRO = {"bce": "Riunione BCE", "fed": "Riunione Fed (FOMC)"}


def _parse_date(v):
    if isinstance(v, date):
        return v
    if v is None:
        return None
    try:
        return datetime.strptime(str(v).strip(), "%Y-%m-%d").date()
    except ValueError:
        logger.warning(f"Data non valida ({v!r}), formato atteso YYYY-MM-DD")
        return None


def _load_yaml(path):
    if not os.path.exists(path):
        return None
    try:
        import yaml
    except ImportError:
        logger.error("PyYAML non installato: impossibile leggere " + path)
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"File YAML illeggibile ({path}): {e}")
        return None


def _load_yaml_source(secret_value, path, nome_secret):
    """Secret (stringa YAML) se presente, altrimenti il file committato."""
    if secret_value:
        try:
            import yaml
            return yaml.safe_load(secret_value) or {}
        except Exception as e:
            logger.warning(f"{nome_secret} illeggibile ({e})")
            return None
    return _load_yaml(path)


def load_regole(path=None):
    """Restituisce {isin: {stop, target, revisione, tesi, eventi}}.
    Un ISIN senza voce nel file ha semplicemente tutti i campi assenti:
    il report lo segnala come 'nessuna regola scritta', non e' un errore."""
    path = path or REGOLE_PATH
    raw = _load_yaml_source(REGOLE_POSIZIONI_YAML, path, "REGOLE_POSIZIONI_YAML")
    if raw is None:
        logger.warning(f"Regole posizioni non trovate: né secret REGOLE_POSIZIONI_YAML né {path}")
        return {}

    out = {}
    for isin, r in raw.items():
        if not isinstance(r, dict):
            continue  # scarta chiavi non-posizione (es. commenti promossi a chiave per errore)
        eventi = []
        for ev in (r.get("eventi") or []):
            if not isinstance(ev, dict):
                continue
            d = _parse_date(ev.get("data"))
            if d:
                eventi.append({"tipo": ev.get("tipo", "evento"), "data": d})
        out[str(isin)] = {
            "stop": r.get("stop"),
            "target": r.get("target"),
            "revisione": _parse_date(r.get("revisione")),
            "tesi": r.get("tesi", ""),
            "eventi": eventi,
        }
    return out


def load_eventi_macro(path=None):
    """Riunioni BCE/Fed dell'anno, come lista di {data, titolo, tipo}."""
    path = path or EVENTI_MACRO_PATH
    raw = _load_yaml(path)
    if raw is None:
        logger.warning(f"Calendario macro non trovato o illeggibile: {path}")
        return []

    out = []
    for chiave, date_list in raw.items():
        titolo = _NOMI_MACRO.get(str(chiave).lower(), str(chiave))
        for d in (date_list or []):
            data = _parse_date(d)
            if data:
                out.append({"data": data, "titolo": titolo, "tipo": "Macro"})
    return out


def load_watchlist(path=None):
    """Titoli da monitorare per i segnali di medio periodo (Sezione 4), oltre
    alle posizioni aperte. Restituisce [{"symbol", "name"}]."""
    path = path or WATCHLIST_PATH
    raw = _load_yaml_source(WATCHLIST_YAML, path, "WATCHLIST_YAML")
    if raw is None:
        logger.warning(f"Watchlist non trovata: né secret WATCHLIST_YAML né {path}")
        return []

    out = []
    for v in (raw.get("simboli") or []):
        if isinstance(v, dict) and v.get("symbol"):
            symbol = str(v["symbol"]).strip()
            out.append({"symbol": symbol, "name": v.get("name", symbol)})
    return out
