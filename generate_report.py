#!/usr/bin/env python3
"""
Trading Report — TradingView Edition
Screener:  scanner.tradingview.com  (Italia + USA, incluse small/mid cap)
Analisi:   RSI + MACD + Trend EMA + Raccomandazione TV aggregata (26 indicatori)
AI:        Anthropic Claude Haiku
"""

import os, json, hashlib, html, logging
from datetime import datetime, date, timedelta, timezone
import requests
import anthropic
import portfolio_sync
import regole
import storico
import indicatori_storici
import segnali_medio_periodo

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ─── PORTFOLIO ────────────────────────────────────────────────────────────────
# Priorita': override manuale da workflow_dispatch > dossier XLS sincronizzato
# (fonte primaria, vedi portfolio_sync.py) > vecchio secret JSON come ripiego,
# per non rompere il report se il dossier non e' stato ancora caricato nel repo.
_portfolio_input = os.environ.get("PORTFOLIO_INPUT", "").strip()
if _portfolio_input:
    PORTFOLIO = json.loads(_portfolio_input)
    logger.info("Portfolio caricato da workflow_dispatch (override manuale)")
elif portfolio_sync.dossier_disponibile():
    PORTFOLIO = portfolio_sync.sync_portfolio()
    logger.info(f"Portfolio sincronizzato da dossier XLS: {len(PORTFOLIO)} posizioni aperte")
else:
    PORTFOLIO = json.loads(os.environ.get("PORTFOLIO_JSON", "[]"))
    logger.info("Portfolio caricato da PORTFOLIO_JSON secret (legacy: nessun dossier XLS trovato)")

# ─── TRADINGVIEW API ──────────────────────────────────────────────────────────
TV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Referer": "https://www.tradingview.com/",
    "Origin": "https://www.tradingview.com",
}

# Colonne richieste allo screener TradingView
TV_COLS = [
    "name",                     # ticker (es. ENI)
    "description",              # nome azienda
    "close",                    # prezzo corrente
    "open",                     # apertura giornaliera (per candele 1D)
    "high",                     # massimo giornaliero
    "low",                      # minimo giornaliero
    "change",                   # variazione giornaliera %
    "volume",                   # volume
    "average_volume_10d_calc",  # volume medio 10gg
    "RSI",                      # RSI(14) giornaliero
    "EMA20",                    # EMA 20
    "EMA50",                    # EMA 50
    "EMA200",                   # EMA 200
    "MACD.macd",                # MACD line
    "MACD.signal",              # MACD signal line
    "MACD.hist",                # MACD histogram (conferma forza del segnale)
    "change|1M",                # performance 1 mese %
    "Perf.3M",                  # performance 3 mesi % (campo nativo: "change|3M" non esiste,
                                 # |3M non e' una risoluzione valida e torna sempre nullo)
    "Rec.All",                  # raccomandazione aggregata TV: -1 vendi forte → +1 compra forte
    "market_cap_basic",         # capitalizzazione di mercato
    "open|1W",                  # apertura settimanale (per candele 1W)
    "high|1W",                  # massimo settimanale
    "low|1W",                   # minimo settimanale
    "close|1W",                 # chiusura settimanale
    "High.3M",                  # massimo 3 mesi (pattern detection)
    "Low.3M",                   # minimo 3 mesi (pattern detection)
    "52WkHigh",                 # massimo 52 settimane
    "52WkLow",                  # minimo 52 settimane
    "type",                     # tipo TV: stock / fund / structured / dr ...
    "typespecs",                # sottotipo: ["etf"], ["etn"], ["etc"], ["common"] ...
]

# Colonne richieste SOLO per gli ETP. Tenute fuori da TV_COLS di proposito:
# se questi nomi non sono validi sullo scanner, romperebbero anche le query azioni.
ETF_EXTRA_COLS = [
    "expense_ratio",            # TER del fondo (per punteggio costo)
    "aum",                      # masse gestite / assets under management
]

def detect_candle(o, h, l, c, prev_o=None, prev_c=None):
    """Riconosce il pattern candela giapponese su OHLC scalare."""
    try:
        rng = h - l
        if rng < 1e-9:
            return "—"
        body  = abs(c - o)
        upper = h - max(c, o)
        lower = min(c, o) - l
        body_r = body / rng

        if body_r < 0.08:
            return "Doji"
        if lower > 2 * body and upper < body:
            return "Hammer ▲" if c >= o else "Hanging Man ▼"
        if upper > 2 * body and lower < body:
            return "Shooting Star ▼" if c < o else "Inv. Hammer ▲"
        if prev_o is not None and prev_c is not None:
            if c > o and c > prev_c and o < prev_o:
                return "Bullish Engulfing ▲"
            if c < o and c < prev_c and o > prev_o:
                return "Bearish Engulfing ▼"
        if body_r > 0.6:
            return "Bullish" if c >= o else "Bearish"
        return "Neutro"
    except Exception:
        return "—"

def tv_request(url, payload):
    """Chiama la TV screener API con 3 tentativi."""
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, headers=TV_HEADERS, timeout=25)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"TV request attempt {attempt+1}/3: {e}")
            if attempt == 2:
                raise
    return {}

def parse_tv_row(row, cols=None):
    """Converte una riga dello screener TV nel formato interno.
    `cols` deve corrispondere ESATTAMENTE alle colonne richieste nel payload:
    lo zip qui sotto e' posizionale, quindi un mismatch disallinea tutti i campi."""
    cols = cols or TV_COLS
    s    = row.get("s", "")       # "BVME:ENI"
    vals = row.get("d", [])
    if len(vals) != len(cols):
        # Guardia: senza questo, uno zip corto assegna silenziosamente i valori
        # alle colonne sbagliate (RSI al posto del MACD, ecc.)
        logger.warning(f"Colonne disallineate per {s}: attese {len(cols)}, ricevute {len(vals)}")
    d    = dict(zip(cols, vals))

    ticker = s.split(":")[-1]     # "ENI"
    price  = d.get("close") or 0
    o_day  = d.get("open")  or 0
    h_day  = d.get("high")  or 0
    l_day  = d.get("low")   or 0
    o_week = d.get("open|1W")  or 0
    h_week = d.get("high|1W")  or 0
    l_week = d.get("low|1W")   or 0
    c_week = d.get("close|1W") or 0
    ema20  = d.get("EMA20")  or 0
    ema50  = d.get("EMA50")  or 0
    ema200 = d.get("EMA200") or 0
    rsi    = d.get("RSI")
    macd   = d.get("MACD.macd")   or 0
    sig    = d.get("MACD.signal") or 0
    hist   = d.get("MACD.hist")   or (macd - sig)
    p1m    = d.get("change|1M")
    p3m    = d.get("Perf.3M")
    rec    = d.get("Rec.All") or 0
    vol    = d.get("volume")                 or 0
    vol10d = d.get("average_volume_10d_calc") or 0
    high3m = d.get("High.3M")  or 0
    low3m  = d.get("Low.3M")   or 0
    high52 = d.get("52WkHigh") or 0
    low52  = d.get("52WkLow")  or 0
    sec_type  = d.get("type")
    typespecs = d.get("typespecs") or []
    ter       = d.get("expense_ratio")
    aum       = d.get("aum")

    # ── Candele giapponesi ──
    candle_d = detect_candle(o_day, h_day, l_day, price) if h_day and l_day else "—"
    candle_w = detect_candle(o_week, h_week, l_week, c_week) if h_week and l_week else "—"

    # ── Trend rispetto alle EMA ──
    if price and ema20 and ema50:
        if price > ema20 > ema50:
            trend = "Rialzista"
            if ema200 and price > ema200:
                trend = "Rialzista (>EMA200)"
        elif price < ema20 < ema50:
            trend = "Ribassista"
        elif price > ema20:
            trend = "Sopra EMA20"
        else:
            trend = "Laterale"
    else:
        trend = "n.d."

    # ── MACD: nuovo indicatore di tendenza ──
    # Histogram > 0 + MACD > Signal = momentum rialzista confermato
    if hist > 0 and macd > sig:
        macd_str = "↑ Rialzista"
    elif hist < 0 and macd < sig:
        macd_str = "↓ Ribassista"
    elif hist > 0:
        macd_str = "↑ In accelerazione"
    else:
        macd_str = "↓ In decelerazione"

    # ── Raccomandazione TV aggregata (26 indicatori) ──
    if rec >= 0.5:
        rec_str = "Compra Forte"
    elif rec >= 0.1:
        rec_str = "Compra"
    elif rec <= -0.5:
        rec_str = "Vendi Forte"
    elif rec <= -0.1:
        rec_str = "Vendi"
    else:
        rec_str = "Neutro"

    return {
        "tv_symbol":  s,
        "symbol":     ticker,
        "yf_symbol":  ticker,   # aggiornato per portfolio
        "name":       d.get("description") or ticker,
        "price":      round(price, 2) if price else None,
        "rsi":        round(rsi, 1)   if rsi   else None,
        "ema20":      ema20,
        "ema50":      ema50,
        "ema200":     ema200,
        "macd_str":   macd_str,
        "macd_hist":  hist,      # usato per filtro Python
        "candle_d":   candle_d,
        "candle_w":   candle_w,
        "day_high":   h_day or None,   # per il resample settimanale dello storico (Fase 4/5)
        "day_low":    l_day or None,
        "perf_1m":    round(p1m, 1) if p1m is not None else None,
        "perf_3m":    round(p3m, 1) if p3m is not None else None,
        "trend":      trend,
        "rec":        rec,
        "rec_str":    rec_str,
        "vol_ratio":  round(vol / vol10d, 2) if vol10d > 0 else None,
        "volume":     vol,
        "vol_10d":    vol10d,
        "macd":       macd,
        "macd_sig":   sig,
        "market_cap": d.get("market_cap_basic"),
        "high_3m":    high3m,
        "low_3m":     low3m,
        "high_52w":   high52,
        "low_52w":    low52,
        "sec_type":   sec_type,
        "typespecs":  typespecs,
        "expense_ratio": ter,
        "aum":        aum,
    }

def momentum_score(d):
    """Score composito per ordinare i risultati dello screener."""
    return (
        (d.get("perf_1m") or 0) * 0.40 +
        (d.get("perf_3m") or 0) * 0.25 +
        ((d.get("rsi") or 50) - 50) * 0.15 +
        (d.get("rec") or 0) * 12 +
        ((d.get("vol_ratio") or 1) - 1) * 3
    )

# ─── HELPER FILTRO PYTHON ────────────────────────────────────────────────────
MIN_LIQUIDITY_EUR = 200_000  # controvalore medio giornaliero minimo (prezzo x volume medio 10gg)

def _passes_momentum(r, min_price=0.2, min_perf1m=0, min_liquidity=MIN_LIQUIDITY_EUR):
    """Filtro applicato in Python dopo la risposta TV (evita cross-column filter API)."""
    if not r.get("price") or r["price"] < min_price:
        return False
    # Liquidita': scarta i titoli su cui non si riuscirebbe a uscire facilmente.
    # Approssimazione: soglia applicata nella valuta nativa del titolo (EUR per l'Italia,
    # USD per gli USA), senza conversione di cambio — i due tassi sono vicini a parita'
    # e la soglia serve a scartare le microcap illiquide, non a essere precisa al centesimo.
    if r["price"] * (r.get("vol_10d") or 0) < min_liquidity:
        return False
    ema20 = r.get("ema20") or 0
    ema50 = r.get("ema50") or 0
    # Trend: prezzo sopra EMA20 e EMA20 sopra EMA50
    if not (ema20 and ema50 and r["price"] > ema20 > ema50):
        return False
    # Performance mensile positiva
    if (r.get("perf_1m") or 0) < min_perf1m:
        return False
    # MACD in territorio positivo (histogram > 0)
    if (r.get("macd_hist") or 0) <= 0:
        return False
    return True

def classify_trend_rimbalzo(r):
    """TREND: sale a 1M E a 3M. RIMBALZO: sale a 1M ma e' ancora sotto lo zero a 3M.
    None se il 3M non e' disponibile (non dovrebbe accadere dopo il fix di Perf.3M)."""
    p1m, p3m = r.get("perf_1m"), r.get("perf_3m")
    if p1m is None or p3m is None:
        return None
    if p1m > 0 and p3m > 0:
        return "TREND"
    if p1m > 0 and p3m < 0:
        return "RIMBALZO"
    return None

