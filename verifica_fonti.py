#!/usr/bin/env python3
"""
verifica_fonti.py — SOLO verifica delle fonti dati, non e' lo strumento finale.

Uso (Windows, PC di casa):
    py -m pip install yfinance tradingview-screener requests
    py verifica_fonti.py

Scrive il risultato in  %USERPROFILE%\\Downloads\\verifica_fonti_<data>.md
e lo stampa anche a video. Nessuna chiave, nessuna API a pagamento.
"""
import datetime as dt
import os
import sys
import traceback
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd
import requests
import yfinance as yf

ROMA = "Europe/Rome"

# simbolo Yahoo -> candidati TradingView (si prova il primo che risponde)
SIMBOLI = {
    "SAN.PA":     ["EURONEXT:SAN"],
    "SNY":        ["NASDAQ:SNY"],
    "OMER.MI":    ["MIL:OMER", "EURONEXT:OMER"],
    "SOM.MI":     ["MIL:SOM"],
    "ISP.MI":     ["MIL:ISP"],
    "GBSE.MI":    ["MIL:GBSE"],
    "XUSE.MI":    ["MIL:XUSE"],
    "REY.MI":     ["MIL:REY"],
    "ENI.MI":     ["MIL:ENI"],
    "EURUSD=X":   ["FX:EURUSD", "FX_IDC:EURUSD"],
    "GC=F":       ["COMEX:GC1!"],
    "XAUUSD=X":   ["OANDA:XAUUSD", "TVC:GOLD"],
    "FTSEMIB.MI": ["INDEX:FTSEMIB", "TVC:FTMIB", "MIL:FTSEMIB"],
    "^FCHI":      ["EURONEXT:PX1", "TVC:CAC40"],
}

CORS_ORIGIN = "https://sgneps80-code.github.io"
CORS_URLS = {
    "Yahoo chart (query1)": "https://query1.finance.yahoo.com/v8/finance/chart/ENI.MI?range=5d&interval=1d",
    "Yahoo chart (query2)": "https://query2.finance.yahoo.com/v8/finance/chart/ENI.MI?range=5d&interval=1d",
    "TradingView scanner":  "https://scanner.tradingview.com/global/scan",
    "GitHub API":           "https://api.github.com/repos/sgneps80-code/trading-report",
}

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) verifica-fonti"}

righe = []


def out(s=""):
    print(s, flush=True)
    righe.append(s)


def fmt_range(df):
    if df is None or df.empty:
        return "VUOTO"
    a = df.index[0].tz_convert(ROMA) if df.index.tz is not None else df.index[0]
    b = df.index[-1].tz_convert(ROMA) if df.index.tz is not None else df.index[-1]
    return f"{len(df)} barre, {a:%Y-%m-%d} → {b:%Y-%m-%d %H:%M}"


def verifica_yahoo():
    out("## 1. yfinance (auto_adjust=False)\n")
    out(f"yfinance {yf.__version__}\n")
    out("| Simbolo | Valuta / borsa | 1d (max) | 1wk (max) | 30m (60gg) | Volume=0 (1d) | Dividendi / split | Prossimi eventi |")
    out("|---|---|---|---|---|---|---|---|")
    campioni = {}
    for s in SIMBOLI:
        t = yf.Ticker(s)
        cell = {}
        try:
            d = t.history(period="max", interval="1d", auto_adjust=False, actions=True)
            cell["1d"] = fmt_range(d)
            cell["v0"] = f"{(d['Volume'] == 0).mean() * 100:.1f}%" if len(d) else "-"
            dv = int((d["Dividends"] > 0).sum()) if "Dividends" in d else 0
            sp = int((d["Stock Splits"] > 0).sum()) if "Stock Splits" in d else 0
            cell["act"] = f"{dv} / {sp}"
            campioni[s] = d
        except Exception as e:
            cell["1d"] = f"ERRORE {type(e).__name__}"
            cell["v0"] = cell["act"] = "-"
        try:
            w = t.history(period="max", interval="1wk", auto_adjust=False)
            cell["1wk"] = fmt_range(w)
        except Exception as e:
            cell["1wk"] = f"ERRORE {type(e).__name__}"
        try:
            m = t.history(period="60d", interval="30m", auto_adjust=False)
            n_sed = m.index.tz_convert(ROMA).normalize().nunique() if len(m) else 0
            cell["30m"] = fmt_range(m) + (f" ({n_sed} sedute)" if len(m) else "")
        except Exception as e:
            cell["30m"] = f"ERRORE {type(e).__name__}"
        try:
            fi = t.fast_info
            cell["ccy"] = f"{fi.get('currency')} / {fi.get('exchange')}"
        except Exception:
            cell["ccy"] = "non disponibile"
        try:
            cal = t.calendar or {}
            ev = []
            if cal.get("Earnings Date"):
                ev.append("conti " + ",".join(str(x) for x in cal["Earnings Date"]))
            if cal.get("Ex-Dividend Date"):
                ev.append(f"stacco {cal['Ex-Dividend Date']}")
            cell["cal"] = "; ".join(ev) or "nessuno"
        except Exception as e:
            cell["cal"] = f"ERRORE {type(e).__name__}"
        out(f"| {s} | {cell['ccy']} | {cell['1d']} | {cell['1wk']} | {cell['30m']} | {cell['v0']} | {cell['act']} | {cell['cal']} |")
    return campioni


def rma(x, n):
    return x.ewm(alpha=1 / n, adjust=False).mean()


