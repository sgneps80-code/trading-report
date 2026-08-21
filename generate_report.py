#!/usr/bin/env python3
"""
Trading Report — TradingView Edition
Screener:  scanner.tradingview.com  (Italia + USA, incluse small/mid cap)
Analisi:   RSI + MACD + Trend EMA + Raccomandazione TV aggregata (26 indicatori)
AI:        Anthropic Claude Haiku
"""

import os, json, hashlib, logging
from datetime import datetime
import requests
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ─── PORTFOLIO ────────────────────────────────────────────────────────────────
_portfolio_input = os.environ.get("PORTFOLIO_INPUT", "").strip()
if _portfolio_input:
    PORTFOLIO = json.loads(_portfolio_input)
    logger.info("Portfolio caricato da workflow_dispatch")
else:
    PORTFOLIO = json.loads(os.environ.get("PORTFOLIO_JSON", "[]"))
    logger.info("Portfolio caricato da PORTFOLIO_JSON secret")

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
    "change|3M",                # performance 3 mesi %
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

def parse_tv_row(row):
    """Converte una riga dello screener TV nel formato interno."""
    s    = row.get("s", "")       # "BVME:ENI"
    vals = row.get("d", [])
    d    = dict(zip(TV_COLS, vals))

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
    p3m    = d.get("change|3M")
    rec    = d.get("Rec.All") or 0
    vol    = d.get("volume")                 or 0
    vol10d = d.get("average_volume_10d_calc") or 0
    high3m = d.get("High.3M")  or 0
    low3m  = d.get("Low.3M")   or 0
    high52 = d.get("52WkHigh") or 0
    low52  = d.get("52WkLow")  or 0

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
def _passes_momentum(r, min_price=0.2, min_perf1m=0):
    """Filtro applicato in Python dopo la risposta TV (evita cross-column filter API)."""
    if not r.get("price") or r["price"] < min_price:
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
    logger.info(f"Italia: {len(rows)} titoli → top {min(10, len(rows))}")
    return rows[:10]

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
    logger.info(f"USA: {len(rows)} titoli → top {min(10, len(rows))}")
    return rows[:10]

# ─── SCREENER ETF ─────────────────────────────────────────────────────────────
def screen_etfs():
    logger.info("Screening ETF — TradingView...")
    payload = {
        "filter": [
            {"left": "RSI",                     "operation": "in_range", "right": [35, 82]},
            {"left": "average_volume_10d_calc", "operation": "greater",  "right": 5000},
            {"left": "MACD.hist",               "operation": "greater",  "right": 0},
        ],
        "options": {"lang": "en"},
        "markets": ["america", "italy", "germany"],
        "symbols": {"query": {"types": ["fund", "dr"]}, "tickers": []},
        "columns": TV_COLS,
        "sort": {"sortBy": "change|1M", "sortOrder": "desc"},
        "range": [0, 150]
    }
    data = tv_request("https://scanner.tradingview.com/global/scan", payload)
    rows = [parse_tv_row(r) for r in (data.get("data") or [])]
    rows = [r for r in rows if r.get("price") and _passes_momentum(r, min_price=0.5, min_perf1m=0)]
    rows.sort(key=momentum_score, reverse=True)
    logger.info(f"ETF: {len(rows)} trovati → top {min(10, len(rows))}")
    return rows[:10]

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
        out.append(parsed)
    return out

# ─── INDICI DI MERCATO ────────────────────────────────────────────────────────
INDICES_MAP = {
    "S&P 500":      "^GSPC",
    "NASDAQ":       "^IXIC",
    "Eurostoxx 50": "^STOXX50E",
    "FTSE MIB":     "FTSEMIB.MI",
}

def get_indices():
    """Recupera variazione % degli indici via Yahoo Finance JSON API (no libreria)."""
    out = {}
    syms = ",".join(INDICES_MAP.values())
    try:
        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={syms}"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        r.raise_for_status()
        quotes = r.json().get("quoteResponse", {}).get("result", [])
        by_sym = {v: k for k, v in INDICES_MAP.items()}
        for q in quotes:
            name = by_sym.get(q.get("symbol", ""))
            chg  = q.get("regularMarketChangePercent")
            if name and chg is not None:
                out[name] = round(chg, 2)
    except Exception as e:
        logger.warning(f"Indices fetch: {e}")
    for name in INDICES_MAP:
        out.setdefault(name, None)
    return out

# ─── ANALISI CLAUDE ──────────────────────────────────────────────────────────