# ─── SCREENER ITALIA (tutti i titoli quotati su Borsa Italiana) ───────────────
def screen_italy():
    logger.info("Screening Italia — TradingView (tutti i titoli)...")
    payload = {
        # Filtri minimi sull'API: solo RSI e volume minimo
        # I confronti colonna-colonna (close>EMA) vengono fatti in Python
        "filter": [
            {"left": "RSI",                     "operation": "in_range", "right": [35, 82]},
            {"left": "average_volume_10d_calc", "operation": "greater",  "right": 5000},
            {"left": "MACD.hist",               "operation": "greater",  "right": 0},
        ],
        "options": {"lang": "en"},
        "markets": ["italy"],
        "symbols": {"query": {"types": ["stock"]}, "tickers": []},
        "columns": TV_COLS,
        "sort": {"sortBy": "change|1M", "sortOrder": "desc"},
        "range": [0, 200]
    }
    data = tv_request("https://scanner.tradingview.com/italy/scan", payload)
    rows = [parse_tv_row(r) for r in (data.get("data") or [])]
    rows = [r for r in rows if _passes_momentum(r, min_price=0.2, min_perf1m=0)]
    rows.sort(key=momentum_score, reverse=True)
    logger.info(f"Italia: {len(rows)} titoli → top {min(5, len(rows))}")
    return rows[:5]

# ─── SCREENER USA (large + mid + small cap) ───────────────────────────────────
def screen_usa():
    logger.info("Screening USA — TradingView (tutte le cap)...")
    payload = {
        "filter": [
            {"left": "RSI",                     "operation": "in_range", "right": [35, 82]},
            {"left": "average_volume_10d_calc", "operation": "greater",  "right": 100000},
            {"left": "market_cap_basic",        "operation": "greater",  "right": 100000000},
            {"left": "MACD.hist",               "operation": "greater",  "right": 0},
        ],
        "options": {"lang": "en"},
        "markets": ["america"],
        "symbols": {"query": {"types": ["stock"]}, "tickers": []},
        "columns": TV_COLS,
        "sort": {"sortBy": "Rec.All", "sortOrder": "desc"},
        "range": [0, 200]
    }
    data = tv_request("https://scanner.tradingview.com/america/scan", payload)
    rows = [parse_tv_row(r) for r in (data.get("data") or [])]
    rows = [r for r in rows if _passes_momentum(r, min_price=1.0, min_perf1m=1)]
    rows.sort(key=momentum_score, reverse=True)
    logger.info(f"USA: {len(rows)} titoli → top {min(5, len(rows))}")
    return rows[:5]

# ─── SCREENER ETF / ETN / ETC (solo Borsa Italiana) ───────────────────────────
_ETP_TYPESPECS = {"etf", "etn", "etc", "etp"}
# Typespecs da escludere SEMPRE: sono fondi, non ETP negoziati in continua.
_ESCLUSI_TYPESPECS = {"closedend", "mutual", "openend", "hedge"}

def _is_etp(r):
    """True solo per ETF, ETN o ETC.

    La diagnostica ha mostrato che il mercato 'italy' restituisce sotto
    type='fund' anche fondi chiusi (typespecs=['closedend']) e fondi comuni:
    non basta piu' accettare qualsiasi 'fund', serve il typespec esplicito.
    """
    specs = r.get("typespecs") or []
    if isinstance(specs, str):
        specs = [specs]
    specs = {str(s).lower() for s in specs}
    sec_type = (r.get("sec_type") or "").lower()

    # Esclusione esplicita: fondi chiusi/comuni non sono ETP
    if specs & _ESCLUSI_TYPESPECS:
        return False
    # Accetta fund/structured solo con typespec ETP confermato
    if sec_type in ("fund", "structured") and (specs & _ETP_TYPESPECS):
        return True
    return False

# ── Eleggibilità e punteggio di convenienza per gli ETP ──
def _passes_etp(r, min_price=1.0):
    """Cancello morbido: liquidità + trend di fondo.
    Niente stacking rigido delle EMA veloci (prezzo>EMA20>EMA50), che svuotava la lista:
    gli ETP diversificati si muovono lenti e scendono spesso sotto la EMA20 nei ritracci."""
    price = r.get("price") or 0
    if price < min_price:
        return False
    # Liquidità in CONTROVALORE (prezzo × volume medio 10gg), non in numero di quote
    vol10d = r.get("vol_10d") or 0
    if price * vol10d < 50_000:            # ~50k della valuta base/giorno — tara sul tuo mercato
        return False
    # Trend di fondo: sopra EMA200 se disponibile, altrimenti sopra EMA50
    ema50, ema200 = r.get("ema50") or 0, r.get("ema200") or 0
    if ema200:
        if price < ema200:
            return False
    elif ema50:
        if price < ema50:
            return False
    else:
        return False
    # Escludi solo i downtrend recenti conclamati
    if (r.get("perf_3m") or 0) < -5:
        return False
    return True

def etp_score(r):
    """Punteggio TECNICO (breve termine): trend + momentum + salute RSI, con freno ai blow-off."""
    price  = r.get("price")     or 0
    ema50  = r.get("ema50")     or 0
    ema200 = r.get("ema200")    or 0
    rsi    = r.get("rsi")       or 50
    hist   = r.get("macd_hist") or 0
    p1m    = r.get("perf_1m")   or 0
    p3m    = r.get("perf_3m")   or 0

    s = 0.0
    # Struttura di trend
    if ema200 and price > ema200:            s += 2.0
    if ema50  and price > ema50:             s += 1.0
    if ema50 and ema200 and ema50 > ema200:  s += 1.0   # golden alignment
    # Momentum con rendimenti decrescenti (radice): non premia gli strappi estremi
    s += (p3m ** 0.5 if p3m > 0 else 0) * 0.6
    s += (p1m ** 0.5 if p1m > 0 else -abs(p1m) * 0.1)
    # Conferma MACD
    if hist > 0:
        s += 1.0
    # Salute RSI: premia 50-68, penalizza gli estremi
    if   50 <= rsi <= 68: s += 1.0
    elif 45 <= rsi < 50:  s += 0.3
    elif rsi > 78:        s -= 1.0
    elif rsi < 40:        s -= 0.5
    return s

def etp_cost_score(r):
    """Punteggio COSTO/DIMENSIONE (strutturale): premia TER basso e masse ampie.

    NEUTRO sui dati mancanti: la diagnostica ha mostrato che TradingView
    valorizza expense_ratio ma spesso lascia aum a None, e Yahoo quoteSummary
    ora risponde 401. Penalizzare un dato assente equivarrebbe a punire un ETF
    solo perche' l'API non lo espone, quindi in quel caso non si assegna nulla.

    NOTA sul formato: TradingView puo' esporre expense_ratio come percentuale
    (0.20 = 0,20%) o come frazione (0.002). L'euristica sotto e' difensiva:
    verifica il valore reale nei log e, se il formato e' stabile, semplificala."""
    ter = r.get("expense_ratio")
    aum = r.get("aum")
    s = 0.0
    if ter is not None:
        ter_pct = ter * 100 if ter < 0.05 else ter    # euristica: <0.05 ⇒ frazione
        if   ter_pct <= 0.15: s += 2.0
        elif ter_pct <= 0.30: s += 1.5
        elif ter_pct <= 0.50: s += 1.0
        elif ter_pct <= 0.75: s += 0.3
        else:                 s -= 1.0    # >0,75%: tipico dei prodotti a leva
    if aum:                               # None o 0 ⇒ nessun punteggio, non penalita'
        if   aum >= 500_000_000: s += 2.0
        elif aum >= 100_000_000: s += 1.5
        elif aum >=  20_000_000: s += 1.0
        elif aum >=   5_000_000: s += 0.3
        else:                    s -= 0.5  # davvero piccolo ⇒ spread ampio, rischio chiusura
    return s

def etp_total_score(r):
    """Convenienza complessiva = tecnica (breve) + costo/dimensione (strutturale)."""
    return etp_score(r) + etp_cost_score(r)

# ── Universo ETP: lista esplicita di ticker quotati su Borsa Italiana ──
# La diagnostica ha dimostrato che il mercato "italy" dello screener TradingView
# contiene SOLO azioni (1818 strumenti, tutti type=stock) piu' 7 fondi chiusi:
# gli ETF di Borsa Italiana NON sono raggiungibili per mercato.
# Sono invece indicizzati sotto il prefisso EURONEXT: (Borsa Italiana e' del
# gruppo Euronext dal 2021) e si interrogano per lista esplicita di tickers.
#
# I ticker VERIFICATI dalla diagnostica sono marcati OK. Gli altri sono
# plausibili ma da confermare: quelli che non risolvono vengono semplicemente
# saltati e segnalati nei log, senza rompere il report.
ETP_TICKERS_DEFAULT = [
    # --- Azionario globale / sviluppato ---
    "SWDA",    # iShares Core MSCI World            (OK verificato)
    "VWCE",    # Vanguard FTSE All-World Acc        (OK verificato)
    "EIMI",    # iShares Core MSCI EM IMI           (OK verificato)
    "VUAA",    # Vanguard S&P 500 Acc               (OK verificato)
    "CSSPX",   # iShares Core S&P 500 (ticker Milano di CSPX)
    "XDWD",    # Xtrackers MSCI World
    "IUSQ",    # iShares MSCI ACWI
    "WSML",    # iShares MSCI World Small Cap
    # --- Azionario Europa ---
    "MEUD",    # Amundi Stoxx Europe 600            (OK verificato)
    "VERX",    # Vanguard FTSE Developed Europe ex-UK
    # --- Obbligazionario / monetario ---
    "XEON",    # Xtrackers EUR Overnight Rate       (OK verificato)
    "AGGH",    # iShares Core Global Aggregate Bond (OK verificato)
    "IBGL",    # iShares Euro Govt Bond 15-30y
    "VECP",    # Vanguard EUR Corporate Bond
    # --- Materie prime / ETC ---
    "SGLD",    # Invesco Physical Gold              (OK verificato)
    "PHAU",    # WisdomTree Physical Gold           (OK verificato)
    "SSLV",    # WisdomTree Physical Silver
    # --- Settoriali / tematici ---
    "QDVE",    # iShares S&P 500 Information Technology
    "WCLD",    # WisdomTree Cloud Computing
    "INRG",    # iShares Global Clean Energy
]

def _etp_universe():
    """Lista ticker ETP. Sovrascrivibile col secret/variabile ETP_TICKERS
    (JSON array di stringhe), cosi' puoi curare la tua watchlist senza
    toccare il codice."""
    raw = os.environ.get("ETP_TICKERS", "").strip()
    if raw:
        try:
            lista = json.loads(raw)
            if isinstance(lista, list) and lista:
                logger.info(f"Universo ETP da variabile ETP_TICKERS: {len(lista)} ticker")
                return [str(t).strip().upper() for t in lista]
        except Exception as e:
            logger.warning(f"ETP_TICKERS non valido ({e}), uso la lista di default")
    return ETP_TICKERS_DEFAULT

# Prefissi da provare, in ordine. EURONEXT copre Borsa Italiana; gli altri
# servono da ripiego per ETF non quotati a Milano (stesso ISIN, altra sede).
_ETP_PREFISSI = ["EURONEXT", "XETR", "LSE"]

