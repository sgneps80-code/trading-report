#!/usr/bin/env python3
"""
Trading Report Generator — GitHub Pages Edition
Genera un report HTML giornaliero, lo cifra con Staticrypt e lo committa in docs/.
"""

import os
import json
import logging
from datetime import datetime
import pandas as pd
import yfinance as yf
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ─── CONFIGURAZIONE ───────────────────────────────────────────────────────────

# Il portafoglio è caricato da un GitHub Secret (PORTFOLIO_JSON) — non è nel codice.
# Formato del secret: JSON array, es:
# [{"symbol":"OMER.MI","name":"OMER","type":"Azione"}, ...]
PORTFOLIO = json.loads(os.environ.get("PORTFOLIO_JSON", "[]"))

STOCK_UNIVERSE_IT = [
    "ENI.MI", "ENEL.MI", "ISP.MI", "UCG.MI", "STM.MI", "RACE.MI",
    "BAMI.MI", "MB.MI", "LDO.MI", "PRY.MI", "SRG.MI", "TIT.MI",
    "A2A.MI", "CPR.MI", "PIRC.MI", "MONC.MI", "AMP.MI", "FCA.MI",
]

STOCK_UNIVERSE_US = [
    "NVDA", "AMD", "MSFT", "AAPL", "GOOGL", "META", "AMZN", "AVGO", "TSM", "QCOM",
    "CRM", "NOW", "PLTR", "PANW", "CRWD", "DDOG", "NET", "ARM", "MRVL",
    "JPM", "GS", "V", "MA", "COIN",
    "LLY", "ABBV", "UNH", "ISRG",
    "XOM", "CVX", "CAT", "RTX", "GE", "LMT",
    "TSLA", "COST", "ASML", "SAP",
]

ETF_UNIVERSE = [
    "QQQ", "VGT", "FTEC", "IGV", "ARKW",
    "SOXX", "SMH", "SOXQ",
    "BOTZ", "ROBO", "IRBO", "THNQ",
    "ICLN", "QCLN", "TAN",
    "XLV", "IBB", "ARKG", "XBI",
    "HACK", "BUG", "CIBR",
    "ITA", "XAR",
    "ARKK", "ARKF", "MOAT", "ARKQ",
]

# ─── ANALISI TECNICA ─────────────────────────────────────────────────────────

def calculate_rsi(prices: pd.Series, period: int = 14):
    if len(prices) < period + 1:
        return None
    delta = prices.diff().dropna()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    rs = gain.rolling(period).mean() / loss.rolling(period).mean().replace(0, float("inf"))
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1)

def ema(prices, period):
    if len(prices) < period:
        return None
    return float(prices.ewm(span=period, adjust=False).mean().iloc[-1])

def vol_ratio(volume, period=20):
    if len(volume) < period:
        return None
    avg = volume.rolling(period).mean().iloc[-1]
    return round(float(volume.iloc[-1] / avg), 2) if avg > 0 else None

def perf(prices, days):
    if len(prices) < days:
        return None
    return round(float((prices.iloc[-1] / prices.iloc[-days] - 1) * 100), 1)

def get_data(symbol, private=False):
    try:
        hist = yf.Ticker(symbol).history(period="6mo")
        if hist.empty or len(hist) < 60:
            return None
        c, v = hist["Close"], hist["Volume"]
        return {
            "symbol": symbol,
            "price": round(float(c.iloc[-1]), 2),
            "rsi": calculate_rsi(c),
            "ema20": ema(c, 20),
            "ema50": ema(c, 50),
            "vol_ratio": vol_ratio(v),
            "perf_1m": perf(c, 21),
            "perf_3m": perf(c, 63),
        }
    except Exception as e:
        # Non loggare il simbolo se è un titolo del portafoglio (privato)
        label = "[portfolio item]" if private else symbol
        logger.warning(f"Skip {label}: {type(e).__name__}")
        return None

def passes(d, min_price=1.0):
    if not d or d["price"] < min_price:
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

def score(d):
    return (
        (d["rsi"] - 50) * 0.5 +
        (d.get("perf_1m") or 0) * 0.3 +
        (d.get("perf_3m") or 0) * 0.2 +
        ((d["vol_ratio"] or 1) - 1) * 5
    )

def screen(universe, label, min_price=1.0):
    logger.info(f"Screening {label} ({len(universe)} candidati)...")
    results = [d for sym in universe if (d := get_data(sym)) and passes(d, min_price)]
    for d in results:
        d["score"] = score(d)
    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"{label}: {len(results)} passati → top {min(10, len(results))}")
    return results[:10]