def generate_analysis(stocks_it, stocks_us, etfs, portfolio, indices):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def fmt(lst):
        if not lst:
            return "Nessun titolo ha superato il filtro oggi."
        return "\n".join(
            f"- {d['symbol']} ({d.get('name','')}): prezzo {d['price']}, RSI {d['rsi']}, "
            f"1M {d.get('perf_1m','n.d.')}%, MACD {d.get('macd_str','n.d.')}, TV Rec: {d.get('rec_str','n.d.')}"
            for d in lst
        )

    port_txt = "\n".join(
        f"- {p['name']} ({p.get('yf_symbol', p['symbol'])}): prezzo {p.get('price','n.d.')}, "
        f"RSI {p.get('rsi','n.d.')}, trend {p.get('trend','n.d.')}, "
        f"MACD {p.get('macd_str','n.d.')}, 1M {p.get('perf_1m','n.d.')}%, TV Rec: {p.get('rec_str','n.d.')}"
        for p in portfolio
    ) or "Portafoglio vuoto."

    idx_txt = "\n".join(
        f"- {k}: {v:+.2f}%" if v is not None else f"- {k}: n.d."
        for k, v in indices.items()
    )

    prompt = f"""Sei un analista finanziario esperto. Data: {datetime.now().strftime('%d/%m/%Y')}.

I dati tecnici provengono da TradingView. MACD indica la direzione del momentum (↑ = rialzista, ↓ = ribassista).
TV Rec è la raccomandazione aggregata di 26 indicatori TradingView (Compra Forte / Compra / Neutro / Vendi / Vendi Forte).

INDICI:
{idx_txt}

TOP AZIONI ITALIANE (screener TV — filtro RSI+EMA+MACD):
{fmt(stocks_it)}

TOP AZIONI USA (screener TV — filtro RSI+EMA+MACD+cap>100M):
{fmt(stocks_us)}

TOP ETF (screener TV — filtro RSI+EMA+MACD):
{fmt(etfs)}

PORTAFOGLIO STEFANO:
{port_txt}

Genera un JSON con questa struttura ESATTA (solo JSON puro, zero markdown):
{{
  "contesto_mercato": "2-3 frasi professionali su sentiment e indici",
  "stocks_it_analysis": [{{"symbol":"TICKER","motivazione":"2-3 righe che citano MACD e TV Rec","rating":"Forte"}}],
  "stocks_us_analysis": [{{"symbol":"TICKER","motivazione":"2-3 righe che citano MACD e TV Rec","rating":"Moderato"}}],
  "etfs_analysis": [{{"symbol":"TICKER","tema":"AI / Semiconduttori / ecc.","motivazione":"2-3 righe","rating":"Forte"}}],
  "portfolio_analysis": [{{"symbol":"TICKER","segnale":"Accumula","motivazione":"2-3 righe con riferimento a MACD e trend"}}],
  "sintesi_portafoglio": "2-3 frasi di sintesi operativa"
}}
Rating: Forte o Moderato. Segnale: Accumula, Mantieni o Riduci.
Usa il campo symbol uguale al ticker TV per portfolio_analysis (es. "OMER", "PANW", "MIL:SMH").
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

def signal_badge(s):
    colors = {"Accumula": "#16a34a", "Riduci": "#dc2626", "Mantieni": "#d97706"}
    c = colors.get(s, "#d97706")
    return f'<span style="color:{c};font-weight:700">● {s}</span>'

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
    return f'<span style="color:{color};font-size:12px;font-weight:600">{macd_str}</span>'

def rec_badge(rec_str):
    """Badge TV Rec.All (aggregato 26 indicatori)."""
    colors = {
        "Compra Forte": "#15803d", "Compra": "#16a34a",
        "Neutro": "#888", "Vendi": "#dc2626", "Vendi Forte": "#991b1b",
    }
    c = colors.get(rec_str, "#888")
    return f'<span style="color:{c};font-size:12px;font-weight:700">● {rec_str}</span>'

def stock_rows(lst, analysis_map):
    if not lst:
        return '<tr><td colspan="12" style="text-align:center;color:#999;padding:20px">Nessun titolo ha superato il filtro oggi (RSI 48-75, prezzo &gt; EMA20/50, MACD &gt; 0)</td></tr>'
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
            <td>{candle_badge(d.get('candle_d','—'))}</td>
            <td>{candle_badge(d.get('candle_w','—'))}</td>
            <td>{macd_badge(d.get('macd_str','n.d.'))}</td>
            <td>{_composite_badge(*compute_signal(d))}</td>
            <td style="font-size:12px">{detect_pattern(d)}</td>
            <td style="font-size:13px;color:#444">{a.get('motivazione','')}</td>
        </tr>"""
    return rows

def etf_rows(lst, analysis_map):
    if not lst:
        return '<tr><td colspan="12" style="text-align:center;color:#999;padding:20px">Nessun ETF ha superato il filtro oggi</td></tr>'
    rows = ""
    for i, d in enumerate(lst, 1):
        a = analysis_map.get(d["symbol"], {})
        price_str = f"{d['price']:.2f}" if d.get("price") else "n.d."
        rows += f"""<tr>
            <td style="color:#999;font-size:12px">{i}</td>
            <td><strong>{d['symbol']}</strong></td>
            <td style="color:#6366f1;font-size:13px">{a.get('tema','Tematico')}</td>
            <td>{price_str}</td>
            <td>{d['rsi'] if d.get('rsi') else 'n.d.'}</td>
            <td>{pct(d.get('perf_1m'))}</td>
            <td>{pct(d.get('perf_3m'))}</td>
            <td>{candle_badge(d.get('candle_d','—'))}</td>
            <td>{candle_badge(d.get('candle_w','—'))}</td>
            <td>{macd_badge(d.get('macd_str','n.d.'))}</td>
            <td>{_composite_badge(*compute_signal(d))}</td>
            <td style="font-size:12px">{detect_pattern(d)}</td>
            <td style="font-size:13px;color:#444">{a.get('motivazione','')}</td>
        </tr>"""
    return rows

def portfolio_rows(portfolio, analysis_map):
    rows = ""
    for p in portfolio:
        # yf_symbol ora è in formato TV (es. "MIL:OMER" o "PANW")
        # Claude risponde con il ticker senza prefisso exchange (es. "OMER")
        # → prova prima la chiave piena, poi il ticker nudo
        sym_key = p.get("yf_symbol", p.get("symbol", ""))
        bare_key = sym_key.split(":")[-1] if ":" in sym_key else sym_key
        a = analysis_map.get(sym_key) or analysis_map.get(bare_key, {})
        trend = p.get("trend", "n.d.")
        trend_color = {
            "Rialzista": "#16a34a", "Rialzista (>EMA200)": "#15803d",
            "Ribassista": "#dc2626", "Laterale": "#d97706", "Sopra EMA20": "#2563eb",
        }.get(trend, "#999")
        price_str = f"{p['price']:.2f}" if p.get("price") else "n.d."
        yf_sym = p.get("yf_symbol", sym_key)
        rows += f"""<tr>
            <td><strong>{p['name']}</strong><br><span style="color:#999;font-size:11px">{yf_sym}</span></td>
            <td style="font-size:12px;color:#666">{p.get('type','')}</td>
            <td>{price_str}</td>
            <td>{p['rsi'] if p.get('rsi') else 'n.d.'}</td>
            <td style="color:{trend_color};font-weight:600;font-size:12px">{trend}</td>
            <td>{pct(p.get('perf_1m'))}</td>
            <td>{pct(p.get('perf_3m'))}</td>
            <td>{candle_badge(p.get('candle_d','—'))}</td>
            <td>{candle_badge(p.get('candle_w','—'))}</td>
            <td>{macd_badge(p.get('macd_str','n.d.'))}</td>
            <td>{_composite_badge(*compute_signal(p))}</td>
            <td style="font-size:12px">{detect_pattern(p)}</td>
            <td>{signal_badge(a.get('segnale','Mantieni'))}</td>
            <td style="font-size:13px;color:#444">{a.get('motivazione','')}</td>
        </tr>"""
    return rows

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

