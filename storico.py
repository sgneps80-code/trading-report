#!/usr/bin/env python3
"""
Storico persistente (Fase 4): una riga al giorno per titolo in
data/storico_indicatori.csv, con i valori che la TradingView screener API
restituisce solo come stato del giorno (close, high/low, RSI, EMA20/50/200,
MACD histogram, performance 1M/3M).

Due categorie:
- "posizione": le posizioni aperte del conto B (chiave ISIN).
- "segnale": i titoli usciti oggi in "Da approfondire" (chiave symbol) — per
  poter verificare, col tempo, se quei segnali si sono confermati o no.

Perche' serve: lo screener non da' serie storiche, solo il valore di oggi.
Senza salvarlo ogni giorno non si possono calcolare indicatori di medio
periodo veri (Fase 5) ne' controllare a posteriori come sono andati i
segnali. CSV append-only (non SQLite): un file SQLite riscritto ogni giorno
produce un blob binario diverso ad ogni commit, illeggibile nei diff e via
via piu' pesante nella storia git; un CSV con solo righe nuove resta
leggero e ispezionabile.

Il repo e' pubblico: ISIN e ticker vengono pseudonimizzati (HMAC-SHA256
troncato, chiave = secret STORICO_SALT) prima di scrivere il CSV. Chi
guarda il repo vede hash, non i tuoi titoli reali; il codice, che conosce
il secret, ricalcola lo stesso hash per rileggere la propria storia. Senza
STORICO_SALT (uso locale) i valori restano in chiaro, con un avviso.
"""
import csv
import hashlib
import hmac
import logging
import os
from datetime import date, datetime

logger = logging.getLogger(__name__)

STORICO_PATH = os.environ.get("STORICO_PATH", "data/storico_indicatori.csv")
STORICO_SALT = os.environ.get("STORICO_SALT", "")

_FIELDS = ["data", "categoria", "symbol", "isin", "close", "high", "low", "volume", "vol_10d",
           "rsi", "ema20", "ema50", "ema200", "macd_hist", "perf_1m", "perf_3m"]
_NUMERICI = [c for c in _FIELDS if c not in ("data", "categoria", "symbol", "isin")]

_salt_avvisato = False


def _pseudonimizza(valore):
    """ISIN/symbol reali -> hash stabile (stesso valore, stesso hash, sempre)
    finche' STORICO_SALT non cambia. Senza il secret, valori in chiaro."""
    global _salt_avvisato
    if not valore:
        return valore
    if not STORICO_SALT:
        if not _salt_avvisato:
            logger.warning("STORICO_SALT non impostato: ISIN/symbol nello storico NON sono pseudonimizzati")
            _salt_avvisato = True
        return valore
    return hmac.new(STORICO_SALT.encode(), valore.encode(), hashlib.sha256).hexdigest()[:16]


def _num(v):
    return "" if v is None else v


def _read_rows(path):
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                d = datetime.strptime(row["data"], "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            parsed = {"data": d, "categoria": row.get("categoria"),
                      "symbol": row.get("symbol"), "isin": row.get("isin") or None}
            for campo in _NUMERICI:
                v = row.get(campo)
                parsed[campo] = float(v) if v not in (None, "") else None
            out.append(parsed)
    return out


def record_daily(portfolio, segnali, path=None):
    """Aggiunge la riga di oggi per le posizioni aperte e per i segnali del
    giorno, una sola volta al giorno per (categoria, symbol)."""
    path = path or STORICO_PATH
    today = date.today().isoformat()

    esistenti = set()
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("data") == today:
                    esistenti.add((row.get("categoria"), row.get("symbol")))

    def righe_da(items, categoria):
        out = []
        for r in items:
            symbol_raw = r.get("symbol") or r.get("yf_symbol")
            if not symbol_raw:
                continue
            symbol = _pseudonimizza(symbol_raw)
            if (categoria, symbol) in esistenti:
                continue
            out.append({
                "data": today, "categoria": categoria, "symbol": symbol,
                "isin": _pseudonimizza(r.get("isin") or ""),
                "close": _num(r.get("price")), "high": _num(r.get("day_high")), "low": _num(r.get("day_low")),
                "volume": _num(r.get("volume")), "vol_10d": _num(r.get("vol_10d")),
                "rsi": _num(r.get("rsi")), "ema20": _num(r.get("ema20")), "ema50": _num(r.get("ema50")),
                "ema200": _num(r.get("ema200")), "macd_hist": _num(r.get("macd_hist")),
                "perf_1m": _num(r.get("perf_1m")), "perf_3m": _num(r.get("perf_3m")),
            })
        return out

    nuove = righe_da(portfolio, "posizione") + righe_da(segnali, "segnale")
    if not nuove:
        return
    scrivi_header = not os.path.exists(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        if scrivi_header:
            w.writeheader()
        w.writerows(nuove)
    logger.info(f"Storico indicatori: {len(nuove)} righe aggiunte per oggi ({path})")


def load_history(symbol=None, isin=None, categoria=None, path=None):
    """Serie storica filtrata, ordinata per data crescente. Uso previsto:
    calcolo dei segnali di medio periodo (Fase 5) e verifica a posteriori
    dei segnali passati, una volta che il log avra' accumulato settimane/mesi."""
    path = path or STORICO_PATH
    if not os.path.exists(path):
        return []
    righe = _read_rows(path)
    if symbol:
        righe = [r for r in righe if r["symbol"] == _pseudonimizza(symbol)]
    if isin:
        righe = [r for r in righe if r["isin"] == _pseudonimizza(isin)]
    if categoria:
        righe = [r for r in righe if r["categoria"] == categoria]
    righe.sort(key=lambda r: r["data"])
    return righe


def valore_precedente(symbol=None, isin=None, categoria=None, path=None):
    """L'ultima riga PRECEDENTE a oggi per questo titolo (None se non esiste:
    primo run per questo titolo, o storico non ancora accumulato). Usato dal
    prompt di analisi (Fase 6) per descrivere cosa e' cambiato rispetto a
    ieri, invece di farlo indovinare al modello."""
    storia = load_history(symbol=symbol, isin=isin, categoria=categoria, path=path)
    precedenti = [r for r in storia if r["data"] < date.today()]
    return precedenti[-1] if precedenti else None


def giorni_in_stato(key_value, predicate, current_value, key="isin", path=None):
    """Da quanti giorni consecutivi (fino a oggi incluso) predicate(riga) e'
    rimasto uguale a current_value per key==key_value.
    Ritorna (giorni, certo): certo=False se si e' raggiunto l'inizio del log
    senza vedere un cambio di stato — il numero e' quindi un minimo, non un
    dato certo su tutta la vita della posizione."""
    path = path or STORICO_PATH
    if not key_value or not os.path.exists(path):
        return None, False

    key_value = _pseudonimizza(key_value) if key in ("isin", "symbol") else key_value
    righe = [r for r in _read_rows(path) if r.get(key) == key_value]
    righe.sort(key=lambda r: r["data"], reverse=True)
    if not righe:
        return None, False

    ultima_coerente = None
    cambio_trovato = False
    for r in righe:
        if predicate(r) != current_value:
            cambio_trovato = True
            break
        ultima_coerente = r["data"]
    if ultima_coerente is None:
        return None, False

    giorni = (date.today() - ultima_coerente).days
    return giorni, cambio_trovato