def get_portfolio():
    out = []
    for item in PORTFOLIO:
        d = get_data(item["symbol"], private=True) or {}
        d.update({"name": item["name"], "type": item["type"], "symbol": item["symbol"]})
        if d.get("price") and d.get("ema20") and d.get("ema50"):
            if d["price"] > d["ema20"] and d["price"] > d["ema50"]:
                d["trend"] = "Rialzista"
            elif d["price"] < d["ema20"] and d["price"] < d["ema50"]:
                d["trend"] = "Ribassista"
            else:
                d["trend"] = "Laterale"
        else:
            d["trend"] = "n.d."
        out.append(d)
    return out

def get_indices():
    idxs = {"S&P 500": "^GSPC", "NASDAQ": "^IXIC", "Eurostoxx 50": "^STOXX50E", "FTSE MIB": "FTSEMIB.MI"}
    out = {}
    for name, sym in idxs.items():
        try:
            h = yf.Ticker(sym).history(period="5d")
            out[name] = round(float((h["Close"].iloc[-1] / h["Close"].iloc[-2] - 1) * 100), 2) if len(h) >= 2 else None
        except:
            out[name] = None
    return out

# ─── ANALISI CLAUDE ──────────────────────────────────────────────────────────

def generate_analysis(stocks_it, stocks_us, etfs, portfolio, indices):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def fmt(lst):
        return "\n".join(
            f"- {d['symbol']}: prezzo {d['price']}, RSI {d['rsi']}, 1M {d.get('perf_1m','n.d.')}%, 3M {d.get('perf_3m','n.d.')}%"
            for d in lst
        ) or "Nessun titolo ha superato il filtro oggi."

    port_txt = "\n".join(
        f"- {p['name']} ({p['symbol']}): prezzo {p.get('price','n.d.')}, RSI {p.get('rsi','n.d.')}, trend {p['trend']}, 1M {p.get('perf_1m','n.d.')}%"
        for p in portfolio
    )
    idx_txt = "\n".join(f"- {k}: {v:+.2f}%" if v else f"- {k}: n.d." for k, v in indices.items())

    prompt = f"""Sei un analista finanziario esperto. Data: {datetime.now().strftime('%d/%m/%Y')}.

INDICI:
{idx_txt}

TOP AZIONI ITALIANE (filtro momentum):
{fmt(stocks_it)}

TOP AZIONI USA (filtro momentum):
{fmt(stocks_us)}

TOP ETF TEMATICI (filtro momentum):
{fmt(etfs)}

PORTAFOGLIO STEFANO:
{port_txt}

Genera un JSON con questa struttura ESATTA (solo JSON puro, zero markdown):
{{
  "contesto_mercato": "2-3 frasi professionali su sentiment e indici",
  "stocks_it_analysis": [{{"symbol":"TICKER","motivazione":"2-3 righe","rating":"Forte"}}],
  "stocks_us_analysis": [{{"symbol":"TICKER","motivazione":"2-3 righe","rating":"Moderato"}}],
  "etfs_analysis": [{{"symbol":"TICKER","tema":"AI / Semiconduttori / ecc.","motivazione":"2-3 righe","rating":"Forte"}}],
  "portfolio_analysis": [{{"symbol":"TICKER","segnale":"Accumula","motivazione":"2-3 righe"}}],
  "sintesi_portafoglio": "2-3 frasi di sintesi operativa"
}}
Rating: Forte o Moderato. Segnale: Accumula, Mantieni o Riduci.
Per LBRT.MI menziona sempre il rischio decay da leva giornaliera."""

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

def stock_rows(lst, analysis_map):
    if not lst:
        return '<tr><td colspan="8" style="text-align:center;color:#999;padding:20px">Nessun titolo ha superato il filtro oggi</td></tr>'
    rows = ""
    for i, d in enumerate(lst, 1):
        a = analysis_map.get(d["symbol"], {})
        rows += f"""<tr>
            <td style="color:#999;font-size:12px">{i}</td>
            <td><strong>{d['symbol']}</strong></td>
            <td>{d['price']:.2f}</td>
            <td>{d['rsi'] or 'n.d.'}</td>
            <td>{pct(d.get('perf_1m'))}</td>
            <td>{pct(d.get('perf_3m'))}</td>
            <td>{rating_badge(a.get('rating','Moderato'))}</td>
            <td style="font-size:13px;color:#444">{a.get('motivazione','')}</td>
        </tr>"""
    return rows

