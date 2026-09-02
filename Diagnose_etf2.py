#!/usr/bin/env python3
"""
Diagnostica ETF #2 — DOVE sono gli ETF italiani su TradingView?

Il test precedente ha dimostrato che il mercato "italy" dello screener contiene
solo 7 fondi (1 fondo comune + 6 fondi chiusi), nessun ETF di ETFplus, e che i
simboli tipo MIL:SWDA non risolvono.

Questo script cerca il bacino corretto provando: ricerca simboli, prefissi
exchange alternativi, mercati diversi e varianti di endpoint.

Uso:   python diagnose_etf2.py
"""

import json
from collections import Counter
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

TV_HEADERS = {
    "User-Agent": UA,
    "Content-Type": "application/json",
    "Referer": "https://www.tradingview.com/",
    "Origin": "https://www.tradingview.com",
}

COLS = ["name", "description", "close", "type", "typespecs",
        "average_volume_10d_calc", "exchange"]

ETF_NOTI = ["SWDA", "CSPX", "VWCE", "EIMI", "SGLD", "PHAU", "IWDA", "XEON"]


def sezione(titolo):
    print(f"\n{'='*72}\n{titolo}\n{'='*72}")


# ── A. Ricerca simboli: dove vive SWDA secondo TradingView? ──────────────────
def test_symbol_search():
    sezione("A. Symbol search — con quale exchange TradingView indicizza gli ETF noti?")
    for q in ETF_NOTI:
        url = ("https://symbol-search.tradingview.com/symbol_search/v3/"
               f"?text={q}&hl=0&lang=en&domain=production")
        try:
            r = requests.get(url, headers={"User-Agent": UA,
                                           "Referer": "https://www.tradingview.com/"},
                             timeout=15)
            if r.status_code != 200:
                print(f"  {q:8} HTTP {r.status_code}")
                continue
            syms = (r.json() or {}).get("symbols") or []
            if not syms:
                print(f"  {q:8} nessun risultato")
                continue
            print(f"  {q}:")
            for s in syms[:5]:
                ex = s.get("exchange") or s.get("listed_exchange") or "?"
                print(f"      {ex:12} {s.get('symbol','?'):10} "
                      f"type={s.get('type')!r:12} "
                      f"desc={(s.get('description') or '')[:45]}")
        except Exception as e:
            print(f"  {q:8} ECCEZIONE: {e}")


# ── B. Prefissi exchange alternativi sui simboli noti ────────────────────────
def test_prefissi():
    sezione("B. Quale prefisso exchange risolve? (scan per tickers)")
    prefissi = ["MIL", "BVME", "BIT", "XMIL", "EURONEXT", "ETFPLUS",
                "MILSEDEX", "EUROTLX", "XETR", "LSE"]
    for pre in prefissi:
        tickers = [f"{pre}:{t}" for t in ETF_NOTI]
        try:
            r = requests.post("https://scanner.tradingview.com/global/scan",
                              json={"symbols": {"tickers": tickers}, "columns": COLS},
                              headers=TV_HEADERS, timeout=20)
            rows = (r.json().get("data") or []) if r.status_code == 200 else []
            esito = f"{len(rows)} risolti" if rows else "0"
            print(f"  {pre:10} HTTP {r.status_code}  -> {esito}")
            for row in rows[:4]:
                d = dict(zip(COLS, row.get("d", [])))
                print(f"      {row.get('s'):18} close={d.get('close')} "
                      f"type={d.get('type')} specs={d.get('typespecs')}")
        except Exception as e:
            print(f"  {pre:10} ECCEZIONE: {e}")


# ── C. Composizione del mercato italy senza filtro di tipo ───────────────────
def test_universo_italy():
    sezione("C. Mercato 'italy' SENZA filtro tipo — cosa contiene davvero?")
    payload = {
        "filter": [],
        "options": {"lang": "en"},
        "markets": ["italy"],
        "columns": COLS,
        "sort": {"sortBy": "name", "sortOrder": "asc"},
        "range": [0, 1000],
    }
    try:
        r = requests.post("https://scanner.tradingview.com/italy/scan",
                          json=payload, headers=TV_HEADERS, timeout=25)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code}: {r.text[:200]}")
            return
        data = r.json()
        rows = data.get("data") or []
        print(f"  totalCount={data.get('totalCount')}  righe={len(rows)}")
        tipi = Counter()
        exch = Counter()
        for row in rows:
            d = dict(zip(COLS, row.get("d", [])))
            tipi[(d.get("type"), json.dumps(d.get("typespecs")))] += 1
            exch[row.get("s", "").split(":")[0]] += 1
        print("\n  Distribuzione type/typespecs:")
        for (t, ts), n in tipi.most_common(20):
            print(f"      {n:5}x  type={t!r:12} typespecs={ts}")
        print("\n  Distribuzione exchange:")
        for e, n in exch.most_common(10):
            print(f"      {n:5}x  {e}")
    except Exception as e:
        print(f"  ECCEZIONE: {e}")