def screen_etfs():
    """Seleziona ETF/ETN/ETC quotati su Borsa Italiana.

    Interroga TradingView per LISTA ESPLICITA di ticker con prefisso EURONEXT:,
    perche' lo screener per mercato non espone gli ETP italiani (vedi diagnostica).
    Per i ticker che non risolvono su EURONEXT si tenta XETR e LSE.
    """
    tickers = _etp_universe()
    logger.info(f"Screening ETP — {len(tickers)} ticker richiesti...")

    cols = TV_COLS + ETF_EXTRA_COLS
    trovati, mancanti = {}, list(tickers)

    for pre in _ETP_PREFISSI:
        if not mancanti:
            break
        simboli = [f"{pre}:{t}" for t in mancanti]
        try:
            data = tv_request("https://scanner.tradingview.com/global/scan",
                              {"symbols": {"tickers": simboli}, "columns": cols})
        except Exception as e:
            logger.warning(f"ETP fetch prefisso {pre}: {e}")
            continue
        righe = data.get("data") or []
        risolti = []
        for row in righe:
            r = parse_tv_row(row, cols)
            tk = row.get("s", "").split(":")[-1]
            if tk in mancanti:
                r["tv_symbol"] = row.get("s", "")
                trovati[tk] = r
                risolti.append(tk)
        mancanti = [t for t in mancanti if t not in risolti]
        logger.info(f"ETP prefisso {pre}: {len(risolti)} risolti, {len(mancanti)} da cercare")

    if mancanti:
        logger.warning(f"ETP non risolti con nessun prefisso: {', '.join(mancanti)}")
    if not trovati:
        logger.error("ETP: nessun ticker risolto. Verifica la lista o esegui la diagnostica.")
        return []

    rows = list(trovati.values())

    # Imbuto diagnostico: mostra DOVE si perdono i candidati
    after_etp = [r for r in rows if _is_etp(r)]
    eligible  = [r for r in after_etp if r.get("price") and _passes_etp(r, min_price=1.0)]
    logger.info(f"ETP funnel: risolti={len(rows)} → is_etp={len(after_etp)} → eleggibili={len(eligible)}")

    if rows and not after_etp:
        tipi = {(r.get("sec_type"), str(r.get("typespecs"))) for r in rows}
        logger.error(f"ETP: _is_etp() ha scartato TUTTO. Tassonomia vista: {tipi}")
        after_etp = rows
        eligible  = [r for r in after_etp if r.get("price") and _passes_etp(r, min_price=1.0)]

    if after_etp and not eligible:
        logger.warning("ETP: nessuno supera _passes_etp (liquidita'/trend). "
                       "Mostro comunque i migliori per punteggio, senza cancello.")
        eligible = after_etp

    eligible.sort(key=etp_total_score, reverse=True)
    logger.info(f"ETP: {len(eligible)} eleggibili → top {min(10, len(eligible))}")
    return eligible[:10]

# ─── ULTIMI 5 GIORNI: OHLC + PERFORMANCE ──────────────────────────────────────
# Lo screener TradingView restituisce solo valori SCALARI (un numero per colonna),
# non serie storiche: non puo' quindi fornire 5 candele giornaliere. Per il grafico
# a candele servono dati storici, presi dall'endpoint chart di Yahoo Finance.

_TV_TO_YF = {
    "MIL": ".MI", "BVME": ".MI", "XMIL": ".MI", "BIT": ".MI", "EURONEXT": ".MI",
    "XETR": ".DE", "XETRA": ".DE", "FWB": ".F", "GETTEX": ".DE",
    "XPAR": ".PA", "EPA": ".PA", "XAMS": ".AS", "AMS": ".AS",
    "LSE": ".L", "XLON": ".L", "XSWX": ".SW", "SWX": ".SW",
    "XMAD": ".MC", "BME": ".MC", "XBRU": ".BR", "XLIS": ".LS",
}
_YF_US = {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "CBOE"}

def tv_to_yahoo_symbol(tv_symbol):
    """Converte 'MIL:SWDA' → 'SWDA.MI'. I ticker USA restano invariati."""
    if not tv_symbol:
        return ""
    if ":" not in tv_symbol:
        return tv_symbol
    exch, ticker = tv_symbol.split(":", 1)
    exch = exch.upper()
    if exch in _YF_US:
        return ticker
    return ticker + _TV_TO_YF.get(exch, "")

_YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

def fetch_5d_ohlc(tv_symbol):
    """Ultime 5 sedute OHLC da Yahoo Finance.
    Restituisce [] in caso di errore: la colonna mostrera' 'n.d.' senza rompere il report.
    Chiediamo 1 mese e teniamo le ultime 5 barre valide, cosi' festivi e giorni
    senza scambi non riducono il campione."""
    ysym = tv_to_yahoo_symbol(tv_symbol)
    if not ysym:
        return []
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}"
           f"?range=1mo&interval=1d")
    try:
        r = requests.get(url, headers=_YF_HEADERS, timeout=12)
        if r.status_code != 200:
            logger.warning(f"5gg OHLC {ysym}: HTTP {r.status_code}")
            return []
        res = (r.json().get("chart") or {}).get("result") or []
        if not res:
            return []
        quotes = (res[0].get("indicators") or {}).get("quote") or [{}]
        q = quotes[0]
        o = q.get("open")  or []
        h = q.get("high")  or []
        l = q.get("low")   or []
        c = q.get("close") or []
        bars = [
            {"o": o[i], "h": h[i], "l": l[i], "c": c[i]}
            for i in range(min(len(o), len(h), len(l), len(c)))
            if None not in (o[i], h[i], l[i], c[i])
        ]
        return bars[-5:]
    except Exception as e:
        logger.warning(f"5gg OHLC {ysym}: {e}")
        return []

def fetch_ohlc_range(tv_symbol, range_="2y", interval="1d"):
    """Storico OHLC reale da Yahoo Finance (stesso endpoint di fetch_5d_ohlc,
    solo con una finestra piu' ampia). Serve per calcolare indicatori di
    medio periodo su dati di mercato VERI fin dal primo run, invece di
    aspettare che il nostro log giornaliero (storico.py) si accumuli per
    mesi: quel log non puo' essere retrodatato, la storia dei prezzi si'.
    Restituisce [] in caso di errore, senza rompere il report."""
    ysym = tv_to_yahoo_symbol(tv_symbol)
    if not ysym:
        return []
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}"
           f"?range={range_}&interval={interval}")
    try:
        r = requests.get(url, headers=_YF_HEADERS, timeout=15)
        if r.status_code != 200:
            logger.warning(f"Storico OHLC {ysym}: HTTP {r.status_code}")
            return []
        res = (r.json().get("chart") or {}).get("result") or []
        if not res:
            return []
        timestamps = res[0].get("timestamp") or []
        quotes = (res[0].get("indicators") or {}).get("quote") or [{}]
        q = quotes[0]
        o, h, l, c, v = (q.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
        bars = []
        for i in range(min(len(timestamps), len(o), len(h), len(l), len(c))):
            if None in (o[i], h[i], l[i], c[i]):
                continue
            bars.append({
                "data": datetime.fromtimestamp(timestamps[i], tz=timezone.utc).date(),
                "o": o[i], "h": h[i], "l": l[i], "c": c[i],
                "v": v[i] if v and i < len(v) and v[i] is not None else None,
            })
        return bars
    except Exception as e:
        logger.warning(f"Storico OHLC {ysym}: {e}")
        return []

def enrich_5d(rows, etichetta=""):
    """Aggiunge bars_5d e perf_5d a ogni riga. Fallisce in silenzio sul singolo titolo."""
    for r in rows:
        sym = r.get("tv_symbol") or r.get("yf_symbol") or r.get("symbol")
        bars = fetch_5d_ohlc(sym)
        r["bars_5d"] = bars
        if len(bars) >= 2 and bars[0].get("c"):
            r["perf_5d"] = round((bars[-1]["c"] / bars[0]["c"] - 1) * 100, 1)
        else:
            r["perf_5d"] = None

def enrich_storico_esteso(rows, etichetta="", range_="5y"):
    """Aggiunge bars_storico (OHLC giornaliero reale, 5 anni) a ogni riga:
    serve sia alle EMA giornaliere di Sezione 1 sia ai segnali settimanali
    di Sezione 4, che richiedono almeno ~200 settimane (~4 anni) di storico
    per un'EMA200 settimanale valida — 2 anni non basterebbero.
    Fallisce in silenzio sul singolo titolo (vedi fetch_ohlc_range)."""
    for r in rows:
        sym = r.get("tv_symbol") or r.get("yf_symbol") or r.get("symbol")
        r["bars_storico"] = fetch_ohlc_range(sym, range_)
    ok = sum(1 for r in rows if r.get("bars_storico"))
    logger.info(f"Storico {range_}{' ' + etichetta if etichetta else ''}: {ok}/{len(rows)} recuperati")
    return rows
    ok = sum(1 for r in rows if r.get("bars_5d"))
    logger.info(f"5gg OHLC{' ' + etichetta if etichetta else ''}: {ok}/{len(rows)} recuperati")
    return rows

def candles_5d_svg(bars, width=84, height=34):
    """Mini grafico a candele giapponesi (SVG inline) delle ultime 5 sedute.
    Verde = chiusura >= apertura, rosso = chiusura < apertura.
    Ogni candela ha ombra (high-low) e corpo (open-close)."""
    if not bars:
        return '<span style="color:#999;font-size:11px">n.d.</span>'
    lo = min(b["l"] for b in bars)
    hi = max(b["h"] for b in bars)
    rng = hi - lo
    if rng <= 0:
        return '<span style="color:#999;font-size:11px">—</span>'

    pad    = 3
    usable = height - 2 * pad
    slot   = width / len(bars)
    body_w = max(3.0, slot * 0.55)

    def y(v):
        return pad + (hi - v) / rng * usable

    parts = []
    for i, b in enumerate(bars):
        cx  = slot * (i + 0.5)
        up  = b["c"] >= b["o"]
        col = "#16a34a" if up else "#dc2626"
        # ombra (high-low)
        parts.append(
            f'<line x1="{cx:.1f}" y1="{y(b["h"]):.1f}" x2="{cx:.1f}" y2="{y(b["l"]):.1f}" '
            f'stroke="{col}" stroke-width="1"/>'
        )
        # corpo (open-close)
        y_top  = y(max(b["o"], b["c"]))
        y_bot  = y(min(b["o"], b["c"]))
        h_body = max(1.0, y_bot - y_top)
        parts.append(
            f'<rect x="{cx - body_w/2:.1f}" y="{y_top:.1f}" '
            f'width="{body_w:.1f}" height="{h_body:.1f}" fill="{col}"/>'
        )

    tip = f"5 sedute — min {lo:.2f} / max {hi:.2f}"
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'style="display:block"><title>{tip}</title>{"".join(parts)}</svg>')

# ─── PORTAFOGLIO ──────────────────────────────────────────────────────────────

# Prefissi exchange da tentare per ticker senza prefisso (ETC/ETF europei)
_FALLBACK_EXCHANGES = ["MIL", "XMIL", "BVME", "LSE", "XETR", "XAMS", "EURONEXT"]

def _tv_fetch_symbols(syms):
    """Chiama la TV screener API e restituisce dict {simbolo: parsed}."""
    results = {}
    if not syms:
        return results
    try:
        data = tv_request("https://scanner.tradingview.com/global/scan",
                          {"symbols": {"tickers": syms}, "columns": TV_COLS})
        for row in (data.get("data") or []):
            s      = row.get("s", "")
            parsed = parse_tv_row(row)
            results[s] = parsed
            results[s.split(":")[-1]] = parsed
    except Exception as e:
        logger.warning(f"TV fetch batch: {e}")
    return results

def get_portfolio_data():
    """Recupera dati tecnici del portafoglio via TradingView screener.
    Accetta 'EXCHANGE:TICKER' oppure solo 'TICKER'.
    Per qualsiasi simbolo non trovato al primo tentativo, riprova con i principali exchange europei."""
    if not PORTFOLIO:
        return []

    # Fetch iniziale con i simboli così come sono nel secret
    tv_syms = [p["symbol"] for p in PORTFOLIO]
    results = _tv_fetch_symbols(tv_syms)

    # Identifica TUTTI i ticker (con o senza prefisso) che non hanno avuto risposta
    def _is_missing(sym):
        ticker = sym.split(":")[-1] if ":" in sym else sym
        return sym not in results and ticker not in results

    missing = [p["symbol"] for p in PORTFOLIO if _is_missing(p["symbol"])]

    if missing:
        logger.info(f"Portfolio retry exchange fallback per: {missing}")
        # Estrai il ticker nudo e riprova con tutti gli exchange candidati
        retry_syms = [
            f"{ex}:{sym.split(':')[-1]}"
            for sym in missing
            for ex in _FALLBACK_EXCHANGES
        ]
        retry_results = _tv_fetch_symbols(retry_syms)
        results.update(retry_results)

    out = []
    for item in PORTFOLIO:
        sym    = item["symbol"]
        ticker = sym.split(":")[-1] if ":" in sym else sym
        parsed = results.get(sym) or results.get(ticker)
        if parsed:
            parsed["name"]      = item.get("name", parsed.get("symbol", sym))
            parsed["type"]      = item.get("type", "Azione")
            parsed["yf_symbol"] = sym
            logger.info(f"Portfolio: {sym} → prezzo {parsed.get('price')}")
        else:
            logger.warning(f"Portfolio: dati non trovati per '{sym}' (ticker={ticker})")
            parsed = {
                "symbol": ticker, "yf_symbol": sym,
                "name": item.get("name", sym), "type": item.get("type", "Azione"),
                "price": None, "rsi": None, "trend": "n.d.",
                "macd_str": "n.d.", "macd_hist": 0,
                "perf_1m": None, "perf_3m": None,
                "rec_str": "n.d.", "rec": 0,
                "candle_d": "—", "candle_w": "—",
            }
        # Campi ricostruiti dal dossier XLS (portfolio_sync): assenti se il
        # portafoglio arriva ancora dal vecchio secret PORTFOLIO_JSON.
        parsed["isin"]              = item.get("isin")
        parsed["quantita"]          = item.get("quantita")
        parsed["prezzo_medio"]      = item.get("prezzo_medio")
        parsed["divisa"]            = item.get("divisa")
        parsed["data_apertura"]     = item.get("data_apertura")
        parsed["giorni_detenzione"] = item.get("giorni_detenzione")
        out.append(parsed)
    return out

