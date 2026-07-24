#!/usr/bin/env python3
"""
Trading Report Generator
Genera ogni giorno un PDF con top 10 azioni, top 10 ETF tematici e analisi portafoglio,
poi lo carica su Google Drive nella cartella "Trading Reports".

VERSIONE 2 — Analisi più profonda e segnali STABILI:
- Segnale operativo calcolato da un modello tecnico deterministico multi-periodo
  (EMA20/50/200, RSI giornaliero e settimanale, performance 1M/3M/6M).
- Memoria del segnale del giorno precedente (salvato su Drive) con ISTERESI:
  un titolo non puo' passare da "Accumula" a "Riduci" in un solo giorno.
- Claude non decide piu' il segnale: lo SPIEGA in modo coerente e giustifica
  ogni cambiamento rispetto al giorno prima.
"""

import io
import os
import json
import logging
from datetime import datetime
import numpy as np
import pandas as pd
import yfinance as yf
import anthropic
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, HRFlowable
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
import google.auth.transport.requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─── CONFIGURAZIONE ──────────────────────────────────────────────────────────

GDRIVE_FOLDER_ID = "1F7FL8HNG3Epr_hPJm8IvSTCTND4IGlNz"
STATE_FILENAME = "report-state.json"   # memoria dei segnali del giorno prima (su Drive)

# Modello Claude per l'analisi testuale.
# Per un'analisi ancora piu' approfondita puoi provare un modello Sonnet, es:
#   CLAUDE_MODEL = "claude-sonnet-4-5"
# (se il modello non e' disponibile sul tuo account, il report fallira'
#  nello step di analisi: in quel caso rimetti la riga qui sotto.)
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

PORTFOLIO = [
    {"symbol": "OMER.MI",  "name": "OMER",                              "type": "Azione"},
    {"symbol": "PANW",     "name": "Palo Alto Networks",                "type": "Azione"},
    {"symbol": "GBSE.MI",  "name": "WisdomTree Physical Gold EUR Hedged", "type": "ETC"},
    {"symbol": "SMH.MI",   "name": "VanEck Semiconductor UCITS ETF",    "type": "ETF"},
    {"symbol": "EXSA.MI",  "name": "iShares STOXX Europe 600 UCITS ETF", "type": "ETF"},
    {"symbol": "MC.PA",    "name": "LVMH",                              "type": "Azione"},
    {"symbol": "RKTO",     "name": "Rocket One Inc",                    "type": "Azione"},
]

STOCK_UNIVERSE = [
    # US Tech / AI / Semi
    "NVDA", "AMD", "MSFT", "AAPL", "GOOGL", "META", "AMZN", "AVGO", "TSM", "QCOM",
    "CRM", "NOW", "SNOW", "PLTR", "PANW", "CRWD", "DDOG", "NET", "ARM", "MRVL",
    # US Finance
    "JPM", "GS", "V", "MA", "BRK-B", "COIN",
    # US Healthcare
    "LLY", "NVO", "ABBV", "UNH", "ISRG", "DXCM",
    # US Energy / Industrial
    "XOM", "CVX", "CAT", "DE", "HON", "RTX", "GE", "LMT",
    # US Consumer / Other
    "TSLA", "NKE", "COST", "AMGN",
    # European ADR / dual-listed
    "ASML", "SAP",
]

ETF_UNIVERSE = [
    # AI / Tech
    "QQQ", "VGT", "FTEC", "IGV", "ARKW",
    # Semiconductors
    "SOXX", "SMH", "SOXQ", "PSI",
    # AI / Robotics
    "BOTZ", "ROBO", "IRBO", "THNQ",
    # Clean Energy
    "ICLN", "QCLN", "TAN", "RNRG",
    # Healthcare / Biotech
    "XLV", "IBB", "ARKG", "XBI",
    # Cybersecurity
    "HACK", "BUG", "CIBR",
    # Defense
    "ITA", "XAR",
    # Fintech
    "ARKF", "FINX",
    # Thematic / Innovation
    "ARKK", "MOAT", "ARKQ",
]

# ─── ANALISI TECNICA ─────────────────────────────────────────────────────────

def calculate_rsi(prices: pd.Series, period: int = 14) -> float | None:
    if len(prices) < period + 1:
        return None
    delta = prices.diff().dropna()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("inf"))
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1)


def calculate_ema(prices: pd.Series, period: int) -> float | None:
    if len(prices) < period:
        return None
    return float(prices.ewm(span=period, adjust=False).mean().iloc[-1])