# ── D. Altri mercati: dove ci sono ETF in quantita'? ─────────────────────────
def test_altri_mercati():
    sezione("D. Conteggio ETF per mercato (dove esiste un bacino vero?)")
    mercati = ["italy", "germany", "uk", "france", "netherlands",
               "switzerland", "spain", "america"]
    for mkt in mercati:
        payload = {
            "filter": [],
            "options": {"lang": "en"},
            "markets": [mkt],
            "symbols": {"query": {"types": ["fund"]}, "tickers": []},
            "columns": ["name", "type", "typespecs"],
            "range": [0, 5],
        }
        try:
            r = requests.post(f"https://scanner.tradingview.com/{mkt}/scan",
                              json=payload, headers=TV_HEADERS, timeout=20)
            if r.status_code != 200:
                print(f"  {mkt:14} HTTP {r.status_code}")
                continue
            data = r.json()
            rows = data.get("data") or []
            esempi = ", ".join(r_.get("s", "").split(":")[-1] for r_ in rows[:4])
            print(f"  {mkt:14} totalCount={str(data.get('totalCount')):6} "
                  f"esempi: {esempi}")
        except Exception as e:
            print(f"  {mkt:14} ECCEZIONE: {e}")


# ── E. Varianti di endpoint (label-product) ──────────────────────────────────
def test_label_product():
    sezione("E. Varianti endpoint: parametro label-product")
    varianti = [
        "https://scanner.tradingview.com/italy/scan",
        "https://scanner.tradingview.com/italy/scan?label-product=screener-etf",
        "https://scanner.tradingview.com/italy/scan?label-product=screener-stock",
        "https://scanner.tradingview.com/global/scan?label-product=screener-etf",
    ]
    payload = {
        "filter": [],
        "options": {"lang": "en"},
        "markets": ["italy"],
        "symbols": {"query": {"types": ["fund"]}, "tickers": []},
        "columns": ["name", "type", "typespecs"],
        "range": [0, 5],
    }
    for url in varianti:
        try:
            r = requests.post(url, json=payload, headers=TV_HEADERS, timeout=20)
            if r.status_code != 200:
                print(f"  HTTP {r.status_code}  {url}")
                continue
            data = r.json()
            print(f"  totalCount={str(data.get('totalCount')):6}  {url}")
        except Exception as e:
            print(f"  ECCEZIONE {e}  {url}")


# ── F. Fallback indipendente: Yahoo Finance risolve i .MI? ───────────────────
def test_yahoo():
    sezione("F. Fallback Yahoo Finance — i ticker .MI rispondono?")
    for t in ETF_NOTI:
        ysym = f"{t}.MI"
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}"
               f"?range=5d&interval=1d")
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
            if r.status_code != 200:
                print(f"  {ysym:10} HTTP {r.status_code}")
                continue
            res = (r.json().get("chart") or {}).get("result") or []
            if not res:
                print(f"  {ysym:10} nessun dato")
                continue
            meta = res[0].get("meta") or {}
            closes = ((res[0].get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
            validi = [c for c in closes if c is not None]
            print(f"  {ysym:10} OK  prezzo={meta.get('regularMarketPrice')} "
                  f"valuta={meta.get('currency')} barre5g={len(validi)}")
        except Exception as e:
            print(f"  {ysym:10} ECCEZIONE: {e}")


def main():
    print("DIAGNOSTICA ETF #2 — localizzazione del bacino ETF italiano")
    test_symbol_search()
    test_prefissi()
    test_universo_italy()
    test_altri_mercati()
    test_label_product()
    test_yahoo()

    print(f"\n{'='*72}\nCOME LEGGERE I RISULTATI\n{'='*72}")
    print("""
  A  -> mostra il prefisso exchange REALE con cui TradingView indicizza SWDA
        e simili. E' l'informazione piu' importante: da li' si ricava il
        'markets' o il set di tickers corretto da usare nel report.

  B  -> se un prefisso risolve (>0 righe), quello e' il formato simbolo giusto
        e possiamo interrogare gli ETF per lista esplicita di tickers.

  C  -> se il mercato 'italy' contiene SOLO stock + i 7 fondi, e' confermato
        che gli ETF italiani non sono nello screener per mercato: va usata
        la query per tickers (B) o un'altra fonte (F).

  D  -> se 'germany' o 'uk' hanno migliaia di fund, il bacino europeo esiste
        ma sotto altri mercati: molti ETF che compri a Milano sono gli stessi
        ISIN quotati anche a Xetra/LSE.

  E  -> se una variante di endpoint sblocca un totalCount alto, e' quella la
        strada corretta.

  F  -> se Yahoo risponde sui .MI, abbiamo comunque una fonte affidabile per
        prezzi e storico degli ETF di Borsa Italiana, indipendente da TV.
""")


if __name__ == "__main__":
    main()
