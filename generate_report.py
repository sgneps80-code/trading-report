#!/usr/bin/env python3
"""
Trading Report Generator — GitHub Pages Edition
Genera un report HTML giornaliero, lo cifra con Staticrypt e lo committa in docs/.
"""

import os
import json
import hashlib
import logging
from datetime import datetime
import pandas as pd
import yfinance as yf
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Silenzia i log interni di yfinance (es. "possibly delisted", "no price data")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("peewee").setLevel(logging.CRITICAL)

# ─── CONFIGURAZIONE ───────────────────────────────────────────────────────────

# Il portafoglio è caricato da un GitHub Secret (PORTFOLIO_JSON) — non è nel codice.
# Formato del secret: JSON array, es:
# [{"symbol":"OMER.MI","name":"OMER","type":"Azione"}, ...]
PORTFOLIO = json.loads(os.environ.get("PORTFOLIO_JSON", "[]"))

STOCK_UNIVERSE_IT = [
    # FTSE MIB — simboli Yahoo Finance verificati (formato TICKER.MI)
    "ENI.MI",    # Eni
    "ENEL.MI",   # Enel
    "ISP.MI",    # Intesa Sanpaolo
    "UCG.MI",    # UniCredit
    "G.MI",      # Generali
    "STM.MI",    # STMicroelectronics
    "RACE.MI",   # Ferrari
    "STLAM.MI",  # Stellantis
    "MB.MI",     # Mediobanca
    "BAMI.MI",   # Banco BPM
    "LDO.MI",    # Leonardo
    "PRY.MI",    # Prysmian
    "MONC.MI",   # Moncler
    "NEXI.MI",   # Nexi
    "AMP.MI",    # Amplifon
    "FBK.MI",    # FinecoBank
    "TRN.MI",    # Terna
    "SRG.MI",    # Snam
    "A2A.MI",    # A2A
    "INW.MI",    # Inwit
    "CPR.MI",    # Campari
    "PIRC.MI",   # Pirelli
    "REC.MI",    # Recordati
    "EXO.MI",    # Exor
    "SPM.MI",    # Saipem
    "ERG.MI",    # ERG
    "DIA.MI",    # DiaSorin
    "BMPS.MI",   # Banca Monte dei Paschi
    "TIT.MI",    # Telecom Italia
    "AZM.MI",    # Azimut
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

def calculate_rsi_series(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff().dropna()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    rs = gain.rolling(period).mean() / loss.rolling(period).mean().replace(0, float("inf"))
    return 100 - (100 / (1 + rs))

def ema(prices, period):
    if len(prices) < period:
        return None
    return float(prices.ewm(span=period, adjust=False).mean().iloc[-1])

def ema_series(prices, period):
    return prices.ewm(span=period, adjust=False).mean()

def vol_ratio(volume, period=20):
    if len(volume) < period:
        return None
    avg = volume.rolling(period).mean().iloc[-1]
    return round(float(volume.iloc[-1] / avg), 2) if avg > 0 else None

def perf(prices, days):
    if len(prices) < days:
        return None
    return round(float((prices.iloc[-1] / prices.iloc[-days] - 1) * 100), 1)

def detect_candle(o, h, l, c):
    """Rileva il pattern candela giapponese sull'ultima barra."""
    try:
        lo, lh, ll, lc = float(o.iloc[-1]), float(h.iloc[-1]), float(l.iloc[-1]), float(c.iloc[-1])
        rng = lh - ll
        if rng < 1e-9:
            return "—"
        body = abs(lc - lo)
        upper = lh - max(lc, lo)
        lower = min(lc, lo) - ll
        body_r = body / rng

        if body_r < 0.1:
            return "Doji"
        if lower > 2 * body and upper < body * 0.5 and lc > lo:
            return "Hammer ▲"
        if lower > 2 * body and upper < body * 0.5 and lc < lo:
            return "Hanging Man ▼"
        if upper > 2 * body and lower < body * 0.5 and lc < lo:
            return "Shooting Star ▼"
        if upper > 2 * body and lower < body * 0.5 and lc > lo:
            return "Inv. Hammer ▲"
        # Engulfing (confronta con candela precedente)
        po, pc = float(o.iloc[-2]), float(c.iloc[-2])
        if lc > lo and lc > pc and lo < po:
            return "Bullish Engulfing ▲"
        if lc < lo and lc < pc and lo > po:
            return "Bearish Engulfing ▼"
        if lc > lo and body_r > 0.6:
            return "Bullish"
        if lc < lo and body_r > 0.6:
            return "Bearish"
        return "Neutro"
    except:
        return "—"

def get_data(symbol, private=False):
    try:
        hist = yf.Ticker(symbol).history(period="6mo")
        if hist.empty or len(hist) < 60:
            return None
        o, h, l, c, v = hist["Open"], hist["High"], hist["Low"], hist["Close"], hist["Volume"]

        # RSI serie completa
        rsi_series = calculate_rsi_series(c)
        rsi_now = round(float(rsi_series.iloc[-1]), 1)
        rsi_last5 = [round(float(x), 1) for x in rsi_series.iloc[-5:] if not pd.isna(x)]

        # EMA serie per stabilità
        ema20_s = ema_series(c, 20)
        ema50_s = ema_series(c, 50)

        # Candela giornaliera
        candle_d = detect_candle(o, h, l, c)

        # Candela settimanale (resample)
        weekly = hist.resample("W").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
        candle_w = detect_candle(weekly["Open"], weekly["High"], weekly["Low"], weekly["Close"]) if len(weekly) >= 2 else "—"

        return {
            "symbol": symbol,
            "price": round(float(c.iloc[-1]), 2),
            "rsi": rsi_now,
            "rsi_last5": rsi_last5,
            "ema20": float(ema20_s.iloc[-1]),
            "ema20_last3": list(ema20_s.iloc[-3:].values),
            "ema50": float(ema50_s.iloc[-1]),
            "ema50_last3": list(ema50_s.iloc[-3:].values),
            "close_last3": list(c.iloc[-3:].values),
            "vol_ratio": vol_ratio(v),
            "perf_1m": perf(c, 21),
            "perf_3m": perf(c, 63),
            "candle_d": candle_d,
            "candle_w": candle_w,
        }
    except Exception as e:
        label = "[portfolio item]" if private else symbol
        logger.warning(f"Skip {label}: {type(e).__name__}")
        return None

def passes(d, min_price=1.0):
    """Filtro stabile: il titolo deve rispettare i criteri per almeno 3 giorni consecutivi."""
    if not d or d["price"] < min_price:
        return False

    # RSI: deve essere in [50,75] negli ultimi 3 giorni (stabilità segnale)
    rsi5 = d.get("rsi_last5", [])
    if len(rsi5) < 3 or sum(1 for r in rsi5[-3:] if 50 <= r <= 75) < 3:
        return False

    # Prezzo > EMA20 negli ultimi 3 giorni
    closes = d.get("close_last3", [])
    ema20s = d.get("ema20_last3", [])
    if len(closes) < 3 or len(ema20s) < 3:
        return False
    if not all(c > e for c, e in zip(closes, ema20s)):
        return False

    # Prezzo > EMA50 oggi
    if d["price"] < d["ema50"]:
        return False

    # Volume in crescita
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

def candle_badge(pattern):
    """Colore badge candela in base al tipo."""
    if not pattern or pattern == "—":
        return '<span style="color:#999">—</span>'
    if any(x in pattern for x in ["Bullish", "Hammer ▲", "Inv. Hammer ▲", "Engulfing ▲"]):
        return f'<span style="color:#16a34a;font-size:12px">{pattern}</span>'
    if any(x in pattern for x in ["Bearish", "Shooting Star", "Hanging Man", "Engulfing ▼"]):
        return f'<span style="color:#dc2626;font-size:12px">{pattern}</span>'
    return f'<span style="color:#888;font-size:12px">{pattern}</span>'

def stock_rows(lst, analysis_map):
    if not lst:
        return '<tr><td colspan="10" style="text-align:center;color:#999;padding:20px">Nessun titolo ha superato il filtro oggi (segnale stabile richiesto per 3 giorni consecutivi)</td></tr>'
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
            <td>{candle_badge(d.get('candle_d','—'))}</td>
            <td>{candle_badge(d.get('candle_w','—'))}</td>
            <td>{rating_badge(a.get('rating','Moderato'))}</td>
            <td style="font-size:13px;color:#444">{a.get('motivazione','')}</td>
        </tr>"""
    return rows

def etf_rows(lst, analysis_map):
    if not lst:
        return '<tr><td colspan="11" style="text-align:center;color:#999;padding:20px">Nessun ETF ha superato il filtro oggi</td></tr>'
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
            <td>{candle_badge(d.get('candle_d','—'))}</td>
            <td>{candle_badge(d.get('candle_w','—'))}</td>
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

def build_html(stocks_it, stocks_us, etfs, portfolio, indices, analysis, password_hash="", portfolio_base="[]"):
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
    editorPortfolio = saved ? JSON.parse(saved) : JSON.parse(JSON.stringify(PORTFOLIO_BASE));
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
    document.getElementById("editor-tbody").innerHTML = editorPortfolio.map((item, i) => `
      <tr style="border-bottom:1px solid #e2e8f0">
        <td style="padding:8px 4px">
          <input value="${{item.symbol}}" onchange="updateItem(${{i}},'symbol',this.value.toUpperCase().trim())"
            style="width:100px;padding:6px;border:1px solid #ddd;border-radius:4px;font-size:13px;font-family:monospace">
        </td>
        <td style="padding:8px 4px">
          <input value="${{item.name}}" onchange="updateItem(${{i}},'name',this.value)"
            style="width:170px;padding:6px;border:1px solid #ddd;border-radius:4px;font-size:13px">
        </td>
        <td style="padding:8px 4px">
          <select onchange="updateItem(${{i}},'type',this.value)"
            style="padding:6px;border:1px solid #ddd;border-radius:4px;font-size:13px">
            <option ${{item.type==='Azione'?'selected':''}}>Azione</option>
            <option ${{item.type==='ETF'?'selected':''}}>ETF</option>
            <option ${{item.type==='Leveraged ETF'?'selected':''}}>Leveraged ETF</option>
            <option ${{item.type==='ETF Commodity'?'selected':''}}>ETF Commodity</option>
          </select>
        </td>
        <td style="padding:8px 4px;text-align:center">
          <button onclick="removeItem(${{i}})" title="Rimuovi"
            style="color:#dc2626;background:none;border:none;cursor:pointer;font-size:20px;line-height:1;padding:2px">×</button>
        </td>
      </tr>`).join("");
  }}

  function updateItem(i, field, value) {{
    editorPortfolio[i][field] = value;
    localStorage.setItem("editor_portfolio", JSON.stringify(editorPortfolio));
  }}

  function removeItem(i) {{
    editorPortfolio.splice(i, 1);
    localStorage.setItem("editor_portfolio", JSON.stringify(editorPortfolio));
    renderEditorTable();
  }}

  function addEditorRow() {{
    editorPortfolio.push({{symbol:"",name:"",type:"Azione"}});
    renderEditorTable();
    setTimeout(() => {{
      const inputs = document.querySelectorAll("#editor-tbody input");
      if (inputs.length >= 2) inputs[inputs.length - 2].focus();
    }}, 50);
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
      setStatus("⏳ Connessione a GitHub...", "#d97706");
      const keyR = await fetch(`https://api.github.com/repos/${{owner}}/${{repo}}/actions/secrets/public-key`, {{
        headers: {{"Authorization":`Bearer ${{token}}`,"Accept":"application/vnd.github+json"}}
      }});
      if (!keyR.ok) throw new Error(`Errore chiave pubblica: HTTP ${{keyR.status}}`);
      const {{key_id, key}} = await keyR.json();

      setStatus("⏳ Cifratura portafoglio...", "#d97706");
      await sodium.ready;
      const pubKey    = sodium.from_base64(key, sodium.base64_variants.ORIGINAL);
      const plaintext = sodium.from_string(JSON.stringify(valid));
      const encrypted = sodium.crypto_box_seal(plaintext, pubKey);
      const encB64    = sodium.to_base64(encrypted, sodium.base64_variants.ORIGINAL);

      setStatus("⏳ Aggiornamento secret GitHub...", "#d97706");
      const secR = await fetch(`https://api.github.com/repos/${{owner}}/${{repo}}/actions/secrets/PORTFOLIO_JSON`, {{
        method:"PUT",
        headers:{{"Authorization":`Bearer ${{token}}`,"Accept":"application/vnd.github+json","Content-Type":"application/json"}},
        body:JSON.stringify({{encrypted_value:encB64,key_id}})
      }});
      if (secR.status !== 201 && secR.status !== 204) throw new Error(`Errore update secret: HTTP ${{secR.status}}`);

      setStatus("⏳ Avvio generazione report...", "#d97706");
      const wfR = await fetch(`https://api.github.com/repos/${{owner}}/${{repo}}/actions/workflows/trading_report.yml/dispatches`, {{
        method:"POST",
        headers:{{"Authorization":`Bearer ${{token}}`,"Accept":"application/vnd.github+json","Content-Type":"application/json"}},
        body:JSON.stringify({{ref:"main"}})
      }});
      if (wfR.status !== 204) throw new Error(`Errore avvio workflow: HTTP ${{wfR.status}}`);

      localStorage.setItem("editor_portfolio", JSON.stringify(valid));
      editorPortfolio = valid;
      renderEditorTable();
      setStatus("✅ Report avviato! Pronto in ~3-5 minuti. Aggiorna la pagina (F5) per vederlo.", "#16a34a");
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
<script src="https://cdn.jsdelivr.net/npm/libsodium-wrappers@0.7.13/dist/browsers/sodium.js"></script>
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
        <th>#</th><th>Ticker</th><th>Prezzo</th><th>RSI</th><th>1M</th><th>3M</th><th>Candela 1D</th><th>Candela 1W</th><th>Rating</th><th>Motivazione</th>
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
        <th>#</th><th>Ticker</th><th>Prezzo</th><th>RSI</th><th>1M</th><th>3M</th><th>Candela 1D</th><th>Candela 1W</th><th>Rating</th><th>Motivazione</th>
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
        <th>#</th><th>Ticker</th><th>Tema</th><th>Prezzo</th><th>RSI</th><th>1M</th><th>3M</th><th>Candela 1D</th><th>Candela 1W</th><th>Rating</th><th>Motivazione</th>
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
    <table style="width:100%;border-collapse:collapse;margin-bottom:12px">
      <thead>
        <tr style="background:#1e3a5f;color:white">
          <th style="padding:10px;text-align:left;font-size:12px">Simbolo Yahoo Finance</th>
          <th style="padding:10px;text-align:left;font-size:12px">Nome</th>
          <th style="padding:10px;text-align:left;font-size:12px">Tipo</th>
          <th style="padding:10px;width:36px"></th>
        </tr>
      </thead>
      <tbody id="editor-tbody"></tbody>
    </table>
    <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:8px">
      <button onclick="addEditorRow()"
        style="background:#e2e8f0;color:#1e3a5f;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:14px">
        + Aggiungi titolo
      </button>
      <button onclick="triggerReport(this)"
        style="background:#16a34a;color:white;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;font-size:14px;font-weight:600">
        🚀 Aggiorna Report
      </button>
      <span id="editor-status" style="font-size:13px"></span>
    </div>
    <p style="font-size:11px;color:#999;margin-top:10px">Il portafoglio viene cifrato e salvato come secret GitHub — non è visibile nel repository.</p>
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
    stocks_it = screen(STOCK_UNIVERSE_IT, "Azioni IT", min_price=0.5)
    stocks_us = screen(STOCK_UNIVERSE_US, "Azioni US", min_price=5.0)
    etfs      = screen(ETF_UNIVERSE, "ETF", min_price=5.0)
    portfolio = get_portfolio()

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