def etf_rows(lst, analysis_map):
    if not lst:
        return '<tr><td colspan="9" style="text-align:center;color:#999;padding:20px">Nessun ETF ha superato il filtro oggi</td></tr>'
    rows = ""
    for i, d in enumerate(lst, 1):
        a = analysis_map.get(d["symbol"], {})
        rows += f"""<tr>
            <td style="color:#999;font-size:12px">{i}</td>
            <td><strong>{d['symbol']}</strong></td>
            <td style="color:#6366f1;font-size:13px">{a.get('tema','Tematico')}</td>
            <td>{d['price']:.2f}</td>
            <td>{d['rsi'] or 'n.d.'}</td>
            <td>{pct(d.get('perf_1m'))}</td>
            <td>{pct(d.get('perf_3m'))}</td>
            <td>{rating_badge(a.get('rating','Moderato'))}</td>
            <td style="font-size:13px;color:#444">{a.get('motivazione','')}</td>
        </tr>"""
    return rows

def portfolio_rows(portfolio, analysis_map):
    rows = ""
    for p in portfolio:
        a = analysis_map.get(p["symbol"], {})
        trend_color = {"Rialzista": "#16a34a", "Ribassista": "#dc2626", "Laterale": "#d97706"}.get(p["trend"], "#999")
        price_str = f"{p['price']:.2f}" if p.get("price") else "n.d."
        rows += f"""<tr>
            <td><strong>{p['name']}</strong><br><span style="color:#999;font-size:11px">{p['symbol']}</span></td>
            <td style="font-size:12px;color:#666">{p.get('type','')}</td>
            <td>{price_str}</td>
            <td>{p.get('rsi') or 'n.d.'}</td>
            <td style="color:{trend_color};font-weight:600">{p['trend']}</td>
            <td>{pct(p.get('perf_1m'))}</td>
            <td>{signal_badge(a.get('segnale','Mantieni'))}</td>
            <td style="font-size:13px;color:#444">{a.get('motivazione','')}</td>
        </tr>"""
    return rows

def build_html(stocks_it, stocks_us, etfs, portfolio, indices, analysis):
    today = datetime.now().strftime("%d %B %Y")
    generated = datetime.now().strftime("%d/%m/%Y %H:%M UTC")

    sm_it  = {a["symbol"]: a for a in analysis.get("stocks_it_analysis", [])}
    sm_us  = {a["symbol"]: a for a in analysis.get("stocks_us_analysis", [])}
    em     = {a["symbol"]: a for a in analysis.get("etfs_analysis", [])}
    pm     = {a["symbol"]: a for a in analysis.get("portfolio_analysis", [])}

    idx_html = "".join(
        f'<div class="idx-card"><div class="idx-name">{k}</div><div class="idx-val">{idx_badge(v)}</div></div>'
        for k, v in indices.items()
    )

    TABLE_HEAD = """<thead><tr style="background:#1e3a5f;color:white">"""
    TABLE_STYLE = """style="width:100%;border-collapse:collapse;font-size:14px;margin-top:12px" """

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
</style>
</head>
<body>

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
        <th>#</th><th>Ticker</th><th>Prezzo</th><th>RSI</th><th>1M</th><th>3M</th><th>Rating</th><th>Motivazione</th>
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
        <th>#</th><th>Ticker</th><th>Prezzo</th><th>RSI</th><th>1M</th><th>3M</th><th>Rating</th><th>Motivazione</th>
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
        <th>#</th><th>Ticker</th><th>Tema</th><th>Prezzo</th><th>RSI</th><th>1M</th><th>3M</th><th>Rating</th><th>Motivazione</th>
      </tr></thead>
      <tbody>{etf_rows(etfs, em)}</tbody>
    </table>
  </div>

  <!-- PORTAFOGLIO -->
  <div class="section">
    <h2>💼 Portafoglio — Analisi Tecnica</h2>
    <table>
      <thead><tr>
        <th>Titolo</th><th>Tipo</th><th>Prezzo</th><th>RSI</th><th>Trend</th><th>1M</th><th>Segnale</th><th>Analisi</th>
      </tr></thead>
      <tbody>{portfolio_rows(portfolio, pm)}</tbody>
    </table>
    <div class="sintesi"><strong>Sintesi operativa:</strong> {analysis.get('sintesi_portafoglio','')}</div>
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
</body>
</html>"""
    return html

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    logger.info("=== Trading Report Generator (GitHub Pages) ===")

    indices   = get_indices()
    stocks_it = screen(STOCK_UNIVERSE_IT, "Azioni IT", min_price=0.5)
    stocks_us = screen(STOCK_UNIVERSE_US, "Azioni US", min_price=5.0)
    etfs      = screen(ETF_UNIVERSE, "ETF", min_price=5.0)
    portfolio = get_portfolio()

    logger.info("Generating analysis with Claude...")
    analysis = generate_analysis(stocks_it, stocks_us, etfs, portfolio, indices)

    logger.info("Building HTML...")
    html = build_html(stocks_it, stocks_us, etfs, portfolio, indices, analysis)

    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("Saved to docs/index.html")

if __name__ == "__main__":
    main()