def build_html(stocks_it, stocks_us, etfs, portfolio, indices, analysis, password_hash="", portfolio_base="[]"):
    today = datetime.now().strftime("%d %B %Y")
    generated = datetime.now().strftime("%d/%m/%Y %H:%M UTC")

    sm_it  = _analysis_map(analysis.get("stocks_it_analysis", []))
    sm_us  = _analysis_map(analysis.get("stocks_us_analysis", []))
    em     = _analysis_map(analysis.get("etfs_analysis", []))
    pm     = _analysis_map(analysis.get("portfolio_analysis", []))

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
  const PORTFOLIO_BASE = {portfolio_base};

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
      initEditor();
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
      initEditor();
    }}
  }})();

  // ─── Editor Portafoglio ───────────────────────────────────────────────────
  let editorPortfolio = [];

  function initEditor() {{
    const saved = localStorage.getItem("editor_portfolio");
    const parsed = saved ? JSON.parse(saved) : null;
    editorPortfolio = (parsed && parsed.length > 0) ? parsed : JSON.parse(JSON.stringify(PORTFOLIO_BASE));
    localStorage.setItem("editor_portfolio", JSON.stringify(editorPortfolio));
    renderEditorTable();
    const owner = localStorage.getItem("gh_owner") || "";
    const repo  = localStorage.getItem("gh_repo")  || "";
    const token = localStorage.getItem("gh_token") || "";
    document.getElementById("gh-owner").value = owner;
    document.getElementById("gh-repo").value  = repo;
    if (owner && repo && token) {{
      document.getElementById("gh-config").style.display = "none";
      document.getElementById("gh-config-saved").style.display = "block";
    }}
  }}

  function renderEditorTable() {{
    document.getElementById("editor-tbody").innerHTML = editorPortfolio.map(function(item, i) {{
      return '<tr style="border-bottom:1px solid #e2e8f0">' +
        '<td style="padding:8px 6px;width:36px;text-align:center">' +
          '<input type="checkbox" class="row-cb" data-i="' + i + '" style="width:16px;height:16px;cursor:pointer">' +
        '</td>' +
        '<td style="padding:8px 6px;font-family:monospace;font-size:13px;font-weight:600;color:#1e3a5f">' + item.symbol + '</td>' +
        '<td style="padding:8px 6px;font-size:13px">' + item.name + '</td>' +
        '<td style="padding:8px 6px;font-size:12px;color:#666">' + (item.type || 'Azione') + '</td>' +
        '<td style="padding:8px 6px;text-align:center">' +
          '<button onclick="removeItem(' + i + ')" title="Rimuovi" ' +
            'style="color:#dc2626;background:none;border:none;cursor:pointer;font-size:20px;line-height:1;padding:2px">×</button>' +
        '</td>' +
        '</tr>';
    }}).join("");
  }}

  function toggleAll(cb) {{
    document.querySelectorAll(".row-cb").forEach(function(c) {{ c.checked = cb.checked; }});
  }}

  function deleteSelected() {{
    var toDelete = new Set([].slice.call(document.querySelectorAll(".row-cb:checked")).map(function(c) {{ return +c.dataset.i; }}));
    if (!toDelete.size) {{ setStatus("⚠️ Nessun titolo selezionato", "#d97706", 3000); return; }}
    editorPortfolio = editorPortfolio.filter(function(_, i) {{ return !toDelete.has(i); }});
    localStorage.setItem("editor_portfolio", JSON.stringify(editorPortfolio));
    var allCb = document.getElementById("check-all");
    if (allCb) allCb.checked = false;
    renderEditorTable();
  }}

  function removeItem(i) {{
    editorPortfolio.splice(i, 1);
    localStorage.setItem("editor_portfolio", JSON.stringify(editorPortfolio));
    renderEditorTable();
  }}

  // ─── Ricerca titoli ───────────────────────────────────────────────────────
  var STATIC_STOCKS = [
    // ── Italiani (Borsa Milano) ──
    {{symbol:"ENI.MI",shortname:"ENI",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"ENEL.MI",shortname:"Enel",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"ISP.MI",shortname:"Intesa Sanpaolo",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"UCG.MI",shortname:"UniCredit",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"STLAM.MI",shortname:"Stellantis",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"MB.MI",shortname:"Mediobanca",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"G.MI",shortname:"Generali",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"LDO.MI",shortname:"Leonardo",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"RACE.MI",shortname:"Ferrari",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"MONC.MI",shortname:"Moncler",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"PRY.MI",shortname:"Prysmian",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"BAMI.MI",shortname:"Banco BPM",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"BPSO.MI",shortname:"BPER Banca",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"BMPS.MI",shortname:"Banca Monte dei Paschi",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"TIT.MI",shortname:"Telecom Italia",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"SRG.MI",shortname:"Snam",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"TRN.MI",shortname:"Terna",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"A2A.MI",shortname:"A2A",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"HER.MI",shortname:"Hera",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"CPR.MI",shortname:"Campari",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"NEXI.MI",shortname:"Nexi",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"FBK.MI",shortname:"FinecoBank",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"AMP.MI",shortname:"Amplifon",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"AZM.MI",shortname:"Azimut",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"POSTE.MI",shortname:"Poste Italiane",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"SPM.MI",shortname:"Saipem",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"STS.MI",shortname:"STMicroelectronics",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"INWT.MI",shortname:"Inwit",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"PIRC.MI",shortname:"Pirelli",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"IVECO.MI",shortname:"Iveco Group",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"MFEA.MI",shortname:"MFE-MediaForEurope",exchDisp:"MIL",quoteType:"EQUITY"}},
    {{symbol:"REC.MI",shortname:"Recordati",exchDisp:"MIL",quoteType:"EQUITY"}},
    // ── Francesi (Euronext Paris) ──
    {{symbol:"MC.PA",shortname:"LVMH",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"OR.PA",shortname:"L'Oreal",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"TTE.PA",shortname:"TotalEnergies",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"BNP.PA",shortname:"BNP Paribas",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"AI.PA",shortname:"Air Liquide",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"SAN.PA",shortname:"Sanofi",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"SAF.PA",shortname:"Safran",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"SU.PA",shortname:"Schneider Electric",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"GLE.PA",shortname:"Societe Generale",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"CS.PA",shortname:"AXA",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"RMS.PA",shortname:"Hermes",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"KER.PA",shortname:"Kering",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"DG.PA",shortname:"Vinci",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"CAP.PA",shortname:"Capgemini",exchDisp:"EPA",quoteType:"EQUITY"}},
    {{symbol:"DSY.PA",shortname:"Dassault Systemes",exchDisp:"EPA",quoteType:"EQUITY"}},
    // ── Tedeschi (Xetra) ──
    {{symbol:"SAP.DE",shortname:"SAP",exchDisp:"XETRA",quoteType:"EQUITY"}},
    {{symbol:"SIE.DE",shortname:"Siemens",exchDisp:"XETRA",quoteType:"EQUITY"}},
    {{symbol:"ALV.DE",shortname:"Allianz",exchDisp:"XETRA",quoteType:"EQUITY"}},
    {{symbol:"MUV2.DE",shortname:"Munich Re",exchDisp:"XETRA",quoteType:"EQUITY"}},
    {{symbol:"BAS.DE",shortname:"BASF",exchDisp:"XETRA",quoteType:"EQUITY"}},
    {{symbol:"BMW.DE",shortname:"BMW",exchDisp:"XETRA",quoteType:"EQUITY"}},
    {{symbol:"VOW3.DE",shortname:"Volkswagen",exchDisp:"XETRA",quoteType:"EQUITY"}},
    {{symbol:"DBK.DE",shortname:"Deutsche Bank",exchDisp:"XETRA",quoteType:"EQUITY"}},
    {{symbol:"MBG.DE",shortname:"Mercedes-Benz",exchDisp:"XETRA",quoteType:"EQUITY"}},
    {{symbol:"BAYN.DE",shortname:"Bayer",exchDisp:"XETRA",quoteType:"EQUITY"}},
    {{symbol:"ADS.DE",shortname:"Adidas",exchDisp:"XETRA",quoteType:"EQUITY"}},
    {{symbol:"RHM.DE",shortname:"Rheinmetall",exchDisp:"XETRA",quoteType:"EQUITY"}},
    // ── USA ──
    {{symbol:"AAPL",shortname:"Apple",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"MSFT",shortname:"Microsoft",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"GOOGL",shortname:"Alphabet (Google)",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"AMZN",shortname:"Amazon",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"META",shortname:"Meta Platforms",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"NVDA",shortname:"NVIDIA",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"TSLA",shortname:"Tesla",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"JPM",shortname:"JPMorgan Chase",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"V",shortname:"Visa",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"JNJ",shortname:"Johnson & Johnson",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"WMT",shortname:"Walmart",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"PG",shortname:"Procter & Gamble",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"BAC",shortname:"Bank of America",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"MA",shortname:"Mastercard",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"XOM",shortname:"Exxon Mobil",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"KO",shortname:"Coca-Cola",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"LLY",shortname:"Eli Lilly",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"AVGO",shortname:"Broadcom",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"COST",shortname:"Costco",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"NFLX",shortname:"Netflix",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"PANW",shortname:"Palo Alto Networks",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"CRM",shortname:"Salesforce",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"AMD",shortname:"AMD",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"INTC",shortname:"Intel",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"QCOM",shortname:"Qualcomm",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"GS",shortname:"Goldman Sachs",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"MS",shortname:"Morgan Stanley",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"CVX",shortname:"Chevron",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"LMT",shortname:"Lockheed Martin",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"RTX",shortname:"RTX (Raytheon)",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"BA",shortname:"Boeing",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"GE",shortname:"GE Aerospace",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"CAT",shortname:"Caterpillar",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"HON",shortname:"Honeywell",exchDisp:"NASDAQ",quoteType:"EQUITY"}},
    {{symbol:"DIS",shortname:"Disney",exchDisp:"NYSE",quoteType:"EQUITY"}},
    {{symbol:"NKE",shortname:"Nike",exchDisp:"NYSE",quoteType:"EQUITY"}},
    // ── ETF ──
    {{symbol:"VWCE.DE",shortname:"Vanguard FTSE All-World",exchDisp:"XETRA",quoteType:"ETF"}},
    {{symbol:"IWDA.AS",shortname:"iShares MSCI World",exchDisp:"AMS",quoteType:"ETF"}},
    {{symbol:"SWDA.MI",shortname:"iShares Core MSCI World",exchDisp:"MIL",quoteType:"ETF"}},
    {{symbol:"CSPX.MI",shortname:"iShares Core S&P 500",exchDisp:"MIL",quoteType:"ETF"}},
    {{symbol:"EIMI.MI",shortname:"iShares MSCI EM IMI",exchDisp:"MIL",quoteType:"ETF"}},
    {{symbol:"VEUR.AS",shortname:"Vanguard FTSE Developed Europe",exchDisp:"AMS",quoteType:"ETF"}},
    {{symbol:"XWLD.MI",shortname:"Xtrackers MSCI World Swap",exchDisp:"MIL",quoteType:"ETF"}},
    {{symbol:"EXSA.DE",shortname:"iShares Euro Stoxx 50",exchDisp:"XETRA",quoteType:"ETF"}},
    {{symbol:"AGGH.MI",shortname:"iShares Core Global Aggregate Bond",exchDisp:"MIL",quoteType:"ETF"}},
    {{symbol:"SGLD.MI",shortname:"Invesco Physical Gold ETC",exchDisp:"MIL",quoteType:"ETF"}},
    {{symbol:"PHAU.MI",shortname:"WisdomTree Physical Gold",exchDisp:"MIL",quoteType:"ETF"}},
    {{symbol:"GLD",shortname:"SPDR Gold Shares",exchDisp:"NYSE",quoteType:"ETF"}},
    {{symbol:"SPY",shortname:"SPDR S&P 500 ETF",exchDisp:"NYSE",quoteType:"ETF"}},
    {{symbol:"QQQ",shortname:"Invesco QQQ Trust",exchDisp:"NASDAQ",quoteType:"ETF"}},
    {{symbol:"VTI",shortname:"Vanguard Total Stock Market",exchDisp:"NYSE",quoteType:"ETF"}},
    {{symbol:"XAR.MI",shortname:"SPDR S&P Aerospace & Defense",exchDisp:"MIL",quoteType:"ETF"}},
    {{symbol:"L8I7.DE",shortname:"iShares Global Clean Energy",exchDisp:"XETRA",quoteType:"ETF"}},
    {{symbol:"IQQH.DE",shortname:"iShares Global Water",exchDisp:"XETRA",quoteType:"ETF"}},
    {{symbol:"QDVE.DE",shortname:"iShares S&P 500 IT Sector",exchDisp:"XETRA",quoteType:"ETF"}}
  ];

  function guessType(quote) {{
    var qt = (quote.quoteType || "").toUpperCase();
    if (qt === "ETF" || qt === "MUTUALFUND") return "ETF";
    return "Azione";
  }}

  // Mappa exchange TradingView → suffisso Yahoo Finance
  var TV_SUFFIX = {{
    "BVME":".MI","MIL":".MI","XMIL":".MI",
    "XPAR":".PA","EPA":".PA",
    "XETR":".DE","XETRA":".DE","FWB":".F",
    "XAMS":".AS","AMS":".AS",
    "LSE":".L","XLON":".L",
    "XSTO":".ST","STO":".ST",
    "XHEL":".HE","HEL":".HE",
    "XCOP":".CO","CPH":".CO",
    "XOSL":".OL","OSL":".OL",
    "XSWX":".SW","SWX":".SW",
    "XMAD":".MC","MCE":".MC",
    "XLIS":".LS","LIS":".LS",
    "XBRU":".BR","BRU":".BR",
    "XWAR":".WA","WSE":".WA",
    "XASX":".AX","ASX":".AX",
    "XTSE":".T","TSE":".T",
    "HKEX":".HK","HKG":".HK",
    "XTSX":".TO","TSX":".TO",
    "JSE":".JO"
  }};

  function tvToYahoo(symbol, exchange) {{
    var us = ["NYSE","NASDAQ","AMEX","CBOE","BATS","ARCA"];
    for (var i = 0; i < us.length; i++) {{ if (exchange === us[i]) return symbol; }}
    var sfx = TV_SUFFIX[exchange];
    return sfx ? symbol + sfx : symbol;
  }}

  function searchLocal(q) {{
    var ql = q.toLowerCase();
    return STATIC_STOCKS.filter(function(s) {{
      return s.symbol.toLowerCase().indexOf(ql) >= 0 ||
             s.shortname.toLowerCase().indexOf(ql) >= 0;
    }}).slice(0, 8);
  }}

  var _searchResults = [];
  var _searchTimer = null;
  function onSearchInput() {{
    clearTimeout(_searchTimer);
    var q = document.getElementById("stock-search").value.trim();
    if (!q) {{ hideDropdown(); return; }}
    _searchTimer = setTimeout(function() {{ doSearch(q); }}, 300);
  }}

  async function doSearch(q) {{
    document.getElementById("manual-add").style.display = "none";
    var local = searchLocal(q);
    if (local.length > 0) {{
      showDropdown(local);
      document.getElementById("search-status").textContent = "🔍 Espandendo ricerca...";
    }} else {{
      document.getElementById("search-status").textContent = "🔍 Ricerca in corso...";
    }}
    // 1) TradingView (ampia copertura, incluse small/mid cap)
    try {{
      var tv = await searchTradingView(q);
      if (tv.length > 0) {{
        var seen = {{}};
        var merged = local.concat(tv).filter(function(s) {{
          if (seen[s.symbol]) return false;
          seen[s.symbol] = true; return true;
        }}).slice(0, 12);
        showDropdown(merged);
        document.getElementById("search-status").textContent = "";
        return;
      }}
    }} catch(e) {{}}
    // 2) Yahoo Finance via proxy
    try {{
      var yf = await searchYahoo(q);
      if (yf.length > 0) {{
        showDropdown(yf);
        document.getElementById("search-status").textContent = "";
        return;
      }}
    }} catch(e) {{}}
    // 3) Solo lista locale o nessun risultato
    if (local.length > 0) {{
      showDropdown(local);
      document.getElementById("search-status").textContent = "";
    }} else {{
      hideDropdown();
      document.getElementById("search-status").textContent = "Nessun risultato. Aggiungi il ticker manualmente.";
      document.getElementById("manual-add").style.display = "inline-block";
    }}
  }}

  async function fetchJSON(url, timeoutMs) {{
    var r = await Promise.race([
      fetch(url),
      new Promise(function(_, rej) {{ setTimeout(function(){{ rej(new Error("timeout")); }}, timeoutMs || 5000); }})
    ]);
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }}

  async function searchTradingView(q) {{
    var enc = encodeURIComponent(q);
    // Endpoint TV — senza sort_by_country per risultati globali
    var tvUrl = "https://symbol-search.tradingview.com/symbol_search/v3/?text=" +
                enc + "&hl=1&exchange=&lang=en&search_type=undefined&domain=production";
    var tvUrlOld = "https://symbol-search.tradingview.com/symbol_search/?text=" +
                   enc + "&exchange=&lang=en&type=&domain=production";

    // Tentativi: diretto, proxy corsproxy, proxy allorigins (raw)
    var attempts = [
      tvUrl,
      "https://corsproxy.io/?" + encodeURIComponent(tvUrl),
      "https://api.allorigins.win/raw?url=" + encodeURIComponent(tvUrl),
      tvUrlOld,
      "https://corsproxy.io/?" + encodeURIComponent(tvUrlOld)
    ];

    function parseTV(data) {{
      // allorigins/get wrap
      if (data && data.contents) {{ try {{ data = JSON.parse(data.contents); }} catch(e) {{}} }}
      var symbols = data && data.symbols ? data.symbols : (Array.isArray(data) ? data : []);
      return symbols.slice(0, 15).map(function(s) {{
        var exch = s.exchange || s.listed_exchange || "";
        var ticker = s.symbol || "";
        var tvSym = (exch && ticker) ? exch + ":" + ticker : ticker;
        var tp = (s.type === "fund" || s.type === "dr" || s.type === "structured") ? "ETF" : "Azione";
        return {{symbol: tvSym, shortname: s.description || s.symbol, exchDisp: exch,
                 quoteType: tp === "ETF" ? "ETF" : "EQUITY"}};
      }}).filter(function(s) {{ return s.symbol && s.symbol.length > 0; }});
    }}

    for (var i = 0; i < attempts.length; i++) {{
      try {{
        var data = await fetchJSON(attempts[i], 5000);
        var results = parseTV(data);
        if (results.length > 0) return results;
      }} catch(e) {{ /* continua */ }}
    }}
    return [];
  }}

  async function searchYahoo(q) {{
    var yf = "https://query1.finance.yahoo.com/v1/finance/search?q=" +
             encodeURIComponent(q) + "&lang=en-US&region=US&quotesCount=10&newsCount=0";
    var proxies = [
      {{url: "https://api.allorigins.win/raw?url=" + encodeURIComponent(yf), wrap: false}},
      {{url: "https://corsproxy.io/?" + encodeURIComponent(yf), wrap: false}},
      {{url: "https://api.allorigins.win/get?url=" + encodeURIComponent(yf), wrap: true}}
    ];
    for (var i = 0; i < proxies.length; i++) {{
      try {{
        var p = proxies[i];
        var data = await fetchJSON(p.url, 5000);
        if (p.wrap && data.contents) data = JSON.parse(data.contents);
        var quotes = (data.finance && data.finance.result &&
                      data.finance.result[0] && data.finance.result[0].quotes) || [];
        if (quotes.length) return quotes;
      }} catch(e) {{ continue; }}
    }}
    return [];
  }}

  function showDropdown(results) {{
    _searchResults = results.slice(0, 10);
    var dd = document.getElementById("search-dropdown");
    dd.innerHTML = _searchResults.map(function(q, idx) {{
      var sym = q.symbol || "";
      var nm  = q.shortname || q.longname || sym;
      var ex  = q.exchDisp || q.exchange || "";
      var tp  = guessType(q);
      return '<div class="dd-item" onmousedown="addFromSearch(' + idx + ')">' +
        '<span style="font-weight:600;font-family:monospace;color:#1e3a5f;min-width:70px">' + sym + '</span>' +
        '<span style="flex:1;font-size:13px;color:#333;overflow:hidden;text-overflow:ellipsis">' + nm + '</span>' +
        '<span style="font-size:11px;color:#888;white-space:nowrap">' + ex + ' &middot; ' + tp + '</span>' +
        '</div>';
    }}).join("");
    dd.style.display = "block";
  }}

  function hideDropdown() {{
    var dd = document.getElementById("search-dropdown");
    if (dd) dd.style.display = "none";
  }}

  function addFromSearch(idx) {{
    var item = _searchResults[idx];
    if (!item) return;
    var rawSym = (item.symbol || "").toUpperCase();
    var exch   = (item.exchDisp || "").toUpperCase();
    // Se il simbolo è in formato Yahoo (es. ENI.MI), converti in formato TV (MIL:ENI)
    var symbol;
    if (rawSym.indexOf(".") >= 0 && exch) {{
      symbol = exch + ":" + rawSym.split(".")[0];
    }} else {{
      symbol = rawSym;
    }}
    var name   = item.shortname || item.longname || symbol;
    var type   = guessType(item);
    hideDropdown();
    document.getElementById("stock-search").value = "";
    document.getElementById("search-status").textContent = "";
    document.getElementById("manual-add").style.display = "none";
    if (editorPortfolio.some(function(p) {{ return p.symbol === symbol; }})) {{
      setStatus("⚠️ " + symbol + " già presente nel portafoglio", "#d97706", 3000);
      return;
    }}
    editorPortfolio.push({{symbol: symbol, name: name, type: type}});
    localStorage.setItem("editor_portfolio", JSON.stringify(editorPortfolio));
    renderEditorTable();
    setStatus("✅ " + symbol + " aggiunto", "#16a34a", 3000);
  }}

  function addManualTicker() {{
    var sym = document.getElementById("stock-search").value.trim().toUpperCase();
    if (!sym) {{ setStatus("⚠️ Inserisci un ticker", "#d97706", 3000); return; }}
    if (editorPortfolio.some(function(p) {{ return p.symbol === sym; }})) {{
      setStatus("⚠️ " + sym + " già presente nel portafoglio", "#d97706", 3000);
      return;
    }}
    editorPortfolio.push({{symbol: sym, name: sym, type: "Azione"}});
    localStorage.setItem("editor_portfolio", JSON.stringify(editorPortfolio));
    renderEditorTable();
    document.getElementById("stock-search").value = "";
    document.getElementById("manual-add").style.display = "none";
    document.getElementById("search-status").textContent = "";
    setStatus("✅ " + sym + " aggiunto", "#16a34a", 3000);
  }}

  function showGhConfig() {{
    document.getElementById("gh-config").style.display = "block";
    document.getElementById("gh-config-saved").style.display = "none";
  }}

  function saveGhConfig() {{
    const owner = document.getElementById("gh-owner").value.trim();
    const repo  = document.getElementById("gh-repo").value.trim();
    const token = document.getElementById("gh-token").value.trim();
    if (!owner || !repo || !token) {{ alert("Compila tutti i campi"); return; }}
    localStorage.setItem("gh_owner", owner);
    localStorage.setItem("gh_repo",  repo);
    localStorage.setItem("gh_token", token);
    document.getElementById("gh-config").style.display = "none";
    document.getElementById("gh-config-saved").style.display = "block";
    setStatus("✅ Impostazioni salvate", "#16a34a", 3000);
  }}

  function setStatus(msg, color, timeout) {{
    const el = document.getElementById("editor-status");
    el.textContent = msg; el.style.color = color;
    if (timeout) setTimeout(() => {{ el.textContent = ""; }}, timeout);
  }}

  async function triggerReport(btn) {{
    const owner = localStorage.getItem("gh_owner");
    const repo  = localStorage.getItem("gh_repo");
    const token = localStorage.getItem("gh_token");
    if (!owner || !repo || !token) {{
      showGhConfig();
      setStatus("⚠️ Configura prima le impostazioni GitHub", "#d97706");
      return;
    }}
    const valid = editorPortfolio.filter(p => p.symbol.trim() && p.name.trim());
    if (!valid.length) {{ setStatus("⚠️ Aggiungi almeno un titolo valido", "#d97706"); return; }}
    btn.disabled = true;
    try {{
      setStatus("⏳ Avvio generazione report...", "#d97706");
      const wfR = await fetch(`https://api.github.com/repos/${{owner}}/${{repo}}/actions/workflows/trading_report.yml/dispatches`, {{
        method:"POST",
        headers:{{"Authorization":`Bearer ${{token}}`,"Accept":"application/vnd.github+json","Content-Type":"application/json"}},
        body:JSON.stringify({{ref:"main", inputs:{{portfolio_json: JSON.stringify(valid)}}}})
      }});
      if (wfR.status !== 204) {{
        const err = await wfR.text();
        throw new Error(`HTTP ${{wfR.status}}: ${{err}}`);
      }}
      localStorage.setItem("editor_portfolio", JSON.stringify(valid));
      editorPortfolio = valid;
      renderEditorTable();
      setStatus("✅ Report avviato! Pronto in ~3-5 minuti. Premi F5 per aggiornare la pagina.", "#16a34a");
    }} catch(e) {{
      setStatus(`❌ ${{e.message}}`, "#dc2626");
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
  .container {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px; }}
  .section {{ background: white; border-radius: 12px; padding: 28px; margin-bottom: 24px; box-shadow: 0 1px 4px rgba(0,0,0,0.07); }}
  .section h2 {{ font-size: 18px; color: #1e3a5f; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 2px solid #e2e8f0; }}
  .idx-grid {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .idx-card {{ background: #f0f4f8; border-radius: 8px; padding: 14px 20px; min-width: 140px; }}
  .idx-name {{ font-size: 12px; color: #666; margin-bottom: 4px; }}
  .idx-val {{ font-size: 18px; }}
  .contesto {{ background: #f0f4f8; border-radius: 8px; padding: 16px; margin-top: 16px; font-size: 14px; line-height: 1.7; color: #333; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 12px; }}
  th {{ background: #1e3a5f; color: white; padding: 10px 12px; text-align: left; font-size: 12px; font-weight: 600; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }}
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

  <!-- CONTESTO DI MERCATO -->
  <div class="section">
    <h2>Contesto di Mercato</h2>
    <div class="idx-grid">{idx_html}</div>
    <div class="contesto">{analysis.get('contesto_mercato','')}</div>
  </div>

  <!-- TOP 10 AZIONI ITALIANE -->
  <div class="section">
    <h2>Top Azioni Italiane — Momentum <span class="badge-count">{len(stocks_it)} oggi</span></h2>
    {"" if stocks_it else '<p class="empty-note">Nessun titolo italiano ha superato tutti i filtri oggi (RSI 50-75, prezzo &gt; EMA20/50, volume in crescita).</p>'}
    <table>
      <thead><tr>
        <th>#</th><th>Titolo</th><th>Prezzo</th><th>RSI</th><th>1M</th><th>3M</th><th>Candela 1D</th><th>Candela 1W</th><th>MACD</th><th>Segnale</th><th>Pattern</th><th>Motivazione</th>
      </tr></thead>
      <tbody>{stock_rows(stocks_it, sm_it)}</tbody>
    </table>
  </div>

  <!-- TOP 10 AZIONI USA -->
  <div class="section">
    <h2>Top Azioni USA — Momentum <span class="badge-count">{len(stocks_us)} oggi</span></h2>
    {"" if stocks_us else '<p class="empty-note">Nessun titolo USA ha superato tutti i filtri oggi.</p>'}
    <table>
      <thead><tr>
        <th>#</th><th>Titolo</th><th>Prezzo</th><th>RSI</th><th>1M</th><th>3M</th><th>Candela 1D</th><th>Candela 1W</th><th>MACD</th><th>Segnale</th><th>Pattern</th><th>Motivazione</th>
      </tr></thead>
      <tbody>{stock_rows(stocks_us, sm_us)}</tbody>
    </table>
  </div>

  <!-- TOP 10 ETF TEMATICI -->
  <div class="section">
    <h2>Top ETF Tematici — Momentum <span class="badge-count">{len(etfs)} oggi</span></h2>
    {"" if etfs else '<p class="empty-note">Nessun ETF ha superato tutti i filtri oggi.</p>'}
    <table>
      <thead><tr>
        <th>#</th><th>Ticker</th><th>Tema</th><th>Prezzo</th><th>RSI</th><th>1M</th><th>3M</th><th>Candela 1D</th><th>Candela 1W</th><th>MACD</th><th>Segnale</th><th>Pattern</th>
      </tr></thead>
      <tbody>{etf_rows(etfs, em)}</tbody>
    </table>
  </div>

  <!-- PORTAFOGLIO -->
  <div class="section">
    <h2>💼 Portafoglio — Analisi Tecnica</h2>
    <table>
      <thead><tr>
        <th>Titolo</th><th>Tipo</th><th>Prezzo</th><th>RSI</th><th>Trend</th><th>1M</th><th>3M</th><th>Candela 1D</th><th>Candela 1W</th><th>MACD</th><th>Segnale</th><th>Pattern</th><th>Operativo</th><th>Analisi</th>
      </tr></thead>
      <tbody>{portfolio_rows(portfolio, pm)}</tbody>
    </table>
    <div class="sintesi"><strong>Sintesi operativa:</strong> {analysis.get('sintesi_portafoglio','')}</div>
  </div>

  <!-- AGGIORNA PORTAFOGLIO -->
  <div class="section">
    <h2>🔧 Aggiorna Portafoglio</h2>
    <div id="gh-config" style="background:#f0f4f8;border-radius:8px;padding:16px;margin-bottom:16px">
      <p style="font-size:13px;color:#555;margin-bottom:12px">Inserisci una volta le credenziali GitHub — vengono salvate nel browser.</p>
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
    <div id="gh-config-saved" style="display:none;font-size:13px;color:#555;margin-bottom:12px">
      Impostazioni GitHub caricate. <a href="#" onclick="showGhConfig();return false" style="color:#1e3a5f">Modifica</a>
    </div>

    <!-- Tabella portafoglio con checkbox -->
    <table style="width:100%;border-collapse:collapse;margin-bottom:8px">
      <thead>
        <tr style="background:#1e3a5f;color:white">
          <th style="padding:10px 6px;width:36px;text-align:center">
            <input type="checkbox" id="check-all" onchange="toggleAll(this)" style="width:16px;height:16px;cursor:pointer">
          </th>
          <th style="padding:10px;text-align:left;font-size:12px">Simbolo</th>
          <th style="padding:10px;text-align:left;font-size:12px">Nome</th>
          <th style="padding:10px;text-align:left;font-size:12px">Tipo</th>
          <th style="padding:10px;width:36px"></th>
        </tr>
      </thead>
      <tbody id="editor-tbody"></tbody>
    </table>
    <div style="margin-bottom:16px">
      <button onclick="deleteSelected()"
        style="background:#dc2626;color:white;border:none;padding:7px 16px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600">
        🗑 Elimina selezionati
      </button>
    </div>

    <!-- Ricerca e aggiunta titoli -->
    <div style="margin-bottom:16px">
      <label style="font-size:12px;color:#666;display:block;margin-bottom:6px;font-weight:600">Aggiungi titolo</label>
      <div style="display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap">
        <div style="position:relative;flex:1;min-width:220px">
          <input id="stock-search" type="text"
            placeholder="Cerca per nome o ticker (es. ENI, Apple, VWCE)..."
            oninput="onSearchInput()" onblur="setTimeout(hideDropdown,200)"
            style="width:100%;padding:9px 12px;border:1px solid #ddd;border-radius:6px;font-size:14px">
          <div id="search-dropdown"
            style="display:none;position:absolute;top:100%;left:0;right:0;background:white;border:1px solid #ddd;border-radius:6px;box-shadow:0 4px 12px rgba(0,0,0,0.15);z-index:100;max-height:300px;overflow-y:auto;margin-top:2px">
          </div>
        </div>
        <div id="manual-add" style="display:none">
          <button onclick="addManualTicker()"
            style="background:#1e3a5f;color:white;border:none;padding:9px 14px;border-radius:6px;cursor:pointer;font-size:13px;white-space:nowrap">
            ➕ Aggiungi come ticker
          </button>
        </div>
      </div>
      <div id="search-status" style="font-size:12px;color:#888;margin-top:6px"></div>
    </div>

    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
      <button onclick="triggerReport(this)"
        style="background:#16a34a;color:white;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:14px;font-weight:600">
        🚀 Aggiorna Report
      </button>
      <span id="editor-status" style="font-size:13px"></span>
    </div>
    <p style="font-size:11px;color:#999;margin-top:10px">Il portafoglio aggiornato viene usato subito e salvato come secret GitHub dal workflow — non è visibile nel repository.</p>
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

    logger.info("Generating analysis with Claude...")
    analysis = generate_analysis(stocks_it, stocks_us, etfs, portfolio, indices)

    logger.info("Building HTML...")
    pwd = os.environ.get("SITE_PASSWORD", "")
    pwd_hash = hashlib.sha256(pwd.encode()).hexdigest() if pwd else ""
    portfolio_base = json.dumps([
        {"symbol": p["symbol"], "name": p.get("name", p["symbol"]), "type": p.get("type", "Azione")}
        for p in PORTFOLIO
    ], ensure_ascii=False)
    html = build_html(stocks_it, stocks_us, etfs, portfolio, indices, analysis, pwd_hash, portfolio_base)

    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("Saved to docs/index.html")

if __name__ == "__main__":
    main()