def volume_ratio(volume: pd.Series, period: int = 20) -> float | None:
    if len(volume) < period:
        return None
    avg = volume.rolling(window=period).mean().iloc[-1]
    return round(float(volume.iloc[-1] / avg), 2) if avg > 0 else None


def performance(prices: pd.Series, days: int) -> float | None:
    if len(prices) < days:
        return None
    return round(float((prices.iloc[-1] / prices.iloc[-days] - 1) * 100), 1)


# ─── CANDELE GIAPPONESI (riconoscimento pattern) ─────────────────────────────
#
# Confronta le ultime candele OHLC con le figure classiche dell'analisi
# candlestick e restituisce nome, direzione e significato. Le figure sono
# controllate in ordine di forza: 3 candele → 2 candele → 1 candela.

def _cndl(o, h, l, c):
    """Metriche di una candela: corpo, range, ombra sup./inf., toro/orso."""
    body = abs(c - o)
    rng = (h - l) if (h - l) > 0 else 1e-9
    upper = h - max(o, c)
    lower = min(o, c) - l
    return body, rng, upper, lower


def _result(pattern, direction, meaning):
    return {"pattern": pattern, "direction": direction, "meaning": meaning}


def detect_candle_pattern(df) -> dict:
    """df: DataFrame con colonne Open/High/Low/Close. Analizza le ultime candele."""
    try:
        if df is None or len(df) < 2:
            return _result("Dati insuff.", "Neutro", "storico troppo breve")
        rows = df.tail(3)
        vals = [(float(r.Open), float(r.High), float(r.Low), float(r.Close))
                for r in rows.itertuples(index=False)]

        # Candela corrente e precedente
        o, h, l, c = vals[-1]
        o1, h1, l1, c1 = vals[-2]
        body, rng, upper, lower = _cndl(o, h, l, c)
        body1, rng1, upper1, lower1 = _cndl(o1, h1, l1, c1)
        bull, bull1 = c > o, c1 > o1

        # ─── 3 CANDELE ───────────────────────────────────────────────
        if len(vals) >= 3:
            o0, h0, l0, c0 = vals[-3]
            bull0 = c0 > o0
            body0 = abs(c0 - o0)
            mid0 = (o0 + c0) / 2

            # Stella del mattino (inversione rialzista)
            if (not bull0 and body0 > 0.5 * (h0 - l0 + 1e-9)
                    and body1 < body0 * 0.6 and bull and c > mid0):
                return _result("Stella del mattino", "Rialzista",
                               "inversione rialzista forte dopo un ribasso")
            # Stella della sera (inversione ribassista)
            if (bull0 and body0 > 0.5 * (h0 - l0 + 1e-9)
                    and body1 < body0 * 0.6 and not bull and c < mid0):
                return _result("Stella della sera", "Ribassista",
                               "inversione ribassista forte dopo un rialzo")
            # Tre soldati bianchi
            if bull0 and bull1 and bull and c1 > c0 and c > c1:
                return _result("Tre soldati bianchi", "Rialzista",
                               "trend rialzista consolidato")
            # Tre corvi neri
            if (not bull0) and (not bull1) and (not bull) and c1 < c0 and c < c1:
                return _result("Tre corvi neri", "Ribassista",
                               "trend ribassista consolidato")

        # ─── 2 CANDELE ───────────────────────────────────────────────
        # Engulfing rialzista
        if (not bull1) and bull and c >= o1 and o <= c1 and body > body1:
            return _result("Engulfing rialzista", "Rialzista",
                           "i compratori inglobano la candela precedente")
        # Engulfing ribassista
        if bull1 and (not bull) and o >= c1 and c <= o1 and body > body1:
            return _result("Engulfing ribassista", "Ribassista",
                           "i venditori inglobano la candela precedente")
        # Piercing line
        if (not bull1) and bull and o < c1 and c > (o1 + c1) / 2 and c < o1:
            return _result("Piercing line", "Rialzista",
                           "recupero deciso dei compratori")
        # Dark cloud cover
        if bull1 and (not bull) and o > c1 and c < (o1 + c1) / 2 and c > o1:
            return _result("Dark cloud cover", "Ribassista",
                           "rientro deciso dei venditori")
        # Harami rialzista (debole)
        if (not bull1) and bull and body1 > body * 1.5 and o >= c1 and c <= o1:
            return _result("Harami rialzista", "Rialzista (debole)",
                           "possibile stabilizzazione dopo il calo")
        # Harami ribassista (debole)
        if bull1 and (not bull) and body1 > body * 1.5 and o <= c1 and c >= o1:
            return _result("Harami ribassista", "Ribassista (debole)",
                           "possibile stallo dopo la salita")

        # ─── 1 CANDELA ───────────────────────────────────────────────
        # Doji (indecisione)
        if body <= 0.1 * rng:
            return _result("Doji", "Neutro", "indecisione, possibile svolta")
        # Martello (rialzista)
        if lower >= 2 * body and upper <= 0.35 * body and body > 0:
            return _result("Martello", "Rialzista",
                           "possibile inversione al rialzo dopo un ribasso")
        # Stella cadente (ribassista)
        if upper >= 2 * body and lower <= 0.35 * body and body > 0:
            return _result("Stella cadente", "Ribassista",
                           "possibile inversione al ribasso dopo un rialzo")
        # Marubozu (corpo pieno = continuazione forte)
        if body >= 0.85 * rng:
            if bull:
                return _result("Marubozu rialzista", "Rialzista",
                               "forte pressione in acquisto")
            return _result("Marubozu ribassista", "Ribassista",
                           "forte pressione in vendita")
        # Trottola (indecisione)
        if body <= 0.35 * rng and upper > 0 and lower > 0:
            return _result("Trottola", "Neutro", "indecisione tra tori e orsi")

        # Nessuna figura rilevante → indica solo il colore della candela
        if bull:
            return _result("Candela neutra", "Rialzista (lieve)", "chiusura sopra apertura")
        return _result("Candela neutra", "Ribassista (lieve)", "chiusura sotto apertura")
    except Exception as e:
        logger.warning(f"Pattern detect error: {e}")
        return _result("n.d.", "Neutro", "")


