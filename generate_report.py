#!/usr/bin/env python3
"""
Trading Report Generator
Genera ogni giorno un PDF con top 10 azioni, top 10 ETF tematici e analisi portafoglio,
poi lo carica su Google Drive nella cartella "Trading Reports".
"""

import os
import json
import logging
from datetime import datetime
import numpy as np
import pandas as pd
import yfinance as yf
import anthropic
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, HRFlowable
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import google.auth.transport.requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─── CONFIGURAZIONE ──────────────────────────────────────────────────────────

GDRIVE_FOLDER_ID = "1F7FL8HNG3Epr_hPJm8IvSTCTND4IGlNz"

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


def get_ticker_data(symbol: str) -> dict | None:
    try:
        hist = yf.Ticker(symbol).history(period="6mo")
        if hist.empty or len(hist) < 60:
            return None
        close, volume = hist["Close"], hist["Volume"]
        return {
            "symbol": symbol,
            "price": float(close.iloc[-1]),
            "rsi": calculate_rsi(close),
            "ema20": calculate_ema(close, 20),
            "ema50": calculate_ema(close, 50),
            "vol_ratio": volume_ratio(volume),
            "perf_1m": performance(close, 21),
            "perf_3m": performance(close, 63),
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

def generate_analysis(stocks: list, etfs: list, portfolio: list, indices: dict) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    today = datetime.now().strftime("%d/%m/%Y")

    def fmt(lst):
        return "\n".join(
            f"- {d['symbol']}: prezzo {d['price']:.2f}, RSI {d['rsi']}, 1M {d.get('perf_1m','n.d.')}%, 3M {d.get('perf_3m','n.d.')}%, vol_ratio {d.get('vol_ratio','n.d.')}"
            for d in lst
        )

    port_txt = "\n".join(
        f"- {p['name']} ({p['symbol']}): prezzo {p.get('price','n.d.')}, RSI {p.get('rsi','n.d.')}, trend {p['trend']}, 1M {p.get('perf_1m','n.d.')}%"
        for p in portfolio
    )
    idx_txt = "\n".join(f"- {k}: {v:+.2f}%" if v is not None else f"- {k}: n.d." for k, v in indices.items())

    prompt = f"""Sei un analista finanziario esperto. Data: {today}.

INDICI:
{idx_txt}

TOP AZIONI (filtro momentum applicato):
{fmt(stocks)}

TOP ETF TEMATICI (filtro momentum applicato):
{fmt(etfs)}

PORTAFOGLIO STEFANO:
{port_txt}

Genera un JSON con questa struttura ESATTA (solo JSON, niente markdown):
{{
  "contesto_mercato": "2-3 frasi sul sentiment e sugli indici",
  "stocks_analysis": [
    {{"symbol": "TICKER", "motivazione": "2-3 righe professionali", "rating": "Forte"}},
    ...
  ],
  "etfs_analysis": [
    {{"symbol": "TICKER", "tema": "AI / Semiconduttori / ecc.", "motivazione": "2-3 righe", "rating": "Moderato"}},
    ...
  ],
  "portfolio_analysis": [
    {{"symbol": "TICKER", "segnale": "Accumula", "motivazione": "2-3 righe"}},
    ...
  ],
  "sintesi_portafoglio": "2-3 frasi di sintesi operativa"
}}

Rating: "Forte" o "Moderato". Segnale: "Accumula", "Mantieni" o "Riduci".
Per LBRT.MI (ETC a leva 2x) menziona sempre il rischio decay da leva giornaliera."""

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
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


def pct(val) -> str:
    return f"{val:+.1f}%" if val is not None else "n.d."


def build_pdf(stocks, etfs, portfolio, indices, analysis, path):
    doc = SimpleDocTemplate(path, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
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
    t = Table(rows, colWidths=[0.6*cm, 1.8*cm, 1.5*cm, 1.0*cm, 1.2*cm, 1.2*cm, 2.0*cm, 7.5*cm])
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
    t = Table(rows, colWidths=[0.5*cm, 1.5*cm, 2.2*cm, 1.3*cm, 0.9*cm, 1.1*cm, 1.1*cm, 1.9*cm, 6.3*cm])
    t.setStyle(TableStyle(TABLE_STYLE))
    story.append(t)

    # 4 – Portafoglio
    story.append(Paragraph("Portafoglio — Analisi Tecnica", h2_s))
    pm = {a["symbol"]: a for a in analysis.get("portfolio_analysis", [])}
    rows = [["Titolo", "Tipo", "Prezzo", "RSI", "Trend", "1M", "Segnale", "Analisi"]]
    for p in portfolio:
        a = pm.get(p["symbol"], {})
        price = f"{p['price']:.2f}" if p.get("price") else "n.d."
        rows.append([
            Paragraph(f"<b>{p['name']}</b><br/><font size='7'>{p['symbol']}</font>", small_s),
            p.get("type", ""),
            price,
            str(p.get("rsi") or "n.d."),
            p.get("trend", "n.d."),
            pct(p.get("perf_1m")),
            signal_para(a.get("segnale", "Mantieni"), small_s),
            Paragraph(a.get("motivazione", ""), small_s),
        ])
    t = Table(rows, colWidths=[3.2*cm, 2.0*cm, 1.4*cm, 1.0*cm, 1.6*cm, 1.2*cm, 1.9*cm, 5.5*cm])
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

def upload_to_drive(file_path: str, filename: str) -> str:
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GDRIVE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GDRIVE_CLIENT_ID"],
        client_secret=os.environ["GDRIVE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    service = build("drive", "v3", credentials=creds)
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
    indices  = get_index_data()
    stocks   = screen_universe(STOCK_UNIVERSE, "Stocks")
    etfs     = screen_universe(ETF_UNIVERSE, "ETFs")
    portfolio = get_portfolio_data()

    logger.info("Generating analysis with Claude...")
    analysis = generate_analysis(stocks, etfs, portfolio, indices)

    logger.info("Building PDF...")
    build_pdf(stocks, etfs, portfolio, indices, analysis, output_path)

    logger.info("Uploading to Google Drive...")
    url = upload_to_drive(output_path, f"trading-report-{today}.pdf")

    print(f"\n✅ Report caricato su Google Drive!")
    print(f"🔗 {url}\n")


if __name__ == "__main__":
    main()