def get_watchlist_data(watchlist):
    """Dati tecnici correnti per la watchlist (Sezione 4), stesso meccanismo
    di get_portfolio_data. Se un simbolo non risolve su TV, resta comunque
    nella lista con dati 'n.d.': i segnali di medio periodo funzionano lo
    stesso, perche' vengono calcolati sullo storico Yahoo, non su questi campi."""
    if not watchlist:
        return []
    syms = [w["symbol"] for w in watchlist]
    results = _tv_fetch_symbols(syms)
    out = []
    for w in watchlist:
        sym = w["symbol"]
        ticker = sym.split(":")[-1] if ":" in sym else sym
        parsed = results.get(sym) or results.get(ticker) or {"symbol": ticker, "price": None, "rsi": None}
        parsed["name"] = w.get("name", parsed.get("name", sym))
        parsed["yf_symbol"] = sym
        out.append(parsed)
    return out

# ─── INDICI DI MERCATO ────────────────────────────────────────────────────────
# Simboli TradingView per gli indici principali
INDICES_TV = {
    "S&P 500":      "SP:SPX",
    "NASDAQ":       "NASDAQ:COMP",
    "Eurostoxx 50": "TVC:SX5E",
    "FTSE MIB":     "INDEX:FTSEMIB",
}

def get_indices():
    """Recupera variazione % degli indici via TradingView screener (nessuna dipendenza da Yahoo)."""
    out = {name: None for name in INDICES_TV}
    try:
        syms = list(INDICES_TV.values())
        data = tv_request("https://scanner.tradingview.com/global/scan",
                          {"symbols": {"tickers": syms}, "columns": ["change"]})
        by_tv = {v: k for k, v in INDICES_TV.items()}
        for row in (data.get("data") or []):
            s   = row.get("s", "")
            chg = (row.get("d") or [None])[0]
            name = by_tv.get(s)
            if name and chg is not None:
                out[name] = round(chg, 2)
    except Exception as e:
        logger.warning(f"Indices TV fetch: {e}")
    return out

# ─── CALENDARIO (Sezione 2) ───────────────────────────────────────────────────
def build_calendario(portfolio, regole_map, eventi_macro, giorni=60):
    """Unisce le riunioni BCE/Fed e gli eventi per-titolo scritti a mano nelle
    regole delle posizioni aperte, filtrati sui prossimi N giorni e ordinati
    cronologicamente. Non include eventi per titoli fuori portafoglio: la
    watchlist configurabile arriva in Fase 5."""
    oggi = date.today()
    limite = oggi + timedelta(days=giorni)
    voci = [e for e in eventi_macro if oggi <= e["data"] <= limite]
    for p in portfolio:
        isin = p.get("isin")
        nome = p.get("name", isin)
        regola = regole_map.get(isin) or {}
        for ev in regola.get("eventi", []):
            if oggi <= ev["data"] <= limite:
                voci.append({"data": ev["data"], "titolo": nome, "tipo": ev.get("tipo", "evento")})
    voci.sort(key=lambda v: v["data"])
    return voci

# ─── ANALISI CLAUDE ──────────────────────────────────────────────────────────

def _confronto_ieri(p):
    """Descrive cosa dicono i dati di IERI per questa posizione, calcolato in
    Python (non lasciato indovinare al modello): il prompt deve narrare un
    fatto già accertato, non stimare una variazione a occhio."""
    isin = p.get("isin")
    prev = storico.valore_precedente(isin=isin, categoria="posizione") if isin else None
    if not prev:
        return "nessun dato di ieri (prima rilevazione per questa posizione)"
    parti = []
    if prev.get("close") and p.get("price"):
        var = (p["price"] / prev["close"] - 1) * 100
        parti.append(f"prezzo da {prev['close']:.2f} a {p['price']:.2f} ({var:+.1f}%)")
    if prev.get("rsi") is not None and p.get("rsi") is not None:
        parti.append(f"RSI da {prev['rsi']:.0f} a {p['rsi']:.0f}")
    if prev.get("macd_hist") is not None:
        segno_prev = "positivo" if prev["macd_hist"] > 0 else "negativo"
        segno_oggi = "positivo" if (p.get("macd_hist") or 0) > 0 else "negativo"
        if segno_prev != segno_oggi:
            parti.append(f"MACD passato da {segno_prev} a {segno_oggi}")
    return "; ".join(parti) if parti else "nessuna variazione significativa rispetto a ieri"

def _regole_txt(p, regole_map):
    """Le regole scritte dall'utente per questa posizione, in una riga —
    cosi' il modello ha i fatti per trovare contraddizioni, senza doverli
    dedurre da una tabella separata."""
    regola = regole_map.get(p.get("isin")) or {}
    if not any(regola.get(k) for k in ("stop", "target", "revisione", "tesi")):
        return "nessuna regola scritta"
    parti = []
    if regola.get("stop"):
        parti.append(f"stop {regola['stop']}")
    if regola.get("target"):
        parti.append(f"target {regola['target']}")
    if regola.get("revisione"):
        parti.append(f"revisione {regola['revisione'].strftime('%d/%m/%Y')}")
    if regola.get("tesi"):
        parti.append(f"tesi scritta: \"{regola['tesi']}\"")
    return ", ".join(parti)

def generate_analysis(stocks_it, stocks_us, etfs, portfolio, indices, regole_map=None):
    regole_map = regole_map or {}
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def fmt(lst):
        if not lst:
            return "Nessun titolo ha superato il filtro oggi."
        return "\n".join(
            f"- {d['symbol']} ({d.get('name','')}): prezzo {d['price']}, RSI {d['rsi']}, "
            f"1M {d.get('perf_1m','n.d.')}%, 3M {d.get('perf_3m','n.d.')}%, "
            f"MACD {d.get('macd_str','n.d.')}, TV Rec: {d.get('rec_str','n.d.')}"
            for d in lst
        )

    port_txt = "\n".join(
        f"- {p['name']} ({p.get('yf_symbol', p['symbol'])}): prezzo {p.get('price','n.d.')}, "
        f"RSI {p.get('rsi','n.d.')}, trend {p.get('trend','n.d.')}, MACD {p.get('macd_str','n.d.')}, "
        f"detenuta da {p.get('giorni_detenzione','n.d.')} giorni.\n"
        f"  Rispetto a ieri: {_confronto_ieri(p)}.\n"
        f"  Regole scritte dall'utente: {_regole_txt(p, regole_map)}."
        for p in portfolio
    ) or "Portafoglio vuoto."

    idx_txt = "\n".join(
        f"- {k}: {v:+.2f}%" if v is not None else f"- {k}: n.d."
        for k, v in indices.items()
    )

    prompt = f"""Descrivi fatti, non consigliare operazioni. Data: {datetime.now().strftime('%d/%m/%Y')}.

REGOLA FONDAMENTALE: non suggerire mai di comprare, vendere, accumulare, ridurre
posizioni o riallocare capitale. Non usare parole come "consiglio", "opportunità",
"conviene", "meglio". Il tuo unico compito è descrivere COSA È CAMBIATO rispetto a
ieri e segnalare eventuali CONTRADDIZIONI tra la tesi scritta dall'utente e i fatti
attuali. La decisione resta sempre dell'utente: tu esponi i fatti, non giudichi.

I dati tecnici provengono da TradingView e da uno storico giornaliero proprio.
MACD indica la direzione del momentum. TV Rec è la raccomandazione aggregata di
26 indicatori TradingView: la riporti come dato di fatto, non la usi per consigliare.

INDICI:
{idx_txt}

TITOLI IN "DA APPROFONDIRE" (screener — spunti di ricerca, non idee d'acquisto):
Italia:
{fmt(stocks_it)}
USA:
{fmt(stocks_us)}
ETF:
{fmt(etfs)}

LE MIE POSIZIONI (conto B), con il confronto con ieri e le regole scritte dall'utente:
{port_txt}

Genera un JSON con questa struttura ESATTA (solo JSON puro, zero markdown):
{{
  "contesto_mercato": "2-3 frasi che descrivono cosa e' cambiato oggi sui mercati rispetto a ieri, nessun consiglio",
  "stocks_it_analysis": [{{"symbol":"TICKER","motivazione":"una riga secca sul possibile catalizzatore del movimento — mai un consiglio operativo, mai dire se comprare o vendere"}}],
  "stocks_us_analysis": [{{"symbol":"TICKER","motivazione":"una riga secca sul possibile catalizzatore del movimento — mai un consiglio operativo, mai dire se comprare o vendere"}}],
  "etfs_analysis": [{{"symbol":"TICKER","tema":"AI / Semiconduttori / ecc.","motivazione":"2-3 righe descrittive — mai un consiglio operativo"}}],
  "cambiamenti_posizioni": [{{"symbol":"TICKER","descrizione":"cosa e' cambiato rispetto a ieri per questa posizione, solo fatti (prezzo, RSI, trend, MACD) — se non c'e' un cambiamento degno di nota NON includere questa posizione nell'elenco"}}],
  "contraddizioni_posizioni": [{{"symbol":"TICKER","contraddizione":"SOLO se la tesi scritta dall'utente e' in conflitto di significato con i fatti attuali (es. la tesi presuppone una condizione che i fatti di oggi negano) — non ripetere il confronto numerico stop/target/giorni di detenzione, il report li mostra già altrove — se non c'e' una tesi scritta o nessun conflitto reale, NON includere questa posizione nell'elenco"}}]
}}
Per stocks_it_analysis, stocks_us_analysis ed etfs_analysis questi titoli sono spunti
di ricerca, non idee d'acquisto: la motivazione deve spiegare PERCHÉ il titolo si
muove (il fatto), mai cosa farne.
cambiamenti_posizioni e contraddizioni_posizioni sono array che possono restare
vuoti: non forzare un'osservazione dove non ce n'è una vera.
Usa il campo symbol uguale al ticker TV, senza prefisso exchange quando possibile
(es. "OMER", "PANW", "MIL:SMH" se serve disambiguare).
Per qualsiasi ETF a leva menziona sempre il rischio decay da leva giornaliera."""

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(text)

# ─── HTML ─────────────────────────────────────────────────────────────────────

def pct(val):
    if val is None:
        return '<span style="color:#999">n.d.</span>'
    color = "#16a34a" if val >= 0 else "#dc2626"
    return f'<span style="color:{color};font-weight:600">{val:+.1f}%</span>'

def rating_badge(r):
    color = "#16a34a" if r == "Forte" else "#d97706"
    return f'<span style="color:{color};font-weight:700">● {r}</span>'

def etp_reco_badge(score):
    """Badge per la Rec. degli ETP, coerente con l'ordinamento (etp_total_score).
    Soglie da calibrare sui dati reali dell'imbuto."""
    if score >= 8.0:
        return '<span style="color:#15803d;font-weight:700;white-space:nowrap">🟢 Forte</span>'
    elif score >= 5.0:
        return '<span style="color:#d97706;font-weight:700;white-space:nowrap">🟡 Moderato</span>'
    elif score >= 2.5:
        return '<span style="color:#ea580c;font-weight:700;white-space:nowrap">🟠 Cauto</span>'
    else:
        return '<span style="color:#dc2626;font-weight:700;white-space:nowrap">🔴 Debole</span>'

def fmt_ter(ter):
    """Formatta il TER (Total Expense Ratio) con colore per fascia di costo."""
    if ter is None:
        return '<span style="color:#999">n.d.</span>'
    ter_pct = ter * 100 if ter < 0.05 else ter    # stessa euristica di etp_cost_score
    color = "#16a34a" if ter_pct <= 0.30 else ("#d97706" if ter_pct <= 0.75 else "#dc2626")
    return f'<span style="color:{color};font-size:12px">{ter_pct:.2f}%</span>'