def get_ticker_data(symbol: str) -> dict | None:
    try:
        # 1 anno di storico: serve per l'EMA200 (trend di lungo periodo)
        hist = yf.Ticker(symbol).history(period="1y")
        if hist.empty or len(hist) < 60:
            return None
        close, volume = hist["Close"], hist["Volume"]

        # Trend settimanale (riduce il rumore giornaliero)
        weekly = close.resample("W").last().dropna()
        rsi_w = calculate_rsi(weekly) if len(weekly) >= 15 else None

        # OHLC per il riconoscimento delle candele (giornaliero e settimanale)
        ohlc_daily = hist[["Open", "High", "Low", "Close"]]
        ohlc_weekly = hist.resample("W").agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
        ).dropna()

        return {
            "symbol": symbol,
            "price": float(close.iloc[-1]),
            "rsi": calculate_rsi(close),
            "rsi_w": rsi_w,
            "ema20": calculate_ema(close, 20),
            "ema50": calculate_ema(close, 50),
            "ema200": calculate_ema(close, 200),
            "vol_ratio": volume_ratio(volume),
            "perf_1m": performance(close, 21),
            "perf_3m": performance(close, 63),
            "perf_6m": performance(close, 126),
            "cndl_daily": detect_candle_pattern(ohlc_daily),
            "cndl_weekly": detect_candle_pattern(ohlc_weekly),
        }
    except Exception as e:
        logger.warning(f"Skip {symbol}: {e}")
        return None


def passes_filter(d: dict) -> bool:
    if d is None or d["price"] < 5:
        return False
    if d["rsi"] is None or not (50 <= d["rsi"] <= 75):
        return False
    if d["ema20"] is None or d["price"] < d["ema20"]:
        return False
    if d["ema50"] is None or d["price"] < d["ema50"]:
        return False
    if d["vol_ratio"] is None or d["vol_ratio"] < 1.0:
        return False
    return True


def momentum_score(d: dict) -> float:
    return (
        (d["rsi"] - 50) * 0.5 +
        (d.get("perf_1m") or 0) * 0.3 +
        (d.get("perf_3m") or 0) * 0.2 +
        ((d["vol_ratio"] or 1) - 1) * 5
    )


def screen_universe(universe: list, label: str) -> list:
    logger.info(f"Screening {label} ({len(universe)} candidates)...")
    results = [d for sym in universe if (d := get_ticker_data(sym)) and passes_filter(d)]
    for d in results:
        d["score"] = momentum_score(d)
    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"{label}: {len(results)} passed → top {min(10, len(results))}")
    return results[:10]


# ─── SEGNALE OPERATIVO STABILE (deterministico + isteresi) ───────────────────

