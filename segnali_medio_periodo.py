#!/usr/bin/env python3
"""
Segnali di medio periodo (Fase 5, Sezione 4): doppio massimo/minimo,
divergenze RSI-prezzo, rotture 52 settimane, golden/death cross EMA50-200 —
tutti su candele SETTIMANALI, orizzonte 3-12 mesi — più volumi anomali
rispetto alla media a 50 GIORNI (l'unico, per richiesta esplicita, su base
giornaliera). Applicati solo alle posizioni aperte e a una watchlist
scritta a mano (data/watchlist.yaml), non a tutto il mercato.

Nessuna chiamata di rete qui: opera su bars_storico già scaricato
(generate_report.fetch_ohlc_range) e sul resample settimanale
(indicatori_storici.resample_settimanale). Un pattern che non è pulito
(picchi troppo distanti in livello, nessun ritracciamento vero) non viene
forzato: la funzione restituisce None invece di un falso positivo — la
sezione vuole "meno rumore", non un segnale ogni riga.
"""
import indicatori_storici as ind

RSI_PERIOD = 14


def rsi_series(closes, period=RSI_PERIOD):
    """RSI su una serie di chiusure (media mobile semplice sui guadagni/
    perdite, poi smoothing di Wilder). I primi `period` punti sono None."""
    if len(closes) <= period:
        return [None] * len(closes)
    out = [None] * period
    gains = losses = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains += max(delta, 0)
        losses += max(-delta, 0)
    avg_gain, avg_loss = gains / period, losses / period
    out.append(_rsi_from_avg(avg_gain, avg_loss))
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain, loss = max(delta, 0), max(-delta, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out.append(_rsi_from_avg(avg_gain, avg_loss))
    return out


def _rsi_from_avg(avg_gain, avg_loss):
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _pivot_massimi(bars, finestra=2):
    """Indici delle barre che sono un massimo locale (high >= alle `finestra`
    barre precedenti e successive)."""
    n = len(bars)
    return [i for i in range(finestra, n - finestra)
            if all(bars[i]["h"] >= bars[j]["h"] for j in range(i - finestra, i + finestra + 1) if j != i)]


def _pivot_minimi(bars, finestra=2):
    n = len(bars)
    return [i for i in range(finestra, n - finestra)
            if all(bars[i]["l"] <= bars[j]["l"] for j in range(i - finestra, i + finestra + 1) if j != i)]


def doppio_massimo(bars_settimanali, lookback=52, tolleranza=0.03, ritraccio_min=0.05):
    """Due picchi comparabili (entro `tolleranza`), separati da almeno 3
    settimane e da un ritracciamento di almeno `ritraccio_min` tra i due.
    None se non c'e' un pattern pulito nella finestra."""
    bars = bars_settimanali[-lookback:]
    if len(bars) < 10:
        return None
    picchi = _pivot_massimi(bars)
    if len(picchi) < 2:
        return None
    i2 = picchi[-1]
    for i1 in reversed(picchi[:-1]):
        if i2 - i1 < 3:
            continue
        p1, p2 = bars[i1]["h"], bars[i2]["h"]
        if abs(p2 - p1) / p1 > tolleranza:
            continue
        valle = min(b["l"] for b in bars[i1:i2 + 1])
        if (max(p1, p2) - valle) / max(p1, p2) < ritraccio_min:
            continue
        return {
            "tipo": "Doppio massimo", "data_picco1": bars[i1]["data"], "data_picco2": bars[i2]["data"],
            "distanza_pct": round(abs(p2 - p1) / p1 * 100, 1), "livello_conferma": round(valle, 4),
        }
    return None


def doppio_minimo(bars_settimanali, lookback=52, tolleranza=0.03, rimbalzo_min=0.05):
    """Simmetrico di doppio_massimo, su minimi locali."""
    bars = bars_settimanali[-lookback:]
    if len(bars) < 10:
        return None
    minimi = _pivot_minimi(bars)
    if len(minimi) < 2:
        return None
    i2 = minimi[-1]
    for i1 in reversed(minimi[:-1]):
        if i2 - i1 < 3:
            continue
        p1, p2 = bars[i1]["l"], bars[i2]["l"]
        if abs(p2 - p1) / p1 > tolleranza:
            continue
        picco = max(b["h"] for b in bars[i1:i2 + 1])
        if (picco - min(p1, p2)) / min(p1, p2) < rimbalzo_min:
            continue
        return {
            "tipo": "Doppio minimo", "data_picco1": bars[i1]["data"], "data_picco2": bars[i2]["data"],
            "distanza_pct": round(abs(p2 - p1) / p1 * 100, 1), "livello_conferma": round(picco, 4),
        }
    return None


def divergenza_rsi(bars_settimanali, lookback=52):
    """Il prezzo fa un nuovo massimo/minimo settimanale che l'RSI settimanale
    non conferma. None se non c'e' una divergenza pulita nella finestra."""
    bars = bars_settimanali[-lookback:]
    if len(bars) < 20:
        return None
    rsi = rsi_series([b["c"] for b in bars])

    picchi = [i for i in _pivot_massimi(bars) if rsi[i] is not None]
    if len(picchi) >= 2:
        i1, i2 = picchi[-2], picchi[-1]
        if bars[i2]["h"] > bars[i1]["h"] and rsi[i2] < rsi[i1]:
            return {"tipo": "Divergenza ribassista (RSI settimanale)", "prezzo": "nuovo massimo",
                    "data_primo": bars[i1]["data"], "data_secondo": bars[i2]["data"],
                    "rsi_primo": round(rsi[i1], 1), "rsi_secondo": round(rsi[i2], 1)}

    minimi = [i for i in _pivot_minimi(bars) if rsi[i] is not None]
    if len(minimi) >= 2:
        i1, i2 = minimi[-2], minimi[-1]
        if bars[i2]["l"] < bars[i1]["l"] and rsi[i2] > rsi[i1]:
            return {"tipo": "Divergenza rialzista (RSI settimanale)", "prezzo": "nuovo minimo",
                    "data_primo": bars[i1]["data"], "data_secondo": bars[i2]["data"],
                    "rsi_primo": round(rsi[i1], 1), "rsi_secondo": round(rsi[i2], 1)}
    return None


def rottura_52_settimane(bars_settimanali):
    """Nuovo massimo o minimo a 52 settimane, calcolato sulle candele
    settimanali ricostruite (non sul campo scalare TV)."""
    if len(bars_settimanali) < 53:
        return None
    finestra = bars_settimanali[-53:-1]
    corrente = bars_settimanali[-1]
    massimo_52 = max(b["h"] for b in finestra)
    minimo_52 = min(b["l"] for b in finestra)
    if corrente["c"] > massimo_52:
        return {"tipo": "Rottura massimo 52 settimane", "data": corrente["data"],
                "livello_precedente": round(massimo_52, 4)}
    if corrente["c"] < minimo_52:
        return {"tipo": "Rottura minimo 52 settimane", "data": corrente["data"],
                "livello_precedente": round(minimo_52, 4)}
    return None


def cross_settimanale(bars_settimanali):
    """Golden/death cross EMA50-EMA200 calcolate su chiusure settimanali
    (richiede ~200 settimane di storico, non giornaliero)."""
    sopra, giorni, certo = ind.golden_death_cross(bars_settimanali, 50, 200)
    if sopra is None:
        return None
    return {"tipo": "Golden cross" if sopra else "Death cross", "giorni_da_incrocio": giorni, "certo": certo}


def volume_anomalo(bars_giornalieri, soglia=2.0, periodo=50):
    """Spike di volume rispetto alla media A 50 GIORNI (non settimanali:
    e' l'unico segnale della sezione richiesto su base giornaliera)."""
    if len(bars_giornalieri) < periodo + 1:
        return None
    volumi = [b.get("v") or 0 for b in bars_giornalieri]
    media_50 = sum(volumi[-periodo - 1:-1]) / periodo
    corrente = volumi[-1]
    if media_50 > 0 and corrente > soglia * media_50:
        return {"tipo": "Volume anomalo", "data": bars_giornalieri[-1]["data"],
                "rapporto": round(corrente / media_50, 1)}
    return None


def calcola_segnali(bars_giornalieri):
    """Tutti i segnali di medio periodo rilevati per un titolo, dato il suo
    storico giornaliero (bars_storico). Lista, può essere vuota."""
    if not bars_giornalieri:
        return []
    settimanali = ind.resample_settimanale(bars_giornalieri)
    segnali = []
    for fn in (doppio_massimo, doppio_minimo, divergenza_rsi, rottura_52_settimane, cross_settimanale):
        r = fn(settimanali)
        if r:
            segnali.append(r)
    v = volume_anomalo(bars_giornalieri)
    if v:
        segnali.append(v)
    return segnali