def indicatori_locali(d):
    """RSI/ATR Wilder (RMA) come TradingView, SMA50, EMA20 — solo per il confronto."""
    c, h, l = d["Close"], d["High"], d["Low"]
    delta = c.diff()
    up, dn = delta.clip(lower=0), (-delta).clip(lower=0)
    # seed RMA = SMA dei primi n valori, come ta.rma di Pine
    def rma_pine(x, n):
        x = x.copy()
        out_ = pd.Series(index=x.index, dtype=float)
        vals = x.values
        prev = None
        for i in range(len(vals)):
            if i < n:
                if i == n - 1:
                    prev = pd.Series(vals[:n]).mean()
                    out_.iloc[i] = prev
                continue
            prev = (prev * (n - 1) + vals[i]) / n
            out_.iloc[i] = prev
        return out_
    rs = rma_pine(up.fillna(0), 14) / rma_pine(dn.fillna(0), 14)
    rsi = 100 - 100 / (1 + rs)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    tr.iloc[0] = h.iloc[0] - l.iloc[0]
    atr = rma_pine(tr, 14)
    return {
        "RSI": rsi.iloc[-1], "ATR": atr.iloc[-1],
        "SMA50": c.rolling(50).mean().iloc[-1], "EMA20": c.ewm(span=20, adjust=False).mean().iloc[-1],
        "close": c.iloc[-1], "data": d.index[-1],
    }


def verifica_tradingview(campioni):
    out("\n## 2. tradingview-screener (confronto incrociato)\n")
    try:
        from tradingview_screener import Query
        import tradingview_screener
        from importlib.metadata import version
        out(f"tradingview-screener {version('tradingview-screener')}\n")
    except Exception as e:
        out(f"Libreria non importabile: {e}")
        return
    cols = ["name", "close", "RSI", "ATR", "SMA50", "EMA20", "currency", "type", "exchange"]
    out("| Yahoo | Ticker TV | close TV | RSI TV | RSI locale | ATR TV | ATR locale | SMA50 TV | SMA50 locale | EMA20 TV | EMA20 locale |")
    out("|---|---|---|---|---|---|---|---|---|---|---|")
    for ysym, cands in SIMBOLI.items():
        trovato, errori = None, []
        for tv in cands:
            for tentativo in range(3):
                try:
                    n, df = Query().select(*cols).set_tickers(tv).get_scanner_data()
                    if n:
                        trovato = (tv, df.iloc[0])
                    else:
                        errori.append(f"{tv}: nessuna riga")
                    break
                except Exception as e:
                    errori.append(f"{tv}: {type(e).__name__} {str(e)[:60]}")
                    __import__("time").sleep(2 * (tentativo + 1))
            if trovato:
                break
        if not trovato:
            out(f"| {ysym} | non trovato ({'; '.join(errori)[:200]}) | | | | | | | | | |")
            continue
        tv, r = trovato
        loc = {}
        d = campioni.get(ysym)
        if d is not None and len(d) > 60:
            try:
                loc = indicatori_locali(d)
            except Exception:
                loc = {}
        f = lambda v: "-" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:.4f}"
        out(f"| {ysym} | {tv} | {f(r.get('close'))} | {f(r.get('RSI'))} | {f(loc.get('RSI'))} | "
            f"{f(r.get('ATR'))} | {f(loc.get('ATR'))} | {f(r.get('SMA50'))} | {f(loc.get('SMA50'))} | "
            f"{f(r.get('EMA20'))} | {f(loc.get('EMA20'))} |")
    out("\nNota: lo screener restituisce il valore sull'ultima barra di TradingView; "
        "a mercato aperto la barra Yahoo e quella TV possono differire per orario di aggiornamento.")


def verifica_cors():
    out("\n## 3. CORS (chiamata dal browser da una pagina su " + CORS_ORIGIN + ")\n")
    out("| Fonte | GET: Access-Control-Allow-Origin | Preflight OPTIONS: ACAO / metodi | Esito per il browser |")
    out("|---|---|---|---|")
    for nome, url in CORS_URLS.items():
        try:
            g = requests.get(url, headers={**UA, "Origin": CORS_ORIGIN}, timeout=15)
            acao = g.headers.get("Access-Control-Allow-Origin", "(assente)")
            st = g.status_code
        except Exception as e:
            acao, st = f"errore {type(e).__name__}", "-"
        try:
            p = requests.options(url, headers={**UA, "Origin": CORS_ORIGIN,
                                               "Access-Control-Request-Method": "POST",
                                               "Access-Control-Request-Headers": "content-type"}, timeout=15)
            pre = f"{p.status_code}: {p.headers.get('Access-Control-Allow-Origin', '(assente)')} / " \
                  f"{p.headers.get('Access-Control-Allow-Methods', '(assente)')}"
        except Exception as e:
            pre = f"errore {type(e).__name__}"
        ok = acao in ("*", CORS_ORIGIN)
        out(f"| {nome} | HTTP {st}, {acao} | {pre} | {'leggibile' if ok else 'BLOCCATO dal browser'} |")


def main():
    ora = dt.datetime.now(dt.timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo(ROMA))
    out(f"# Verifica fonti dati — {ora:%Y-%m-%d %H:%M} (Europe/Rome)\n")
    out(f"Python {sys.version.split()[0]}, pandas {pd.__version__}\n")
    campioni = {}
    for fn in (verifica_yahoo, verifica_tradingview, verifica_cors):
        try:
            r = fn() if fn is not verifica_tradingview else fn(campioni)
            if fn is verifica_yahoo:
                campioni = r or {}
        except Exception:
            out("```\n" + traceback.format_exc() + "```")
    dest = Path(os.environ.get("USERPROFILE", Path.home())) / "Downloads"
    dest.mkdir(exist_ok=True)
    f = dest / f"verifica_fonti_{ora:%Y-%m-%d_%H%M}.md"
    f.write_text("\n".join(righe), encoding="utf-8")
    print(f"\nSalvato in: {f}")


if __name__ == "__main__":
    main()