def technical_score(d: dict) -> float | None:
    """
    Punteggio tecnico multi-periodo. Piu' alto = piu' forte.
    Combina trend di lungo (EMA200), medio (EMA50), breve (EMA20),
    momentum (RSI giornaliero e settimanale) e performance 1M/3M/6M.
    Essendo deterministico, a parita' di dati produce SEMPRE lo stesso valore.
    """
    price = d.get("price")
    if not price:
        return None

    score = 0.0

    # Trend (peso maggiore al lungo periodo → stabilita')
    if d.get("ema200") is not None:
        score += 2.0 if price > d["ema200"] else -2.0
    if d.get("ema50") is not None:
        score += 1.5 if price > d["ema50"] else -1.5
    if d.get("ema20") is not None:
        score += 1.0 if price > d["ema20"] else -1.0

    # Momentum RSI giornaliero (con zona neutra per evitare il rumore)
    rsi = d.get("rsi")
    if rsi is not None:
        if rsi >= 70:      score += 0.5     # forte ma occhio all'ipercomprato
        elif rsi >= 55:    score += 1.5
        elif rsi >= 45:    score += 0.0     # zona neutra
        elif rsi >= 30:    score -= 1.5
        else:              score -= 0.5     # ipervenduto: possibile rimbalzo

    # RSI settimanale (conferma di medio periodo)
    rsi_w = d.get("rsi_w")
    if rsi_w is not None:
        score += 1.0 if rsi_w >= 50 else -1.0

    # Performance (con tetto per non farsi dominare da un singolo dato)
    for key, weight in (("perf_1m", 0.05), ("perf_3m", 0.03), ("perf_6m", 0.02)):
        v = d.get(key)
        if v is not None:
            score += max(min(v * weight, 2.0), -2.0)

    return round(score, 2)


def decide_signal(score: float | None, prev: str | None) -> str:
    """
    Traduce il punteggio in segnale operativo con ISTERESI e transizioni
    a un solo gradino: Riduci ↔ Mantieni ↔ Accumula.
    Impossibile passare da 'Accumula' a 'Riduci' (o viceversa) in un giorno.
    """
    if score is None:
        return "Mantieni"

    def base(s: float) -> str:
        if s >= 3.0:  return "Accumula"
        if s <= -2.0: return "Riduci"
        return "Mantieni"

    # Primo run oppure si parte da "Mantieni": usa le bande base
    if prev is None or prev == "Mantieni":
        return base(score)

    # Da "Accumula": resta finche' non si indebolisce chiaramente, poi scende
    # di UN solo gradino (a "Mantieni"), mai direttamente a "Riduci".
    if prev == "Accumula":
        return "Accumula" if score >= 1.0 else "Mantieni"

    # Da "Riduci": resta finche' non recupera, poi sale di UN solo gradino.
    if prev == "Riduci":
        return "Riduci" if score <= -0.5 else "Mantieni"

    return base(score)


def get_portfolio_data() -> list:
    results = []
    for item in PORTFOLIO:
        d = get_ticker_data(item["symbol"]) or {}
        d["name"] = item["name"]
        d["type"] = item["type"]
        d["symbol"] = item["symbol"]
        if d.get("price") and d.get("ema20") and d.get("ema50"):
            if d["price"] > d["ema20"] and d["price"] > d["ema50"]:
                d["trend"] = "Rialzista"
            elif d["price"] < d["ema20"] and d["price"] < d["ema50"]:
                d["trend"] = "Ribassista"
            else:
                d["trend"] = "Laterale"
        else:
            d["trend"] = "n.d."
        results.append(d)
    return results


def apply_signals(portfolio: list, prev_state: dict) -> list:
    """Calcola il segnale stabile per ogni posizione usando la memoria del giorno prima."""
    for p in portfolio:
        p["score"] = technical_score(p)
        prev = (prev_state.get(p["symbol"]) or {}).get("signal")
        p["prev_signal"] = prev
        p["segnale"] = decide_signal(p["score"], prev)
        p["changed"] = bool(prev is not None and prev != p["segnale"])
    return portfolio


def get_index_data() -> dict:
    indices = {"S&P 500": "^GSPC", "NASDAQ": "^IXIC", "Eurostoxx 50": "^STOXX50E", "FTSE MIB": "FTSEMIB.MI"}
    out = {}
    for name, sym in indices.items():
        try:
            hist = yf.Ticker(sym).history(period="5d")
            out[name] = round(float((hist["Close"].iloc[-1] / hist["Close"].iloc[-2] - 1) * 100), 2) if len(hist) >= 2 else None
        except:
            out[name] = None
    return out