def fmt_aum(aum):
    """Formatta le masse gestite (valuta base del fondo) con colore per fascia di dimensione."""
    if not aum:
        return '<span style="color:#999">n.d.</span>'
    if aum >= 1e9:
        txt = f"{aum/1e9:.1f}B"
    elif aum >= 1e6:
        txt = f"{aum/1e6:.0f}M"
    elif aum >= 1e3:
        txt = f"{aum/1e3:.0f}K"
    else:
        txt = f"{aum:.0f}"
    color = "#16a34a" if aum >= 100e6 else ("#d97706" if aum >= 20e6 else "#dc2626")
    return f'<span style="color:{color};font-size:12px">{txt}</span>'

def auto_comment(d):
    """Commento sintetico automatico per ogni titolo, basato sui segnali calcolati."""
    rsi    = d.get("rsi")      or 0
    p1m    = d.get("perf_1m")  or 0
    p3m    = d.get("perf_3m")  or 0
    hist   = d.get("macd_hist") or 0
    ema20  = d.get("ema20")    or 0
    ema50  = d.get("ema50")    or 0
    ema200 = d.get("ema200")   or 0
    price  = d.get("price")    or 0

    parts = []

    # RSI
    if rsi > 72:
        parts.append(f"RSI {rsi:.0f} — zona ipercomprata, attenzione ai prezzi estesi")
    elif rsi < 42:
        parts.append(f"RSI {rsi:.0f} — ipervenduto, possibile rimbalzo")
    else:
        parts.append(f"RSI {rsi:.0f}")

    # Performance
    if p1m > 8:
        parts.append(f"forte slancio mensile +{p1m:.1f}%")
    elif p1m > 3:
        parts.append(f"1M +{p1m:.1f}%")
    elif p1m < -4:
        parts.append(f"1M {p1m:.1f}% — pressione ribassista")
    elif p1m < 0:
        parts.append(f"1M {p1m:.1f}%")

    # Struttura EMA
    if price and ema20 and ema50 and ema200:
        if price > ema20 > ema50 > ema200:
            parts.append("trend allineato su tutti i timeframe")
        elif price > ema20 > ema50 and (not ema200 or price < ema200):
            parts.append("sopra EMA20/50, sotto EMA200")
    elif price and ema20 and price < ema20:
        parts.append("sotto EMA20 — struttura debole")

    # MACD
    if hist > 0:
        parts.append("MACD positivo")
    else:
        parts.append("MACD negativo")

    # Pattern
    pat = detect_pattern(d)
    if pat != "—":
        parts.append(pat)

    return ". ".join(parts[:4]) + "."

def _composite_badge(label, color):
    return f'<span style="color:{color};font-weight:700;font-size:12px">{label}</span>'

def compute_signal(r):
    """Segnale composito da RSI/EMA/MACD/momentum. Restituisce (label, colore)."""
    price  = r.get("price")    or 0
    rsi    = r.get("rsi")      or 50
    hist   = r.get("macd_hist") or 0
    ema20  = r.get("ema20")    or 0
    ema50  = r.get("ema50")    or 0
    ema200 = r.get("ema200")   or 0
    p1m    = r.get("perf_1m")  or 0
    p3m    = r.get("perf_3m")  or 0
    vol    = r.get("volume")   or 0
    vol10d = r.get("vol_10d")  or 1

    if rsi > 75:
        return ("⚠️ Ipercomprato", "#b45309")
    if rsi < 42 and hist > 0 and price and ema20 and price > ema20:
        return ("🔄 Rimbalzo", "#2563eb")
    if price and ema20 and ema50 and ema200 and price > ema20 > ema50 > ema200 and hist > 0 and p1m > 4:
        return ("🚀 Breakout", "#15803d")
    if price and ema200 and price > ema200 and p1m > 5 and p3m > 12:
        return ("💪 Trend Forte", "#16a34a")
    if hist > 0 and p1m < -2:
        return ("📉 Momentum ↓", "#dc2626")
    if vol10d > 0 and vol > vol10d * 2.5 and hist > 0:
        return ("📣 Volume Spike", "#7c3aed")
    if abs(p1m) < 2 and abs(p3m) < 6:
        return ("➡️ Laterale", "#6b7280")
    if hist > 0:
        return ("📈 Rialzista", "#059669")
    return ("📊 Neutro", "#6b7280")

def detect_pattern(r):
    """Rileva pattern tecnici da massimi/minimi di periodo."""
    price  = r.get("price")    or 0
    h3m    = r.get("high_3m")  or 0
    l3m    = r.get("low_3m")   or 0
    h52    = r.get("high_52w") or 0
    l52    = r.get("low_52w")  or 0
    p1m    = r.get("perf_1m")  or 0
    p3m    = r.get("perf_3m")  or 0
    rsi    = r.get("rsi")      or 50
    hist   = r.get("macd_hist") or 0
    ema20  = r.get("ema20")    or 0

    if not price:
        return "—"

    near_h3m = h3m and abs(price - h3m) / h3m < 0.03
    near_l3m = l3m and abs(price - l3m) / l3m < 0.04
    near_h52 = h52 and price > h52 * 0.97
    near_l52 = l52 and price < l52 * 1.05

    if near_h3m and p1m < -1 and rsi > 58:
        return "⛰️ Doppio Picco?"
    if near_l3m and p1m > 1 and hist > 0:
        return "🔁 Doppio Minimo?"
    if near_h52 and p1m > 3 and hist > 0:
        return "🔝 Breakout 52W"
    if near_l52 and hist > 0:
        return "🛡️ Test Supporto"
    if p3m > 18 and abs(p1m) < 4 and h3m and price > h3m * 0.88:
        return "🚩 Flag Rialzista"
    if ema20 and price and abs(price - ema20) / ema20 < 0.02 and hist > 0 and p3m > 8:
        return "↩️ Pullback EMA20"
    if near_h3m and rsi > 72:
        return "🔴 Resistenza"
    return "—"

def idx_badge(val):
    if val is None:
        return '<span style="color:#999">n.d.</span>'
    color = "#16a34a" if val >= 0 else "#dc2626"
    sign = "+" if val >= 0 else ""
    return f'<span style="color:{color};font-weight:700">{sign}{val:.2f}%</span>'

def candle_badge(pattern):
    """Badge colorato per pattern candela giapponese."""
    if not pattern or pattern in ("—", "n.d."):
        return '<span style="color:#999">—</span>'
    if any(x in pattern for x in ["Bullish", "Hammer ▲", "Inv. Hammer ▲", "Engulfing ▲"]):
        return f'<span style="color:#16a34a;font-size:12px">{pattern}</span>'
    if any(x in pattern for x in ["Bearish", "Shooting Star ▼", "Hanging Man ▼", "Engulfing ▼"]):
        return f'<span style="color:#dc2626;font-size:12px">{pattern}</span>'
    return f'<span style="color:#888;font-size:12px">{pattern}</span>'

def macd_badge(macd_str):
    """Badge MACD: verde se rialzista, rosso se ribassista."""
    if not macd_str or macd_str == "n.d.":
        return '<span style="color:#999">n.d.</span>'
    color = "#16a34a" if macd_str.startswith("↑") else "#dc2626"
    return f'<span style="color:{color};font-size:12px;font-weight:600;white-space:nowrap">{macd_str}</span>'

def rec_badge(rec_str):
    """Badge TV Rec.All (aggregato 26 indicatori)."""
    colors = {
        "Compra Forte": "#15803d", "Compra": "#16a34a",
        "Neutro": "#888", "Vendi": "#dc2626", "Vendi Forte": "#991b1b",
    }
    c = colors.get(rec_str, "#888")
    return f'<span style="color:{c};font-size:12px;font-weight:700">● {rec_str}</span>'

def trend_rimbalzo_badge(label):
    """Badge di classificazione (non un giudizio d'acquisto): distingue un trend
    confermato su 1M e 3M da un semplice rimbalzo tecnico dopo un calo a 3M."""
    if label == "TREND":
        return '<span style="color:#1d4ed8;font-weight:700;white-space:nowrap">📈 TREND</span>'
    if label == "RIMBALZO":
        return '<span style="color:#9333ea;font-weight:700;white-space:nowrap">🔄 RIMBALZO</span>'
    return '<span style="color:#999">n.d.</span>'

def stock_rows(lst, analysis_map, market_delta=0):
    if not lst:
        return '<tr><td colspan="15" style="text-align:center;color:#999;padding:20px">Nessun titolo ha superato il filtro oggi (RSI 48-75, prezzo &gt; EMA20/50, MACD &gt; 0)</td></tr>'
    rows = ""
    for i, d in enumerate(lst, 1):
        a = analysis_map.get(d["symbol"], {})
        price_str = f"{d['price']:.2f}" if d.get("price") else "n.d."
        rows += f"""<tr>
            <td style="color:#999;font-size:12px">{i}</td>
            <td><strong>{d['symbol']}</strong><br><span style="color:#888;font-size:11px">{d.get('name','')}</span></td>
            <td>{price_str}</td>
            <td>{d['rsi'] if d.get('rsi') else 'n.d.'}</td>
            <td>{pct(d.get('perf_1m'))}</td>
            <td>{pct(d.get('perf_3m'))}</td>
            <td>{pct(d.get('perf_5d'))}</td>
            <td>{candles_5d_svg(d.get('bars_5d'))}</td>
            <td>{candle_badge(d.get('candle_d','—'))}</td>
            <td>{candle_badge(d.get('candle_w','—'))}</td>
            <td>{macd_badge(d.get('macd_str','n.d.'))}</td>
            <td>{_composite_badge(*compute_signal(d))}</td>
            <td style="font-size:12px">{detect_pattern(d)}</td>
            <td>{trend_rimbalzo_badge(classify_trend_rimbalzo(d))}</td>
            <td class="wrap"><div style="color:#444">{a.get('motivazione') or auto_comment(d)}</div></td>
        </tr>"""
    return rows

def etf_rows(lst, analysis_map, market_delta=0):
    if not lst:
        return '<tr><td colspan="18" style="text-align:center;color:#999;padding:20px">Nessun ETF/ETN/ETC ha superato il filtro oggi</td></tr>'
    rows = ""
    for i, d in enumerate(lst, 1):
        a = analysis_map.get(d["symbol"], {})
        price_str = f"{d['price']:.2f}" if d.get("price") else "n.d."
        rows += f"""<tr>
            <td style="color:#999;font-size:12px">{i}</td>
            <td><strong>{d['symbol']}</strong></td>
            <td style="color:#6366f1;font-size:13px">{a.get('tema','—')}</td>
            <td>{price_str}</td>
            <td>{d['rsi'] if d.get('rsi') else 'n.d.'}</td>
            <td>{pct(d.get('perf_1m'))}</td>
            <td>{pct(d.get('perf_3m'))}</td>
            <td>{pct(d.get('perf_5d'))}</td>
            <td>{candles_5d_svg(d.get('bars_5d'))}</td>
            <td>{candle_badge(d.get('candle_d','—'))}</td>
            <td>{candle_badge(d.get('candle_w','—'))}</td>
            <td>{macd_badge(d.get('macd_str','n.d.'))}</td>
            <td>{_composite_badge(*compute_signal(d))}</td>
            <td style="font-size:12px">{detect_pattern(d)}</td>
            <td>{etp_reco_badge(etp_total_score(d))}</td>
            <td>{fmt_ter(d.get('expense_ratio'))}</td>
            <td>{fmt_aum(d.get('aum'))}</td>
            <td class="wrap"><div style="color:#444">{a.get('motivazione') or auto_comment(d)}</div></td>
        </tr>"""
    return rows

def var_da_carico_html(price, prezzo_medio):
    if not price or not prezzo_medio:
        return '<span style="color:#999">n.d.</span>'
    var = (price / prezzo_medio - 1) * 100
    color = "#16a34a" if var >= 0 else "#dc2626"
    return f'<span style="color:{color};font-weight:700">{var:+.1f}%</span>'

def giorni_detenzione_html(giorni):
    if giorni is None:
        return '<span style="color:#999">n.d.</span>'
    if giorni < 60:
        color = "#16a34a"
    elif giorni <= 80:
        color = "#d97706"
    else:
        color = "#dc2626"
    return f'<span style="color:{color};font-weight:700">{giorni} gg</span>'

