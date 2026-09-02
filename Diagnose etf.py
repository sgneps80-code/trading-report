#!/usr/bin/env python3
"""
Diagnostica ETF/ETN/ETC — TradingView
Esegue una serie di test a strati per capire ESATTAMENTE dove si perde la lista.

Uso:   python diagnose_etf.py
Serve solo la libreria requests:  pip install requests
"""

import json
import requests

TV_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Referer": "https://www.tradingview.com/",
    "Origin": "https://www.tradingview.com",
}

URL_ITALY  = "https://scanner.tradingview.com/italy/scan"
URL_GLOBAL = "https://scanner.tradingview.com/global/scan"

BASE_COLS = ["name", "description", "close", "RSI", "EMA50", "EMA200",
             "MACD.hist", "change|1M", "change|3M",
             "average_volume_10d_calc", "type", "typespecs"]

FUND_COLS = ["expense_ratio", "aum"]


def call(url, payload, label):
    """Esegue una chiamata e riporta status, conteggio e primo record."""
    print(f"\n{'='*70}\nTEST: {label}\n{'='*70}")
    try:
        r = requests.post(url, json=payload, headers=TV_HEADERS, timeout=25)
    except Exception as e:
        print(f"  ECCEZIONE di rete: {e}")
        return None
    print(f"  HTTP status : {r.status_code}")
    if r.status_code != 200:
        print(f"  Corpo errore: {r.text[:400]}")
        return None
    try:
        data = r.json()
    except Exception as e:
        print(f"  Risposta non JSON: {e}\n  {r.text[:300]}")
        return None
    rows = data.get("data") or []
    print(f"  totalCount  : {data.get('totalCount')}")
    print(f"  righe       : {len(rows)}")
    if rows:
        n_cols = len(payload.get("columns", []))
        n_vals = len(rows[0].get("d", []))
        print(f"  colonne richieste={n_cols}  valori ricevuti={n_vals}"
              f"  {'  <-- DISALLINEAMENTO!' if n_cols != n_vals else '  (allineate)'}")
        print(f"  primo record: {rows[0].get('s')}")
        print(f"    valori: {rows[0].get('d')}")
    return rows


def payload(cols, types, filters=None, market_url=URL_ITALY, markets=("italy",)):
    p = {
        "filter": filters or [],
        "options": {"lang": "en"},
        "markets": list(markets),
        "symbols": {"query": {"types": list(types)}, "tickers": []},
        "columns": list(cols),
        "sort": {"sortBy": "change|1M", "sortOrder": "desc"},
        "range": [0, 20],
    }
    return p


def main():
    print("DIAGNOSTICA ETF/ETN/ETC — TradingView")

    # ── TEST 1: raggiungibilità base, nessun filtro, colonne minime ──
    call(URL_ITALY, payload(["name", "close"], ["fund"]),
         "1. Scanner Italia raggiungibile? (types=fund, 2 colonne, zero filtri)")

    # ── TEST 2: le colonne dei fondi sono valide? ──
    call(URL_ITALY, payload(["name", "close"] + FUND_COLS, ["fund"]),
         "2. Le colonne expense_ratio/aum sono accettate? (SOSPETTO PRINCIPALE)")

    # ── TEST 3: set colonne completo del report ──
    call(URL_ITALY, payload(BASE_COLS, ["fund"]),
         "3. Set colonne completo (senza colonne fondo)")

    # ── TEST 4: set completo + colonne fondo ──
    call(URL_ITALY, payload(BASE_COLS + FUND_COLS, ["fund"]),
         "4. Set completo + colonne fondo (com'e' ora nel report)")

    # ── TEST 5: types usati dal report ──
    call(URL_ITALY, payload(BASE_COLS, ["fund", "structured"]),
         "5. types=['fund','structured'] come nel report")

    # ── TEST 6: con i filtri del report ──
    filters = [
        {"left": "RSI", "operation": "in_range", "right": [30, 85]},
        {"left": "average_volume_10d_calc", "operation": "greater", "right": 3000},
    ]
    rows = call(URL_ITALY, payload(BASE_COLS, ["fund", "structured"], filters),
                "6. Con i filtri API del report (RSI 30-85, volume>3000)")

    # ── TEST 7: tassonomia reale — che type/typespecs hanno gli ETP italiani? ──
    rows = call(URL_ITALY, payload(BASE_COLS, ["fund", "structured", "etf"]),
                "7. Tassonomia: quali type/typespecs tornano davvero?")
    if rows:
        print("\n  --- Riepilogo tassonomia (type / typespecs) ---")
        seen = {}
        for r in rows:
            d = dict(zip(BASE_COLS, r.get("d", [])))
            key = (d.get("type"), json.dumps(d.get("typespecs")))
            seen.setdefault(key, []).append(r.get("s", "").split(":")[-1])
        for (t, ts), syms in seen.items():
            print(f"    type={t!r:14} typespecs={ts:24} -> {', '.join(syms[:6])}")
        print("\n  NOTA: se qui NON compare type='fund', la funzione _is_etp() del")
        print("        report scarta tutto ed e' quella la causa della lista vuota.")

    # ── TEST 8: fallback scanner globale filtrato su Milano ──
    p = payload(BASE_COLS, ["fund"], markets=("italy",))
    call(URL_GLOBAL, p, "8. Fallback: stessa query sullo scanner /global/scan")

    # ── TEST 9: controllo su simboli noti quotati a Milano ──
    known = ["MIL:SWDA", "MIL:CSPX", "MIL:SGLD", "MIL:PHAU", "MIL:EIMI"]
    print(f"\n{'='*70}\nTEST: 9. Simboli noti (SWDA, CSPX, SGLD, PHAU, EIMI)\n{'='*70}")
    try:
        r = requests.post(URL_GLOBAL,
                          json={"symbols": {"tickers": known},
                                "columns": BASE_COLS + FUND_COLS},
                          headers=TV_HEADERS, timeout=25)
        print(f"  HTTP status : {r.status_code}")
        if r.status_code == 200:
            rows = (r.json().get("data") or [])
            print(f"  righe       : {len(rows)}")
            for row in rows:
                d = dict(zip(BASE_COLS + FUND_COLS, row.get("d", [])))
                print(f"    {row.get('s'):14} close={d.get('close')} "
                      f"type={d.get('type')} specs={d.get('typespecs')} "
                      f"ter={d.get('expense_ratio')} aum={d.get('aum')}")
        else:
            print(f"  Corpo errore: {r.text[:300]}")
    except Exception as e:
        print(f"  ECCEZIONE: {e}")

    print(f"\n{'='*70}")
    print("COME LEGGERE I RISULTATI")
    print("="*70)
    print("""
  TEST 1 fallisce            -> problema di rete/blocco: TradingView non
                                risponde piu' a richieste non autenticate.
  TEST 1 ok, TEST 2 fallisce -> le colonne expense_ratio/aum sono invalide:
                                vanno rimosse o rinominate (causa piu' probabile).
  TEST 4 vuoto ma 3 pieno    -> confermato: sono le colonne fondo a rompere tutto.
  TEST 5 vuoto ma 3 pieno    -> il problema e' types=['fund','structured'].
  TEST 6 vuoto ma 5 pieno    -> sono i filtri API (RSI/volume) troppo stretti.
  TEST 7                     -> mostra la tassonomia REALE: serve per correggere
                                _is_etp() nel report.
  TEST 9 vuoto               -> il formato simbolo 'MIL:' non e' piu' valido;
                                prova con 'BVME:' o 'EURONEXT:'.
""")


if __name__ == "__main__":
    main()