# ─── ANALISI CLAUDE ──────────────────────────────────────────────────────────

def _fmt2(v) -> str:
    return f"{v:.2f}" if isinstance(v, (int, float)) else "n.d."


def generate_analysis(stocks: list, etfs: list, portfolio: list, indices: dict) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today = datetime.now().strftime("%d/%m/%Y")

    def fmt(lst):
        return "\n".join(
            f"- {d['symbol']}: prezzo {d['price']:.2f}, RSI {d['rsi']}, RSI_sett {d.get('rsi_w','n.d.')}, "
            f"1M {d.get('perf_1m','n.d.')}%, 3M {d.get('perf_3m','n.d.')}%, 6M {d.get('perf_6m','n.d.')}%, "
            f"vol_ratio {d.get('vol_ratio','n.d.')}"
            for d in lst
        )

    port_lines = []
    for p in portfolio:
        change_note = ""
        if p.get("changed") and p.get("prev_signal"):
            change_note = (f"  >>> SEGNALE CAMBIATO da '{p['prev_signal']}' a '{p['segnale']}' "
                           f"rispetto a ieri: spiega in modo esplicito cosa e' cambiato.")
        cd = p.get("cndl_daily") or {}
        cw = p.get("cndl_weekly") or {}
        port_lines.append(
            f"- {p['name']} ({p['symbol']}) [{p.get('type','')}]: "
            f"prezzo {_fmt2(p.get('price'))}, trend {p.get('trend','n.d.')}, "
            f"RSI {p.get('rsi','n.d.')}, RSI_sett {p.get('rsi_w','n.d.')}, "
            f"EMA20 {_fmt2(p.get('ema20'))}, EMA50 {_fmt2(p.get('ema50'))}, EMA200 {_fmt2(p.get('ema200'))}, "
            f"1M {p.get('perf_1m','n.d.')}%, 3M {p.get('perf_3m','n.d.')}%, 6M {p.get('perf_6m','n.d.')}%, "
            f"score {p.get('score','n.d.')}. "
            f"Candela giornaliera: {cd.get('pattern','n.d.')} ({cd.get('direction','')}); "
            f"Candela settimanale: {cw.get('pattern','n.d.')} ({cw.get('direction','')}). "
            f"SEGNALE GIA' CALCOLATO (NON modificarlo): {p.get('segnale')}.{change_note}"
        )
    port_txt = "\n".join(port_lines)
    idx_txt = "\n".join(f"- {k}: {v:+.2f}%" if v is not None else f"- {k}: n.d." for k, v in indices.items())

    prompt = f"""Sei un analista finanziario esperto e RIGOROSO. Data: {today}.

Il tuo compito e' scrivere motivazioni professionali e APPROFONDITE, NON inventare i segnali.
Il segnale operativo di ogni posizione del portafoglio e' GIA' stato calcolato da un modello
tecnico deterministico multi-periodo (EMA20/50/200 + RSI giornaliero e settimanale + performance
1M/3M/6M) con isteresi. NON devi cambiarlo: devi spiegarlo in modo coerente.

REGOLE FONDAMENTALI:
1. La motivazione deve essere COERENTE con il segnale gia' calcolato (mai contraddirlo).
2. Se un segnale e' CAMBIATO rispetto a ieri, spiega chiaramente quale condizione tecnica
   e' cambiata (es. il prezzo ha perso l'EMA50, l'RSI settimanale e' sceso sotto 50, ecc.).
3. Vai in profondita': cita trend di lungo periodo (EMA200), momentum multi-periodo, livelli.
4. Se un titolo e' uno strumento a leva (nome con 'Lev', '2x' o '3x'), ricorda SEMPRE il
   rischio di decay da leva giornaliera su orizzonti superiori a un giorno.
5. Integra la lettura delle CANDELE giapponesi (giornaliera e settimanale): se la candela
   conferma il trend/segnale rafforza la tesi; se lo contraddice (es. candela ribassista su
   trend rialzista), segnala il possibile avvertimento di breve periodo.

INDICI (variazione giornaliera):
{idx_txt}

TOP AZIONI (gia' filtrate per momentum):
{fmt(stocks)}

TOP ETF TEMATICI (gia' filtrati per momentum):
{fmt(etfs)}

PORTAFOGLIO DI STEFANO (con segnale gia' calcolato):
{port_txt}

Genera un JSON con questa struttura ESATTA (solo JSON, niente markdown):
{{
  "contesto_mercato": "3-4 frasi sul sentiment, sugli indici e sui settori piu' forti/deboli",
  "stocks_analysis": [
    {{"symbol": "TICKER", "motivazione": "2-3 righe professionali", "rating": "Forte"}}
  ],
  "etfs_analysis": [
    {{"symbol": "TICKER", "tema": "AI / Semiconduttori / ecc.", "motivazione": "2-3 righe", "rating": "Moderato"}}
  ],
  "portfolio_analysis": [
    {{"symbol": "TICKER", "motivazione": "3-4 righe: giustifica il segnale gia' calcolato, cita gli indicatori e, se cambiato, spiega perche'"}}
  ],
  "sintesi_portafoglio": "3-4 frasi di sintesi operativa complessiva, coerente con i segnali"
}}

Rating (solo per azioni/ETF): "Forte" o "Moderato".
NON includere il campo "segnale" nel portfolio_analysis: il segnale e' gia' deciso."""

    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=3500,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    return json.loads(text)


