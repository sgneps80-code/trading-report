#!/usr/bin/env python3
"""
Diagnostica ETF #3 — TER e AUM senza Morningstar

Verifica se Yahoo Finance espone i dati strutturali dei fondi (spese correnti,
masse gestite) per gli ETP quotati a Milano. Se risponde, evitiamo del tutto
la compilazione manuale della tabella costi.

Testa anche quali suffissi Yahoo risolvono per gli ETF italiani, visto che
CSPX.MI e IWDA.MI danno 404 mentre SWDA.MI funziona.

Uso:   python diagnose_etf3.py
"""

import json
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "application/json"}

# ETP di interesse: mix di azionari, obbligazionari e ETC su oro
TICKER = ["SWDA", "VWCE", "EIMI", "SGLD", "PHAU", "XEON",
          "CSPX", "IWDA", "AGGH", "VUAA", "SPPW", "MEUD"]

SUFFISSI = [".MI", ".DE", ".AS", ".L", ".SW", ".PA"]


def sezione(t):
    print(f"\n{'='*72}\n{t}\n{'='*72}")


# ── A. quoteSummary: TER e AUM disponibili? ─────────────────────────────────
def test_quotesummary():
    sezione("A. Yahoo quoteSummary — TER e AUM per gli ETP di Milano")
    moduli = "fundProfile,defaultKeyStatistics,summaryDetail,price"
    for t in TICKER:
        sym = f"{t}.MI"
        url = (f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{sym}"
               f"?modules={moduli}")
        try:
            r = requests.get(url, headers=H, timeout=15)
            if r.status_code != 200:
                print(f"  {sym:10} HTTP {r.status_code}")
                continue
            res = ((r.json().get("quoteSummary") or {}).get("result") or [])
            if not res:
                print(f"  {sym:10} nessun risultato")
                continue
            d = res[0]
            fp  = d.get("fundProfile") or {}
            dks = d.get("defaultKeyStatistics") or {}
            sd  = d.get("summaryDetail") or {}
            pr  = d.get("price") or {}

            fees = (fp.get("feesExpensesInvestment") or {})
            ter = (fees.get("annualReportExpenseRatio") or {}).get("raw")
            if ter is None:
                ter = (dks.get("annualReportExpenseRatio") or {}).get("raw")
            aum = (dks.get("totalAssets") or {}).get("raw") \
                  or (sd.get("totalAssets") or {}).get("raw")
            cat = fp.get("categoryName")
            fam = fp.get("family")

            print(f"  {sym:10} TER={ter}  AUM={aum}  cat={cat!r} fam={fam!r} "
                  f"nome={(pr.get('longName') or '')[:35]!r}")
        except Exception as e:
            print(f"  {sym:10} ECCEZIONE: {e}")


# ── B. Quale suffisso risolve per ciascun ticker? ───────────────────────────
def test_suffissi():
    sezione("B. Quale suffisso Yahoo risolve? (chart endpoint)")
    for t in TICKER:
        trovati = []
        for sfx in SUFFISSI:
            sym = t + sfx
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                   f"?range=5d&interval=1d")
            try:
                r = requests.get(url, headers=H, timeout=10)
                if r.status_code == 200:
                    res = (r.json().get("chart") or {}).get("result") or []
                    if res:
                        meta = res[0].get("meta") or {}
                        trovati.append(f"{sfx}({meta.get('currency')} "
                                       f"{meta.get('regularMarketPrice')})")
            except Exception:
                pass
        print(f"  {t:8} -> {', '.join(trovati) if trovati else 'NESSUN suffisso risolve'}")


# ── C. Storico sufficiente per gli indicatori? ──────────────────────────────
def test_storico():
    sezione("C. Storico giornaliero: bastano 200 barre per EMA200?")
    for t in ["SWDA", "VWCE", "SGLD", "XEON"]:
        sym = f"{t}.MI"
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
               f"?range=2y&interval=1d")
        try:
            r = requests.get(url, headers=H, timeout=20)
            if r.status_code != 200:
                print(f"  {sym:10} HTTP {r.status_code}")
                continue
            res = (r.json().get("chart") or {}).get("result") or []
            if not res:
                print(f"  {sym:10} nessun dato")
                continue
            q = ((res[0].get("indicators") or {}).get("quote") or [{}])[0]
            closes = [c for c in (q.get("close") or []) if c is not None]
            vols   = [v for v in (q.get("volume") or []) if v is not None]
            print(f"  {sym:10} barre={len(closes)}  "
                  f"{'OK per EMA200' if len(closes) >= 200 else 'INSUFFICIENTI'}  "
                  f"volumi presenti={len(vols)>0}")
        except Exception as e:
            print(f"  {sym:10} ECCEZIONE: {e}")


def main():
    print("DIAGNOSTICA ETF #3 — dati strutturali senza Morningstar")
    test_quotesummary()
    test_suffissi()
    test_storico()

    print(f"\n{'='*72}\nCOME LEGGERE I RISULTATI\n{'='*72}")
    print("""
  A  -> se TER e AUM tornano valorizzati, NON serve compilare a mano la tabella
        costi: possiamo tenere il punteggio costo/dimensione in automatico.
        Se tornano tutti None o HTTP 401/429, la tabella statica e' la via.

  B  -> dice per ogni ETF quale suffisso usare. Se un ticker risolve solo con
        .DE o .L, e' lo stesso ISIN quotato altrove: i prezzi in EUR restano
        confrontabili, cambia solo la sede di negoziazione.

  C  -> conferma che c'e' storico sufficiente per calcolare EMA200 in locale
        (servono almeno 200 sedute) e se i volumi sono disponibili per il
        filtro di liquidita'.
""")


if __name__ == "__main__":
    main()