def distanza_da_livello_html(price, livello, verso_alto):
    """verso_alto=True per il target (quanto manca, in %, perche' il prezzo
    deve ancora salire per raggiungerlo). verso_alto=False per lo stop
    (quanto e' sopra, in %: negativo significa che l'ha gia' rotto)."""
    if not price or not livello:
        return '<span style="color:#999">n.d.</span>'
    dist = (livello / price - 1) * 100 if verso_alto else (price / livello - 1) * 100
    color = "#dc2626" if dist < 0 else "#444"
    return f'<span style="color:{color};font-weight:600">{dist:+.1f}%</span>'

def trend_ema_html(sopra, giorni, certo, label):
    freccia, stato = ("▲", "Sopra") if sopra else ("▼", "Sotto")
    color = "#16a34a" if sopra else "#dc2626"
    if giorni is None:
        durata = ""
    else:
        durata = f" ({giorni}gg)" if certo else f" (almeno {giorni}gg)"
    return f'<span style="color:{color};font-weight:600;white-space:nowrap">{freccia} {stato} {label}{durata}</span>'

def eventi_prossimi_html(eventi, giorni_max=30):
    oggi = date.today()
    prossimi = sorted(
        (e for e in (eventi or []) if 0 <= (e["data"] - oggi).days <= giorni_max),
        key=lambda e: e["data"]
    )
    if not prossimi:
        return '<span style="color:#999;font-size:12px">nessuno nei prossimi 30gg</span>'
    return "<br>".join(
        f'<span style="font-size:12px">{e["tipo"]} — {e["data"].strftime("%d/%m")}</span>'
        for e in prossimi
    )

def note_fattuali_html(p, regola, cambiamento=None, contraddizione=None):
    """Domande/osservazioni fattuali, non giudizi: confronta lo stato attuale
    con i tuoi dati (storico personale) e con quello che hai scritto tu
    (stop/target/revisione). Nessun badge Mantieni/Riduci/Evitare.
    cambiamento e contraddizione sono testo generato dal modello (Fase 6):
    solo descrizione di cosa e' cambiato da ieri e di eventuali conflitti tra
    la tesi scritta e i fatti — mai un consiglio — e vengono mostrati in un
    colore diverso per restare distinguibili dai fatti calcolati qui sotto."""
    note = []
    price = p.get("price")
    giorni = p.get("giorni_detenzione")
    stop = (regola or {}).get("stop")
    target = (regola or {}).get("target")
    revisione = (regola or {}).get("revisione")

    if giorni is not None and giorni > 80:
        note.append(f"Aperta da {giorni} giorni — sopra la permanenza media dei tuoi trade perdenti (80gg).")
    elif giorni is not None and giorni >= 60:
        note.append(f"Aperta da {giorni} giorni — nella fascia (61-180gg) dove il tuo win rate storico scende al 32%.")

    if price and stop and price <= stop:
        note.append(f"Sotto lo stop dichiarato ({stop}).")
    if price and target and price >= target:
        note.append(f"Sopra il target dichiarato ({target}).")
    if revisione and date.today() > revisione:
        note.append(f"Data di revisione ({revisione.strftime('%d/%m/%Y')}) superata.")

    righe = [f'<span style="font-size:12px;color:#92400e">▸ {n}</span>' for n in note]
    if cambiamento:
        righe.append(f'<span style="font-size:12px;color:#1d4ed8">↻ {cambiamento}</span>')
    if contraddizione:
        righe.append(f'<span style="font-size:12px;color:#7c3aed">⚠ Tesi vs fatti: {contraddizione}</span>')

    if not righe:
        return '<span style="color:#999;font-size:12px">—</span>'
    return "<br>".join(righe)

def posizioni_rows(portfolio, regole_map, cambiamenti_map=None, contraddizioni_map=None, editor_idx_by_isin=None):
    cambiamenti_map = cambiamenti_map or {}
    contraddizioni_map = contraddizioni_map or {}
    editor_idx_by_isin = editor_idx_by_isin or {}
    if not portfolio:
        return ('<tr><td colspan="10" style="text-align:center;color:#999;padding:20px">'
                'Nessuna posizione aperta sul conto B (dossier non ancora caricato, vedi README).</td></tr>')
    rows = ""
    for p in portfolio:
        isin = p.get("isin")
        regola = regole_map.get(isin) or {}
        idx = editor_idx_by_isin.get(isin)
        sym_key = p.get("yf_symbol", p.get("symbol", ""))
        bare_key = sym_key.split(":")[-1] if ":" in sym_key else sym_key
        cambiamento = (cambiamenti_map.get(sym_key) or cambiamenti_map.get(bare_key) or {}).get("descrizione")
        contraddizione = (contraddizioni_map.get(sym_key) or contraddizioni_map.get(bare_key) or {}).get("contraddizione")
        price = p.get("price")
        ema50, ema200 = p.get("ema50") or 0, p.get("ema200") or 0

        # 1) Storico reale (Yahoo): EMA vere, data di incrocio vera.
        bars = p.get("bars_storico") or []
        sopra50, g50, certo50 = indicatori_storici.trend_vs_ema(bars, 50)
        sopra200, g200, certo200 = indicatori_storici.trend_vs_ema(bars, 200)

        # 2) Storico Yahoo non disponibile per questo titolo: ripiego sul
        # nostro log giornaliero (storico.py) — "almeno N giorni" finche' non
        # ha visto un cambio di stato — e in assenza anche di quello, sullo
        # stato del solo giorno corrente (nessuna durata).
        if sopra50 is None:
            sopra50 = bool(price and ema50 and price > ema50)
            g50, certo50 = storico.giorni_in_stato(
                isin, lambda r: bool(r["close"] and r["ema50"] and r["close"] > r["ema50"]), sopra50
            ) if isin else (None, False)
        if sopra200 is None:
            sopra200 = bool(price and ema200 and price > ema200)
            g200, certo200 = storico.giorni_in_stato(
                isin, lambda r: bool(r["close"] and r["ema200"] and r["close"] > r["ema200"]), sopra200
            ) if isin else (None, False)
        price_str = f"{price:.2f}" if price else "n.d."
        divisa = p.get("divisa") or ""
        tesi = regola.get("tesi") or ""
        nome = p.get("name", p.get("symbol", ""))
        simbolo = p.get("yf_symbol", p.get("symbol", ""))
        revisione = regola.get("revisione")

        mini = "padding:6px;border:1px solid #ddd;border-radius:4px;font-size:12px;margin-top:4px"
        if idx is not None:
            ticker_input = (f'<br><input id="sym-{idx}" value="{html.escape(simbolo)}" '
                             f'placeholder="MIL:TICKER" style="width:100px;{mini}">')
            stop_input = (f'<br><input id="stop-{idx}" type="number" step="0.01" '
                          f'value="{regola.get("stop") if regola.get("stop") is not None else ""}" '
                          f'style="width:80px;{mini}">')
            target_input = (f'<br><input id="target-{idx}" type="number" step="0.01" '
                            f'value="{regola.get("target") if regola.get("target") is not None else ""}" '
                            f'style="width:80px;{mini}">')
            rev_input = (f'<br><input id="rev-{idx}" type="date" title="Prossima revisione" '
                        f'value="{revisione.isoformat() if revisione else ""}" style="{mini}">')
            tesi_field = (f'<input id="tesi-{idx}" value="{html.escape(tesi)}" '
                         f'placeholder="perché tieni questa posizione" style="width:100%;{mini}">')
        else:
            ticker_input = stop_input = target_input = rev_input = ""
            tesi_html = html.escape(tesi) if tesi else '<span style="color:#999">nessuna tesi scritta</span>'
            tesi_field = f'<div style="color:#444;font-size:12px">{tesi_html}</div>'

        rows += f"""<tr>
            <td><strong>{html.escape(nome)}</strong><br><span style="color:#999;font-size:11px">{html.escape(simbolo)}</span>{ticker_input}</td>
            <td>{price_str} {divisa}</td>
            <td>{var_da_carico_html(price, p.get('prezzo_medio'))}</td>
            <td>{giorni_detenzione_html(p.get('giorni_detenzione'))}</td>
            <td>{distanza_da_livello_html(price, regola.get('stop'), verso_alto=False)}{stop_input}</td>
            <td>{distanza_da_livello_html(price, regola.get('target'), verso_alto=True)}{target_input}</td>
            <td>{trend_ema_html(sopra50, g50, certo50, "EMA50")}<br>{trend_ema_html(sopra200, g200, certo200, "EMA200")}</td>
            <td>{eventi_prossimi_html(regola.get('eventi'))}{rev_input}</td>
            <td>{note_fattuali_html(p, regola, cambiamento, contraddizione)}</td>
            <td class="wrap">{tesi_field}</td>
        </tr>"""
    return rows

def calendario_rows(voci):
    if not voci:
        return '<tr><td colspan="3" style="text-align:center;color:#999;padding:20px">Nessun evento nei prossimi 60 giorni.</td></tr>'
    rows = ""
    for v in voci:
        rows += f"""<tr>
            <td style="white-space:nowrap">{v['data'].strftime('%d/%m/%Y')}</td>
            <td>{v['tipo']}</td>
            <td>{v['titolo']}</td>
        </tr>"""
    return rows

# ─── SEGNALI DI MEDIO PERIODO (Sezione 4) ────────────────────────────────────
_SEGNALI_BULLISH = {"Doppio minimo", "Divergenza rialzista (RSI settimanale)",
                    "Rottura massimo 52 settimane", "Golden cross"}
_SEGNALI_BEARISH = {"Doppio massimo", "Divergenza ribassista (RSI settimanale)",
                    "Rottura minimo 52 settimane", "Death cross"}

def _segnale_badge(tipo):
    if tipo in _SEGNALI_BULLISH:
        color = "#16a34a"
    elif tipo in _SEGNALI_BEARISH:
        color = "#dc2626"
    else:
        color = "#6b7280"
    return f'<span style="color:{color};font-weight:700;white-space:nowrap">{tipo}</span>'

def _formatta_dettaglio_segnale(s):
    tipo = s.get("tipo", "")
    if tipo in ("Doppio massimo", "Doppio minimo"):
        return (f"Picchi del {s['data_picco1'].strftime('%d/%m/%Y')} e {s['data_picco2'].strftime('%d/%m/%Y')}, "
                f"distanza {s['distanza_pct']}%. Livello di conferma: {s['livello_conferma']}.")
    if "Divergenza" in tipo:
        return (f"{s['prezzo'].capitalize()} tra il {s['data_primo'].strftime('%d/%m/%Y')} "
                f"e il {s['data_secondo'].strftime('%d/%m/%Y')}: RSI da {s['rsi_primo']} a {s['rsi_secondo']}.")
    if "Rottura" in tipo:
        return f"Il {s['data'].strftime('%d/%m/%Y')}, livello precedente {s['livello_precedente']}."
    if tipo in ("Golden cross", "Death cross"):
        durata = f"{s['giorni_da_incrocio']}gg" if s["certo"] else f"almeno {s['giorni_da_incrocio']}gg"
        return f"EMA50/200 su candele settimanali, da {durata}."
    if tipo == "Volume anomalo":
        return f"Il {s['data'].strftime('%d/%m/%Y')}, {s['rapporto']}x la media a 50 giorni."
    return ""

def segnali_medio_periodo_rows(items):
    """items: lista di (nome, symbol, categoria, lista_segnali)."""
    righe = ""
    for nome, symbol, categoria, segnali in items:
        for s in segnali:
            righe += f"""<tr>
                <td><strong>{nome}</strong><br><span style="color:#999;font-size:11px">{symbol}</span></td>
                <td style="font-size:12px;color:#666">{categoria}</td>
                <td>{_segnale_badge(s['tipo'])}</td>
                <td class="wrap"><div style="color:#444;font-size:12px">{_formatta_dettaglio_segnale(s)}</div></td>
            </tr>"""
    if not righe:
        return ('<tr><td colspan="4" style="text-align:center;color:#999;padding:20px">'
                'Nessun segnale di medio periodo rilevato oggi.</td></tr>')
    return righe

def _analysis_map(items):
    """Costruisce dict symbol→analisi con lookup fuzzy:
    indicizza con il simbolo esatto, senza suffisso (.MI/.PA/…) e senza prefisso exchange."""
    m = {}
    for a in items:
        sym = a.get("symbol", "")
        m[sym] = a
        # senza suffisso (.MI, .PA, ecc.)
        bare = sym.split(".")[0]
        m.setdefault(bare, a)
        # senza prefisso exchange (BVME:ENI → ENI)
        if ":" in bare:
            m.setdefault(bare.split(":")[-1], a)
    return m