# ─── PDF ─────────────────────────────────────────────────────────────────────

BLUE = colors.HexColor("#1e3a5f")
LIGHT = colors.HexColor("#f0f4f8")
GREY = colors.HexColor("#cccccc")
GREEN = "#16a34a"
AMBER = "#d97706"
RED   = "#dc2626"

TABLE_STYLE = [
    ("BACKGROUND", (0, 0), (-1, 0), BLUE),
    ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
    ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE",   (0, 0), (-1, -1), 8),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT, colors.white]),
    ("GRID",       (0, 0), (-1, -1), 0.5, GREY),
    ("PADDING",    (0, 0), (-1, -1), 4),
    ("VALIGN",     (0, 0), (-1, -1), "TOP"),
]


def rating_para(rating: str, style) -> Paragraph:
    c = GREEN if rating == "Forte" else AMBER
    return Paragraph(f'<font color="{c}">● {rating}</font>', style)


def signal_para(segnale: str, style) -> Paragraph:
    c = GREEN if segnale == "Accumula" else (RED if segnale == "Riduci" else AMBER)
    return Paragraph(f'<font color="{c}">● {segnale}</font>', style)


def _dir_color(direction: str) -> str:
    if "Rial" in direction:
        return GREEN
    if "Rib" in direction:
        return RED
    return AMBER


def candle_para(cndl: dict, style) -> Paragraph:
    d = cndl or {}
    name = d.get("pattern", "-")
    direction = d.get("direction", "Neutro")
    meaning = d.get("meaning", "")
    col = _dir_color(direction)
    return Paragraph(
        f"<b>{name}</b><br/><font color='{col}'>{direction}</font>"
        f"<br/><font size='6.5' color='#555555'>{meaning}</font>",
        style,
    )


def pct(val) -> str:
    return f"{val:+.1f}%" if val is not None else "n.d."


