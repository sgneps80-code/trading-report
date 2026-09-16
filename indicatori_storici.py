#!/usr/bin/env python3
"""
Indicatori di medio periodo calcolati su storico di mercato REALE (2 anni
di chiusure giornaliere/settimanali da Yahoo Finance, via
generate_report.fetch_ohlc_range), non sul nostro log giornaliero
(storico.py): quello parte vuoto e richiederebbe mesi per dire qualcosa,
mentre la storia dei prezzi esiste già ed è scaricabile subito.

Nessuna chiamata di rete qui dentro: solo calcolo su una serie già scaricata.
"""
from datetime import date


def ema_series(closes, period):
    """EMA su una lista di chiusure in ordine cronologico.
    Seed = SMA dei primi `period` valori (convenzione comune, coerente
    con TradingView). I primi (period-1) punti sono None: dati insufficienti."""
    if len(closes) < period:
        return [None] * len(closes)
    k = 2 / (period + 1)
    out = [None] * (period - 1)
    seed = sum(closes[:period]) / period
    out.append(seed)
    prev = seed
    for c in closes[period:]:
        prev = c * k + prev * (1 - k)
        out.append(prev)
    return out


def stato_e_durata(dates, valori_a, valori_b, oggi=None):
    """Confronta due serie allineate per data (es. prezzo vs EMA50, o EMA50
    vs EMA200) e determina se A>B oggi e da quanti giorni consecutivi,
    scandendo a ritroso la finestra di storico disponibile.

    Ritorna (a_sopra_b, giorni, certo):
    - a_sopra_b: True/False/None (None se non ci sono dati sufficienti)
    - giorni: giorni trascorsi dall'ultimo cambio di stato visibile
    - certo: True se il cambio di stato e' visibile nella finestra scaricata;
      False se lo stato attuale persiste fin dall'inizio della finestra
      (il numero e' quindi un minimo, non un dato certo su tutta la storia)."""
    coppie = [(d, a, b) for d, a, b in zip(dates, valori_a, valori_b) if a is not None and b is not None]
    if not coppie:
        return None, None, False

    oggi = oggi or date.today()
    stato_attuale = coppie[-1][1] > coppie[-1][2]
    ultima_coerente = coppie[-1][0]
    cambio_trovato = False
    for d, a, b in reversed(coppie):
        if (a > b) != stato_attuale:
            cambio_trovato = True
            break
        ultima_coerente = d

    giorni = (oggi - ultima_coerente).days
    return stato_attuale, giorni, cambio_trovato


def trend_vs_ema(bars, period, oggi=None):
    """Da una lista di barre {'data','c',...} in ordine cronologico, calcola
    se il prezzo e' sopra/sotto la sua EMA(period) e da quanti giorni.
    Wrapper di comodo su ema_series + stato_e_durata per il caso piu' comune
    (prezzo vs una singola EMA, usato in Sezione 1)."""
    if not bars:
        return None, None, False
    dates = [b["data"] for b in bars]
    closes = [b["c"] for b in bars]
    ema = ema_series(closes, period)
    return stato_e_durata(dates, closes, ema, oggi=oggi)


def golden_death_cross(bars, corto=50, lungo=200, oggi=None):
    """Da una lista di barre {'data','c',...}, stato dell'allineamento
    EMA(corto) vs EMA(lungo) e da quanti giorni (golden cross se True,
    death cross se False). Usato in Sezione 4 (segnali di medio periodo)."""
    if not bars:
        return None, None, False
    dates = [b["data"] for b in bars]
    closes = [b["c"] for b in bars]
    e_corto = ema_series(closes, corto)
    e_lungo = ema_series(closes, lungo)
    return stato_e_durata(dates, e_corto, e_lungo, oggi=oggi)


def resample_settimanale(bars):
    """Raggruppa barre giornaliere in barre settimanali (lun-dom, ISO week):
    apertura del primo giorno, chiusura dell'ultimo, max/min della settimana,
    volume totale. Richiesto dai segnali su candele settimanali (Fase 5)."""
    settimane = {}
    ordine = []
    for b in bars:
        key = b["data"].isocalendar()[:2]  # (anno ISO, settimana ISO)
        if key not in settimane:
            settimane[key] = {"data": b["data"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"],
                               "v": b.get("v") or 0}
            ordine.append(key)
        else:
            w = settimane[key]
            w["h"] = max(w["h"], b["h"])
            w["l"] = min(w["l"], b["l"])
            w["c"] = b["c"]
            w["data"] = b["data"]  # ultima data della settimana (chiusura)
            w["v"] = (w["v"] or 0) + (b.get("v") or 0)
    return [settimane[k] for k in ordine]