def build_html(stocks_it, stocks_us, etfs, portfolio, indices, analysis, password_hash="",
               regole_map=None, calendario=None, segnali_items=None, regole_editor_data=None):
    regole_map = regole_map or {}
    regole_editor_json = json.dumps(regole_editor_data or [], ensure_ascii=False)
    calendario = calendario or []
    segnali_items = segnali_items or []
    today = datetime.now().strftime("%d %B %Y")
    generated = datetime.now().strftime("%d/%m/%Y %H:%M UTC")

    sm_it  = _analysis_map(analysis.get("stocks_it_analysis", []))
    sm_us  = _analysis_map(analysis.get("stocks_us_analysis", []))
    em     = _analysis_map(analysis.get("etfs_analysis", []))
    cm     = _analysis_map(analysis.get("cambiamenti_posizioni", []))
    cx     = _analysis_map(analysis.get("contraddizioni_posizioni", []))
    editor_idx_by_isin = {r["isin"]: i for i, r in enumerate(regole_editor_data or [])}

    # Contesto di mercato per Raccomandazione
    mkt_it = indices.get("FTSE MIB") or 0
    mkt_us = indices.get("S&P 500") or 0
    mkt_eu = ((mkt_it + (indices.get("Eurostoxx 50") or 0)) / 2)

    idx_html = "".join(
        f'<div class="idx-card"><div class="idx-name">{k}</div><div class="idx-val">{idx_badge(v)}</div></div>'
        for k, v in indices.items()
    )

    TABLE_HEAD = """<thead><tr style="background:#1e3a5f;color:white">"""
    TABLE_STYLE = """style="width:100%;border-collapse:collapse;font-size:14px;margin-top:12px" """

    lock_screen = f"""
<div id="lock" style="display:flex;align-items:center;justify-content:center;min-height:100vh;background:linear-gradient(135deg,#1e3a5f,#2d5a8e)">
  <div style="background:white;border-radius:16px;padding:48px;box-shadow:0 8px 40px rgba(0,0,0,0.4);text-align:center;max-width:360px;width:90%">
    <div style="font-size:40px;margin-bottom:16px">📊</div>
    <h2 style="color:#1e3a5f;margin-bottom:8px;font-size:22px">Trading Report</h2>
    <p style="color:#666;font-size:14px;margin-bottom:28px">Accesso riservato</p>
    <input id="pwd" type="password" placeholder="Password" autofocus
      style="width:100%;padding:12px 16px;border:2px solid #e2e8f0;border-radius:8px;font-size:16px;outline:none;margin-bottom:12px">
    <button onclick="unlock()"
      style="width:100%;padding:12px;background:#1e3a5f;color:white;border:none;border-radius:8px;font-size:16px;cursor:pointer;font-weight:600">
      Accedi
    </button>
    <p id="err" style="color:#dc2626;font-size:13px;margin-top:12px;display:none">Password errata</p>
  </div>
</div>
""" if password_hash else ""

    lock_script = f"""
<script>
  const HASH = "{password_hash}";
  const REGOLE_ATTUALI = {regole_editor_json};

  // ─── Autenticazione ───────────────────────────────────────────────────────
  async function sha256(msg) {{
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(msg));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2,"0")).join("");
  }}
  async function unlock() {{
    const h = await sha256(document.getElementById("pwd").value);
    if (h === HASH) {{
      document.getElementById("lock").style.display = "none";
      document.getElementById("report").style.display = "block";
      localStorage.setItem("tr_auth", h);
      localStorage.setItem("tr_exp", Date.now() + 7*24*60*60*1000);
    }} else {{
      document.getElementById("err").style.display = "block";
    }}
  }}
  document.getElementById("pwd").addEventListener("keydown", e => e.key === "Enter" && unlock());
  (async () => {{
    const h = localStorage.getItem("tr_auth");
    const exp = localStorage.getItem("tr_exp");
    if (h && exp && Date.now() < +exp && h === HASH) {{
      document.getElementById("lock").style.display = "none";
      document.getElementById("report").style.display = "block";
    }}
  }})();

  function showGhConfig() {{
    document.getElementById("gh-config").style.display = "block";
    document.getElementById("gh-config-saved").style.display = "none";
  }}

  function hideGhConfig() {{
    document.getElementById("gh-config").style.display = "none";
    document.getElementById("gh-config-saved").style.display = "block";
  }}

  // Se le credenziali sono già salvate da una visita precedente, non
  // mostrare di nuovo il modulo vuoto: sembrerebbe chiedere di nuovo il
  // token anche quando non serve (dispatchWorkflow legge comunque da qui).
  if (localStorage.getItem("gh_owner") && localStorage.getItem("gh_repo") && localStorage.getItem("gh_token")) {{
    hideGhConfig();
  }}

  function saveGhConfig() {{
    const owner = document.getElementById("gh-owner").value.trim();
    const repo  = document.getElementById("gh-repo").value.trim();
    const token = document.getElementById("gh-token").value.trim();
    if (!owner || !repo || !token) {{ alert("Compila tutti i campi"); return; }}
    localStorage.setItem("gh_owner", owner);
    localStorage.setItem("gh_repo",  repo);
    localStorage.setItem("gh_token", token);
    hideGhConfig();
  }}

  async function dispatchWorkflow(inputs) {{
    const owner = localStorage.getItem("gh_owner");
    const repo  = localStorage.getItem("gh_repo");
    const token = localStorage.getItem("gh_token");
    if (!owner || !repo || !token) {{
      showGhConfig();
      throw new Error("Configura prima le impostazioni GitHub");
    }}
    const wfR = await fetch(`https://api.github.com/repos/${{owner}}/${{repo}}/actions/workflows/trading_report.yml/dispatches`, {{
      method:"POST",
      headers:{{"Authorization":`Bearer ${{token}}`,"Accept":"application/vnd.github+json","Content-Type":"application/json"}},
      body:JSON.stringify({{ref:"main", inputs}})
    }});
    if (wfR.status !== 204) {{
      const err = await wfR.text();
      throw new Error(`HTTP ${{wfR.status}}: ${{err}}`);
    }}
  }}

  async function caricaDossier(btn) {{
    const fileInput = document.getElementById("xls-file");
    const file = fileInput.files[0];
    if (!file) {{ setSyncStatus("⚠️ Scegli un file XLS", "#d97706"); return; }}
    btn.disabled = true;
    try {{
      setSyncStatus("⏳ Lettura file...", "#d97706");
      const buf = await file.arrayBuffer();
      const bytes = new Uint8Array(buf);
      let binary = "";
      for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
      const b64 = btoa(binary);
      setSyncStatus("⏳ Caricamento dossier e avvio sincronizzazione...", "#d97706");
      await dispatchWorkflow({{movimenti_xlsx_b64: b64}});
      setSyncStatus("✅ Dossier caricato! Report pronto in ~3-5 minuti. Premi F5 per aggiornare.", "#16a34a");
    }} catch(e) {{
      setSyncStatus(`❌ ${{e.message}}`, "#dc2626");
    }} finally {{
      btn.disabled = false;
    }}
  }}

  function setSyncStatus(msg, color, elId) {{
    const el = document.getElementById(elId || "sync-status");
    if (el) {{ el.textContent = msg; el.style.color = color; }}
  }}

  async function salvaRegolePosizioni(btn) {{
    const isinMap = {{}};
    const regole = {{}};
    let mancaSimbolo = false;
    REGOLE_ATTUALI.forEach((r, i) => {{
      const symbol = (document.getElementById("sym-" + i).value || "").trim();
      const stopV   = (document.getElementById("stop-" + i).value || "").trim();
      const targetV = (document.getElementById("target-" + i).value || "").trim();
      const tesiV   = (document.getElementById("tesi-" + i).value || "").trim();
      const revV    = (document.getElementById("rev-" + i).value || "").trim();
      if (!symbol) {{ mancaSimbolo = true; return; }}
      isinMap[r.isin] = {{tv_symbol: symbol, name: r.name, type: r.type || "Azione"}};
      const regola = {{}};
      if (stopV)   regola.stop = parseFloat(stopV);
      if (targetV) regola.target = parseFloat(targetV);
      if (tesiV)   regola.tesi = tesiV;
      if (revV)    regola.revisione = revV;
      if (r.eventi && r.eventi.length) regola.eventi = r.eventi;
      regole[r.isin] = regola;
    }});
    if (mancaSimbolo) {{ setSyncStatus("⚠️ Ogni riga deve avere un ticker TradingView", "#d97706", "regole-status"); return; }}
    btn.disabled = true;
    try {{
      setSyncStatus("⏳ Salvataggio regole...", "#d97706", "regole-status");
      await dispatchWorkflow({{isin_map_json: JSON.stringify(isinMap), regole_posizioni_yaml: JSON.stringify(regole)}});
      setSyncStatus("✅ Regole salvate! Report pronto in ~3-5 minuti. Premi F5 per aggiornare.", "#16a34a", "regole-status");
    }} catch(e) {{
      setSyncStatus(`❌ ${{e.message}}`, "#dc2626", "regole-status");
    }} finally {{
      btn.disabled = false;
    }}
  }}
</script>
""" if password_hash else ""

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trading Report — {today}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f8fafc; color: #1a1a2e; }}
  .header {{ background: linear-gradient(135deg, #1e3a5f, #2d5a8e); color: white; padding: 32px 40px; }}
  .header h1 {{ font-size: 28px; font-weight: 700; }}
  .header p {{ opacity: 0.75; margin-top: 6px; font-size: 14px; }}
  .container {{ max-width: 1600px; margin: 0 auto; padding: 32px 24px; }}
  .section {{ background: white; border-radius: 12px; padding: 28px; margin-bottom: 24px; box-shadow: 0 1px 4px rgba(0,0,0,0.07); overflow-x: auto; }}
  .section h2 {{ font-size: 18px; color: #1e3a5f; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 2px solid #e2e8f0; }}
  .idx-grid {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .idx-card {{ background: #f0f4f8; border-radius: 8px; padding: 14px 20px; min-width: 140px; }}
  .idx-name {{ font-size: 12px; color: #666; margin-bottom: 4px; }}
  .idx-val {{ font-size: 18px; }}
  .contesto {{ background: #f0f4f8; border-radius: 8px; padding: 16px; margin-top: 16px; font-size: 14px; line-height: 1.7; color: #333; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 12px; }}
  th {{ background: #1e3a5f; color: white; padding: 10px 12px; text-align: left; font-size: 12px; font-weight: 600; }}
  td {{ padding: 8px 10px; border-bottom: 1px solid #e2e8f0; vertical-align: middle; white-space: nowrap; }}
  td.wrap {{ white-space: normal; width: 220px; max-width: 220px; min-width: 120px; vertical-align: top; overflow: hidden; }}
  td.wrap div {{ display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;word-break:break-word;overflow-wrap:break-word;font-size:12px;line-height:1.4;max-width:220px; }}
  td.wrap div:hover {{ -webkit-line-clamp:unset; cursor:help; }}
  tr:nth-child(even) {{ background: #f8fafc; }}
  tr:hover {{ background: #eef2ff; }}
  .badge-count {{ display: inline-block; background: #e2e8f0; color: #555; font-size: 11px; padding: 2px 8px; border-radius: 12px; margin-left: 8px; }}
  .empty-note {{ color: #999; font-size: 13px; font-style: italic; margin-top: 8px; }}
  .sintesi {{ background: #fffbeb; border-left: 4px solid #d97706; padding: 14px 18px; border-radius: 0 8px 8px 0; margin-top: 16px; font-size: 14px; line-height: 1.6; }}
  .disclaimer {{ font-size: 11px; color: #999; line-height: 1.6; margin-top: 8px; }}
  .gen-time {{ font-size: 12px; color: #aaa; text-align: right; margin-top: 8px; }}
  .gh-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }}
  .dd-item {{ padding:9px 12px; cursor:pointer; border-bottom:1px solid #e2e8f0; display:flex; align-items:center; gap:8px; }}
  .dd-item:hover {{ background:#f0f4f8; }}
  @media (max-width: 768px) {{
    .header {{ padding: 20px 16px; }}
    .header h1 {{ font-size: 20px; }}
    .header p {{ font-size: 12px; }}
    .container {{ padding: 12px 8px; }}
    .section {{ padding: 16px 12px; overflow-x: auto; }}
    .section h2 {{ font-size: 15px; }}
    th {{ padding: 7px 6px; font-size: 11px; }}
    td {{ padding: 7px 6px; font-size: 12px; }}
    table {{ font-size: 12px; min-width: 600px; }}
    .idx-grid {{ gap: 8px; }}
    .idx-card {{ min-width: 90px; padding: 10px 12px; }}
    .idx-val {{ font-size: 15px; }}
    .sintesi {{ font-size: 13px; }}
    .gh-grid {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>

{lock_screen}
<div id="report" {"style='display:none'" if password_hash else ""}>

<div class="header">
  <h1>📊 Trading Report</h1>
  <p>{today} — Analisi Momentum Giornaliera</p>
</div>

<div class="container">

  <!-- LE MIE POSIZIONI -->
  <div class="section">
    <h2>Le mie posizioni <span class="badge-count">{len(portfolio)} aperte</span></h2>
    <p class="empty-note">Ticker TradingView, stop, target, revisione e tesi si modificano qui sotto, riga per riga — nessun'altra tabella da cercare.</p>
    <div style="overflow-x:auto">
    <table>
      <thead><tr>
        <th>Titolo</th><th>Prezzo</th><th>Var. da carico</th><th>Giorni detenzione</th>
        <th>Distanza da stop</th><th>Distanza da target</th><th>Trend medio periodo</th>
        <th>Eventi (30gg) / Revisione</th><th>Da notare</th><th>Tesi scritta</th>
      </tr></thead>
      <tbody>{posizioni_rows(portfolio, regole_map, cm, cx, editor_idx_by_isin)}</tbody>
    </table>
    </div>
    <p class="empty-note">Nessun badge di raccomandazione: solo fatti confrontati con quello che hai scritto qui sopra. La decisione resta tua.</p>
    {'''<button onclick="salvaRegolePosizioni(this)"
      style="background:#16a34a;color:white;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:14px;font-weight:600;margin-top:8px">
      💾 Salva regole e aggiorna report
    </button>
    <p id="regole-status" style="font-size:13px;margin-top:12px"></p>''' if editor_idx_by_isin else ''}
  </div>

  <!-- CALENDARIO -->
  <div class="section">
    <h2>Calendario <span class="badge-count">prossimi 60 giorni</span></h2>
    <table>
      <thead><tr><th>Data</th><th>Tipo</th><th>Titolo</th></tr></thead>
      <tbody>{calendario_rows(calendario)}</tbody>
    </table>
  </div>

  <!-- CONTESTO DI MERCATO -->
  <div class="section">
    <h2>Contesto di Mercato</h2>
    <div class="idx-grid">{idx_html}</div>
    <div class="contesto">{analysis.get('contesto_mercato','')}</div>
  </div>

  <!-- DA APPROFONDIRE — GIA IN MOVIMENTO (ITALIA) -->
  <div class="section">
    <h2>Da approfondire — già in movimento (Italia) <span class="badge-count">{len(stocks_it)} oggi</span></h2>
    {"" if stocks_it else '<p class="empty-note">Nessun titolo italiano ha superato tutti i filtri oggi (RSI 50-75, prezzo &gt; EMA20/50, volume in crescita).</p>'}
    <table>
      <thead><tr>
        <th>#</th><th>Titolo</th><th>Prezzo</th><th>RSI</th><th>1M</th><th>3M</th><th>5gg</th><th>Candele 5gg</th><th>Candela 1D</th><th>Candela 1W</th><th>MACD</th><th>Segnale</th><th>Pattern</th><th>Tipo</th><th>Perché sta salendo</th>
      </tr></thead>
      <tbody>{stock_rows(stocks_it, sm_it, mkt_it)}</tbody>
    </table>
  </div>

  <!-- DA APPROFONDIRE — GIA IN MOVIMENTO (USA) -->
  <div class="section">
    <h2>Da approfondire — già in movimento (USA) <span class="badge-count">{len(stocks_us)} oggi</span></h2>
    {"" if stocks_us else '<p class="empty-note">Nessun titolo USA ha superato tutti i filtri oggi.</p>'}
    <table>
      <thead><tr>
        <th>#</th><th>Titolo</th><th>Prezzo</th><th>RSI</th><th>1M</th><th>3M</th><th>5gg</th><th>Candele 5gg</th><th>Candela 1D</th><th>Candela 1W</th><th>MACD</th><th>Segnale</th><th>Pattern</th><th>Tipo</th><th>Perché sta salendo</th>
      </tr></thead>
      <tbody>{stock_rows(stocks_us, sm_us, mkt_us)}</tbody>
    </table>
  </div>

  <!-- SEGNALI DI MEDIO PERIODO -->
  <div class="section">
    <h2>Segnali di medio periodo <span class="badge-count">candele settimanali, 3-12 mesi</span></h2>
    <table>
      <thead><tr><th>Titolo</th><th>Fonte</th><th>Segnale</th><th>Dettaglio</th></tr></thead>
      <tbody>{segnali_medio_periodo_rows(segnali_items)}</tbody>
    </table>
    <p class="empty-note">Solo sulle tue posizioni e sulla watchlist in data/watchlist.yaml — non su tutto il mercato. Un pattern non pulito non viene forzato: niente segnale è meglio di un falso segnale.</p>
  </div>

  <!-- TOP 10 ETF / ETN / ETC ITALIA -->
  <div class="section">
    <h2>Top ETF / ETN / ETC (Borsa Italiana) — Momentum <span class="badge-count">{len(etfs)} oggi</span></h2>
    {"" if etfs else '<p class="empty-note">Nessun ETF/ETN/ETC ha superato tutti i filtri oggi.</p>'}
    <table>
      <thead><tr>
        <th>#</th><th>Ticker</th><th>Tema</th><th>Prezzo</th><th>RSI</th><th>1M</th><th>3M</th><th>5gg</th><th>Candele 5gg</th><th>Candela 1D</th><th>Candela 1W</th><th>MACD</th><th>Segnale</th><th>Pattern</th><th>Rec.</th><th>TER</th><th>AUM</th><th>Motivazione</th>
      </tr></thead>
      <tbody>{etf_rows(etfs, em, mkt_eu)}</tbody>
    </table>
  </div>

  <!-- SINCRONIZZA DATI PERSONALI -->
  <div class="section">
    <h2>📂 Sincronizza dati personali</h2>
    <div id="gh-config" style="background:#f0f4f8;border-radius:8px;padding:16px;margin-bottom:16px">
      <p style="font-size:13px;color:#555;margin-bottom:12px">Inserisci una volta le credenziali GitHub — vengono salvate nel browser, non sul server.</p>
      <div class="gh-grid">
        <div>
          <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">GitHub Username</label>
          <input id="gh-owner" type="text" placeholder="es. miouser"
            style="width:100%;padding:8px;border:1px solid #ddd;border-radius:6px;font-size:14px">
        </div>
        <div>
          <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">Repository name</label>
          <input id="gh-repo" type="text" placeholder="es. trading-report"
            style="width:100%;padding:8px;border:1px solid #ddd;border-radius:6px;font-size:14px">
        </div>
      </div>
      <div style="margin-bottom:12px">
        <label style="font-size:12px;color:#666;display:block;margin-bottom:4px">Personal Access Token (scope: <code>repo</code>)</label>
        <input id="gh-token" type="password" placeholder="ghp_..."
          style="width:100%;padding:8px;border:1px solid #ddd;border-radius:6px;font-size:14px">
      </div>
      <button onclick="saveGhConfig()"
        style="background:#1e3a5f;color:white;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:14px;font-weight:600">
        Salva impostazioni
      </button>
    </div>
    <div id="gh-config-saved" style="display:none;font-size:13px;color:#555;margin-bottom:16px">
      Impostazioni GitHub caricate. <a href="#" onclick="showGhConfig();return false" style="color:#1e3a5f">Modifica</a>
    </div>

    <div>
      <label style="font-size:13px;font-weight:600;color:#1e3a5f;display:block;margin-bottom:6px">Dossier titoli (XLS)</label>
      <p style="font-size:12px;color:#666;margin-bottom:8px">Carica il file "Movimenti Dossier Titoli" o "Portafoglio di sintesi" esportato dal tuo broker (.xlsx o .xls). Ricostruisce le posizioni aperte automaticamente — le righe da compilare (ticker, stop, target, tesi) compaiono in "Le mie posizioni" qui sopra, senza bisogno di scendere fin qui.</p>
      <input id="xls-file" type="file" accept=".xlsx,.xls" style="margin-bottom:8px;display:block;font-size:13px">
      <button onclick="caricaDossier(this)"
        style="background:#1e3a5f;color:white;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:14px;font-weight:600">
        Carica e sincronizza
      </button>
    </div>

    <p id="sync-status" style="font-size:13px;margin-top:16px"></p>
  </div>

  <!-- FOOTER -->
  <div class="section">
    <p class="disclaimer">
      Questo report è generato automaticamente a scopo informativo e non costituisce consulenza finanziaria.
      Le decisioni di investimento sono responsabilità esclusiva dell'investitore.
      I dati tecnici sono calcolati su prezzi storici di chiusura e potrebbero non riflettere le quotazioni in tempo reale.
    </p>
    <p class="gen-time">Generato il {generated}</p>
  </div>

</div>
</div>
{lock_script}</body>
</html>"""
    return html

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    logger.info("=== Trading Report Generator (GitHub Pages) ===")

    indices   = get_indices()
    stocks_it = screen_italy()
    stocks_us = screen_usa()
    etfs      = screen_etfs()
    portfolio = get_portfolio_data()

    # Ultime 5 sedute (OHLC) per il grafico a candele e la performance 5gg.
    # Richiede una chiamata HTTP per titolo: fallisce in silenzio sul singolo simbolo.
    logger.info("Recupero OHLC ultimi 5 giorni...")
    enrich_5d(stocks_it, "azioni IT")
    enrich_5d(stocks_us, "azioni US")
    enrich_5d(etfs,      "ETP")
    enrich_5d(portfolio, "portafoglio")

    logger.info("Recupero storico 5 anni per le posizioni (EMA reali, non stimate)...")
    enrich_storico_esteso(portfolio, "portafoglio")

    logger.info("Caricamento regole posizioni, calendario macro e watchlist...")
    regole_map = regole.load_regole()
    eventi_macro = regole.load_eventi_macro()
    calendario = build_calendario(portfolio, regole_map, eventi_macro)
    watchlist_data = get_watchlist_data(regole.load_watchlist())
    enrich_storico_esteso(watchlist_data, "watchlist")

    logger.info("Calcolo segnali di medio periodo (Sezione 4)...")
    segnali_items = [
        (p.get("name", p.get("symbol", "")), p.get("yf_symbol", p.get("symbol", "")), "Posizione",
         segnali_medio_periodo.calcola_segnali(p.get("bars_storico") or []))
        for p in portfolio
    ] + [
        (w.get("name", w.get("symbol", "")), w.get("yf_symbol", w.get("symbol", "")), "Watchlist",
         segnali_medio_periodo.calcola_segnali(w.get("bars_storico") or []))
        for w in watchlist_data
    ]

    logger.info("Aggiornamento storico persistente...")
    storico.record_daily(portfolio, stocks_it + stocks_us)

    logger.info("Generating analysis with Claude...")
    analysis = generate_analysis(stocks_it, stocks_us, etfs, portfolio, indices, regole_map)

    logger.info("Building HTML...")
    pwd = os.environ.get("SITE_PASSWORD", "")
    pwd_hash = hashlib.sha256(pwd.encode()).hexdigest() if pwd else ""
    regole_editor_data = []
    for p in portfolio:
        isin = p.get("isin")
        if not isin:
            continue
        regola = regole_map.get(isin) or {}
        regole_editor_data.append({
            "isin": isin,
            "symbol": p.get("yf_symbol", p.get("symbol", "")),
            "name": p.get("name", p.get("symbol", "")),
            "type": p.get("type", "Azione"),
            "stop": regola.get("stop"),
            "target": regola.get("target"),
            "tesi": regola.get("tesi") or "",
            "revisione": regola["revisione"].isoformat() if regola.get("revisione") else None,
            "eventi": [{"tipo": e["tipo"], "data": e["data"].isoformat()} for e in regola.get("eventi", [])],
        })
    html = build_html(stocks_it, stocks_us, etfs, portfolio, indices, analysis, pwd_hash,
                       regole_map, calendario, segnali_items, regole_editor_data)

    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("Saved to docs/index.html")

if __name__ == "__main__":
    main()
