"""Diagnostica una tantum: quali prefissi TradingView risolvono i simboli di prova."""
import json
import requests
from tradingview_screener import Query

H = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json",
     "Origin": "https://www.tradingview.com", "Referer": "https://www.tradingview.com/"}
cand = ["MIL:ISP", "EURONEXT:ISP", "NASDAQ:SNY", "NYSE:SNY", "MIL:XUSE", "EURONEXT:XUSE", "MIL:GBSE", "EURONEXT:GBSE",
        "FX:EURUSD", "FX_IDC:EURUSD", "OANDA:EURUSD", "COMEX:GC1!", "TVC:GOLD", "OANDA:XAUUSD",
        "INDEX:FTSEMIB", "TVC:FTMIB", "EURONEXT:FTSEMIB", "MIL:FTSEMIB", "EURONEXT:PX1", "TVC:CAC40", "INDEX:CAC40", "SP:SPX", "MIL:ENI"]
r = requests.post("https://scanner.tradingview.com/global/scan", headers=H,
                  json={"symbols": {"tickers": cand}, "columns": ["name", "close", "type", "RSI", "ATR"]}, timeout=20)
print("RAW", r.status_code, json.dumps(r.json().get("data"))[:3000])
q = Query().select("name", "close", "RSI").set_tickers(*cand)
print("LIB query", json.dumps(q.query)[:800])
n, df = q.get_scanner_data()
print("LIB", n, df.to_string()[:2000])