def build_pdf(stocks, etfs, portfolio, indices, analysis, path):
    # Pagina ORIZZONTALE: serve spazio per le colonne delle candele
    doc = SimpleDocTemplate(path, pagesize=landscape(A4),
                            rightMargin=1.5*cm, leftMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)
    base = getSampleStyleSheet()
    title_s   = ParagraphStyle("T",  parent=base["Title"],   fontSize=18, textColor=BLUE, spaceAfter=4)
    sub_s     = ParagraphStyle("S",  parent=base["Normal"],  fontSize=10, textColor=colors.HexColor("#666666"), spaceAfter=20)
    h2_s      = ParagraphStyle("H2", parent=base["Heading2"],fontSize=13, textColor=BLUE, spaceBefore=16, spaceAfter=8)
    body_s    = ParagraphStyle("B",  parent=base["Normal"],  fontSize=9,  leading=14, spaceAfter=6)
    small_s   = ParagraphStyle("Sm", parent=base["Normal"],  fontSize=8,  leading=11)
    disc_s    = ParagraphStyle("D",  parent=base["Normal"],  fontSize=7.5,textColor=colors.HexColor("#888888"), leading=11)

    today_str = datetime.now().strftime("%d %B %Y")
    story = []

    # Header
    story += [
        Paragraph("Trading Report", title_s),
        Paragraph(f"{today_str} — Analisi Momentum Giornaliera", sub_s),
        HRFlowable(width="100%", thickness=2, color=BLUE),
        Spacer(1, 0.4*cm),
    ]

    # 1 – Contesto di Mercato
    story.append(Paragraph("Contesto di Mercato", h2_s))
    idx_rows = [["Indice", "Var. giornaliera"]]
    for name, val in indices.items():
        if val is not None:
            c = GREEN if val >= 0 else RED
            idx_rows.append([name, Paragraph(f'<font color="{c}">{val:+.2f}%</font>', small_s)])
        else:
            idx_rows.append([name, "n.d."])
    t = Table(idx_rows, colWidths=[8*cm, 5*cm])
    t.setStyle(TableStyle(TABLE_STYLE))
    story += [t, Spacer(1, 0.3*cm),
              Paragraph(analysis.get("contesto_mercato", ""), body_s)]

    # 2 – Top 10 Azioni
    story.append(Paragraph("Top 10 Azioni — Momentum", h2_s))
    sm = {a["symbol"]: a for a in analysis.get("stocks_analysis", [])}
    rows = [["#", "Ticker", "Prezzo", "RSI", "1M", "3M", "Rating", "Motivazione"]]
    for i, s in enumerate(stocks, 1):
        a = sm.get(s["symbol"], {})
        rows.append([str(i), s["symbol"], f"{s['price']:.2f}", str(s["rsi"] or "n.d."),
                     pct(s.get("perf_1m")), pct(s.get("perf_3m")),
                     rating_para(a.get("rating", "Moderato"), small_s),
                     Paragraph(a.get("motivazione", ""), small_s)])
    t = Table(rows, colWidths=[0.8*cm, 2.0*cm, 1.8*cm, 1.1*cm, 1.4*cm, 1.4*cm, 2.5*cm, 15.7*cm])
    t.setStyle(TableStyle(TABLE_STYLE))
    story.append(t)

    # 3 – Top 10 ETF
    story.append(Paragraph("Top 10 ETF Tematici — Momentum", h2_s))
    em = {a["symbol"]: a for a in analysis.get("etfs_analysis", [])}
    rows = [["#", "Ticker", "Tema", "Prezzo", "RSI", "1M", "3M", "Rating", "Motivazione"]]
    for i, s in enumerate(etfs, 1):
        a = em.get(s["symbol"], {})
        rows.append([str(i), s["symbol"], a.get("tema", "Tematico"),
                     f"{s['price']:.2f}", str(s["rsi"] or "n.d."),
                     pct(s.get("perf_1m")), pct(s.get("perf_3m")),
                     rating_para(a.get("rating", "Moderato"), small_s),
                     Paragraph(a.get("motivazione", ""), small_s)])
    t = Table(rows, colWidths=[0.7*cm, 1.8*cm, 2.8*cm, 1.6*cm, 1.0*cm, 1.3*cm, 1.3*cm, 2.4*cm, 13.8*cm])
    t.setStyle(TableStyle(TABLE_STYLE))
    story.append(t)

    # 4 – Portafoglio
    story.append(Paragraph("Portafoglio — Analisi Tecnica", h2_s))
    pm = {a["symbol"]: a for a in analysis.get("portfolio_analysis", [])}
    rows = [["Titolo", "Tipo", "Prezzo", "RSI", "Trend", "Segnale",
             "Candela Giorn.", "Candela Sett.", "Analisi"]]
    for p in portfolio:
        a = pm.get(p["symbol"], {})
        price = f"{p['price']:.2f}" if p.get("price") else "n.d."
        # Cella segnale: se cambiato rispetto a ieri, mostra il segnale precedente
        seg = p.get("segnale", "Mantieni")
        seg_cell = [signal_para(seg, small_s)]
        if p.get("changed") and p.get("prev_signal"):
            seg_cell.append(Paragraph(f"<font size='6' color='#888888'>(ieri: {p['prev_signal']})</font>", small_s))
        rows.append([
            Paragraph(f"<b>{p['name']}</b><br/><font size='7'>{p['symbol']}</font>", small_s),
            p.get("type", ""),
            price,
            str(p.get("rsi") or "n.d."),
            p.get("trend", "n.d."),
            seg_cell,
            candle_para(p.get("cndl_daily"), small_s),
            candle_para(p.get("cndl_weekly"), small_s),
            Paragraph(a.get("motivazione", ""), small_s),
        ])
    t = Table(rows, colWidths=[3.0*cm, 1.6*cm, 1.3*cm, 0.9*cm, 1.5*cm, 2.0*cm,
                               4.6*cm, 4.6*cm, 7.2*cm])
    t.setStyle(TableStyle(TABLE_STYLE))
    story += [t, Spacer(1, 0.3*cm),
              Paragraph(f"<b>Sintesi operativa:</b> {analysis.get('sintesi_portafoglio', '')}", body_s)]

    # Disclaimer
    story += [
        Spacer(1, 0.8*cm),
        HRFlowable(width="100%", thickness=0.5, color=GREY),
        Spacer(1, 0.2*cm),
        Paragraph(
            "Questo report è generato automaticamente a scopo informativo e non costituisce consulenza finanziaria. "
            "Le decisioni di investimento sono responsabilità esclusiva dell'investitore. "
            "I dati tecnici sono calcolati su prezzi storici di chiusura e potrebbero non riflettere le quotazioni in tempo reale.",
            disc_s
        ),
    ]

    doc.build(story)
    logger.info(f"PDF generato: {path}")


