#!/usr/bin/env python3
"""
Log minimo dello stato "posizione vs EMA50/EMA200", una riga al giorno per
ISIN, in data/storico_trend.csv.

Serve solo a rispondere "da quanti giorni": la TradingView screener API
restituisce solo lo stato di OGGI (prezzo, EMA50, EMA200), non la data in
cui il prezzo ha incrociato la media — senza una serie storica non c'e'
modo di saperlo. Il conteggio e' quindi accurato dal giorno in cui questo
file ha iniziato a registrare; se lo stato attuale coincide gia' con la
riga piu' vecchia disponibile, il numero restituito e' un minimo ("almeno
N giorni"), non un dato certo su tutta la vita della posizione. Diventera'
piu' preciso man mano che il log si accumula nei run successivi.
"""
import csv
import logging
import os
from datetime import date, datetime

logger = logging.getLogger(__name__)

TREND_LOG_PATH = os.environ.get("TREND_LOG_PATH", "data/storico_trend.csv")
_FIELDS = ["data", "isin", "sopra_ema50", "sopra_ema200"]


def _ema_state(price, ema50, ema200):
    return {
        "sopra_ema50": bool(price and ema50 and price > ema50),
        "sopra_ema200": bool(price and ema200 and price > ema200),
    }


def append_today(portfolio_rows, path=None):
    """Aggiunge la riga di oggi per ogni posizione con un ISIN, una sola
    volta al giorno (rerun nello stesso giorno non duplicano)."""
    path = path or TREND_LOG_PATH
    today = date.today().isoformat()

    gia_presenti = set()
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("data") == today:
                    gia_presenti.add(row.get("isin"))

    nuove = []
    for p in portfolio_rows:
        isin = p.get("isin")
        if not isin or isin in gia_presenti:
            continue
        stato = _ema_state(p.get("price"), p.get("ema50"), p.get("ema200"))
        nuove.append({"data": today, "isin": isin,
                      "sopra_ema50": stato["sopra_ema50"], "sopra_ema200": stato["sopra_ema200"]})

    if not nuove:
        return
    scrivi_header = not os.path.exists(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        if scrivi_header:
            w.writeheader()
        w.writerows(nuove)
    logger.info(f"Storico trend: {len(nuove)} righe aggiunte per oggi ({path})")


def days_in_state(isin, field, current_value, path=None):
    """Da quanti giorni consecutivi (fino a oggi incluso) 'field' e' rimasto
    uguale a current_value per questo ISIN.
    Ritorna (giorni, certo): certo=False se si e' raggiunto l'inizio del log
    senza vedere un cambio di stato — il numero e' quindi un minimo."""
    path = path or TREND_LOG_PATH
    if not isin or not os.path.exists(path):
        return None, False

    righe = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("isin") == isin:
                righe.append(row)
    righe.sort(key=lambda r: r["data"], reverse=True)
    if not righe:
        return None, False

    target = str(current_value)
    ultima_coerente = None
    cambio_trovato = False
    for r in righe:
        if r.get(field) != target:
            cambio_trovato = True
            break
        ultima_coerente = r["data"]
    if ultima_coerente is None:
        return None, False

    inizio = datetime.strptime(ultima_coerente, "%Y-%m-%d").date()
    giorni = (date.today() - inizio).days
    return giorni, cambio_trovato