# ─── GOOGLE DRIVE ────────────────────────────────────────────────────────────

def get_drive_service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GDRIVE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GDRIVE_CLIENT_ID"],
        client_secret=os.environ["GDRIVE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    return build("drive", "v3", credentials=creds)


def load_previous_signals(service) -> dict:
    """Legge da Drive i segnali dell'ultimo run. Se non esiste, torna {} (primo run)."""
    try:
        res = service.files().list(
            q=f"name='{STATE_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed=false",
            spaces="drive", fields="files(id,name)", pageSize=1,
        ).execute()
        files = res.get("files", [])
        if not files:
            logger.info("Nessuno stato precedente su Drive (primo run o file assente).")
            return {}
        raw = service.files().get_media(fileId=files[0]["id"]).execute()
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        logger.info(f"Stato precedente caricato ({len(data)} posizioni).")
        return data
    except Exception as e:
        logger.warning(f"Impossibile leggere lo stato precedente: {e}")
        return {}


def save_signals(service, portfolio: list) -> None:
    """Salva su Drive i segnali di oggi, cosi' il prossimo run ha memoria."""
    today = datetime.now().strftime("%Y-%m-%d")
    state = {
        p["symbol"]: {"signal": p.get("segnale", "Mantieni"),
                      "score": p.get("score"),
                      "date": today}
        for p in portfolio
    }
    try:
        payload = json.dumps(state, indent=2, ensure_ascii=False).encode("utf-8")
        media = MediaIoBaseUpload(io.BytesIO(payload), mimetype="application/json")
        res = service.files().list(
            q=f"name='{STATE_FILENAME}' and '{GDRIVE_FOLDER_ID}' in parents and trashed=false",
            spaces="drive", fields="files(id)", pageSize=1,
        ).execute()
        files = res.get("files", [])
        if files:
            service.files().update(fileId=files[0]["id"], media_body=media).execute()
        else:
            service.files().create(
                body={"name": STATE_FILENAME, "parents": [GDRIVE_FOLDER_ID]},
                media_body=media,
            ).execute()
        logger.info("Stato segnali salvato su Drive.")
    except Exception as e:
        logger.warning(f"Impossibile salvare lo stato dei segnali: {e}")


def upload_to_drive(service, file_path: str, filename: str) -> str:
    file = service.files().create(
        body={"name": filename, "parents": [GDRIVE_FOLDER_ID]},
        media_body=MediaFileUpload(file_path, mimetype="application/pdf"),
        fields="id,webViewLink",
    ).execute()
    url = file.get("webViewLink", "")
    logger.info(f"Caricato su Drive: {url}")
    return url


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    output_path = f"/tmp/trading-report-{today}.pdf"

    logger.info("=== Trading Report Generator ===")
    indices   = get_index_data()
    stocks    = screen_universe(STOCK_UNIVERSE, "Stocks")
    etfs      = screen_universe(ETF_UNIVERSE, "ETFs")
    portfolio = get_portfolio_data()

    # Connessione a Drive + memoria del giorno prima → segnali stabili
    service = get_drive_service()
    prev_state = load_previous_signals(service)
    portfolio = apply_signals(portfolio, prev_state)

    logger.info("Generating analysis with Claude...")
    analysis = generate_analysis(stocks, etfs, portfolio, indices)

    logger.info("Building PDF...")
    build_pdf(stocks, etfs, portfolio, indices, analysis, output_path)

    logger.info("Uploading to Google Drive...")
    url = upload_to_drive(service, output_path, f"trading-report-{today}.pdf")

    # Salva i segnali di oggi per il run di domani
    save_signals(service, portfolio)

    print(f"\n✅ Report caricato su Google Drive!")
    print(f"🔗 {url}\n")


if __name__ == "__main__":
    main()
