"""
Struttura di prezzo descritta come fatti geometrici: punti di swing (ZigZag
con soglia in multipli di ATR), livelli, gap, candele, figure candidate,
Fibonacci. Nessun giudizio, nessuna previsione.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Pivot:
    i: int                 # posizione nella serie
    data: pd.Timestamp
    prezzo: float
    tipo: str              # "H" massimo, "L" minimo
    confermato: bool = True
    etichetta: str = ""    # HH / LH / HL / LL / "" (primo della sua specie)


def zigzag(df: pd.DataFrame, atr: pd.Series, mult: float) -> list[Pivot]:
    """ZigZag su massimi/minimi giornalieri.
    Un massimo diventa punto di swing quando, dopo di esso, il prezzo scende
    di almeno mult*ATR14 (ATR della barra del massimo); simmetrico per i
    minimi. L'ultimo estremo, non ancora confermato da un'inversione di
    pari ampiezza, e' riportato come "provvisorio"."""
    h, l = df["High"].to_numpy(float), df["Low"].to_numpy(float)
    a = atr.to_numpy(float)
    idx = df.index
    start = int(np.argmax(~np.isnan(a))) if (~np.isnan(a)).any() else len(a)
    piv: list[Pivot] = []
    if start >= len(a) - 1:
        return piv
    trend = 0
    hi = lo = start
    for i in range(start + 1, len(h)):
        if trend == 0:
            if h[i] > h[hi]:
                hi = i
            if l[i] < l[lo]:
                lo = i
            if hi > lo and h[hi] - l[lo] >= mult * a[lo]:
                piv.append(Pivot(lo, idx[lo], l[lo], "L"))
                trend = 1
            elif lo > hi and h[hi] - l[lo] >= mult * a[hi]:
                piv.append(Pivot(hi, idx[hi], h[hi], "H"))
                trend = -1
        elif trend == 1:
            if h[i] >= h[hi]:
                hi = i
            elif h[hi] - l[i] >= mult * a[hi]:
                piv.append(Pivot(hi, idx[hi], h[hi], "H"))
                trend, lo = -1, i
        else:
            if l[i] <= l[lo]:
                lo = i
            elif h[i] - l[lo] >= mult * a[lo]:
                piv.append(Pivot(lo, idx[lo], l[lo], "L"))
                trend, hi = 1, i
    if trend == 1:
        piv.append(Pivot(hi, idx[hi], h[hi], "H", confermato=False))
    elif trend == -1:
        piv.append(Pivot(lo, idx[lo], l[lo], "L", confermato=False))
    # etichette HH/LH/HL/LL rispetto al precedente dello stesso tipo
    ult = {"H": None, "L": None}
    for p in piv:
        prev = ult[p.tipo]
        if prev is not None:
            if p.tipo == "H":
                p.etichetta = "HH" if p.prezzo > prev.prezzo else ("LH" if p.prezzo < prev.prezzo else "EH")
            else:
                p.etichetta = "HL" if p.prezzo > prev.prezzo else ("LL" if p.prezzo < prev.prezzo else "EL")
        ult[p.tipo] = p
    return piv


def estremi_periodo(df: pd.DataFrame, oggi: pd.Timestamp) -> dict:
    """Massimo/minimo (High/Low) con data su finestre di calendario."""
    out = {}
    for nome, off in (("1 settimana", pd.DateOffset(days=7)), ("1 mese", pd.DateOffset(months=1)),
                      ("3 mesi", pd.DateOffset(months=3)), ("52 settimane", pd.DateOffset(weeks=52))):
        w = df[df.index > oggi - off]
        if w.empty:
            out[nome] = None
            continue
        out[nome] = {"max": w["High"].max(), "data_max": w["High"].idxmax(),
                     "min": w["Low"].min(), "data_min": w["Low"].idxmin(), "n": len(w)}
    return out


# ─── gap ─────────────────────────────────────────────────────────────────────

def trova_gap(df: pd.DataFrame, atr: pd.Series, vol20: pd.Series, soglia_atr: float,
              dal: pd.Timestamp | None = None) -> list[dict]:
    """Gap = minimo della seduta sopra il massimo precedente (gap up) o
    massimo sotto il minimo precedente (gap down). Ampiezza misurata
    sull'ATR14 della seduta precedente. Chiuso = una seduta successiva
    torna a toccare il bordo opposto (massimo/minimo della seduta prima del gap)."""
    h, l, v = df["High"].to_numpy(float), df["Low"].to_numpy(float), df["Volume"].to_numpy(float)
    a, v20 = atr.to_numpy(float), vol20.to_numpy(float)
    idx = df.index
    out = []
    for i in range(1, len(df)):
        if dal is not None and idx[i] < dal:
            continue
        if np.isnan(a[i - 1]) or a[i - 1] <= 0:
            continue
        if l[i] > h[i - 1]:
            direz, lo, hi = "rialzo", h[i - 1], l[i]
        elif h[i] < l[i - 1]:
            direz, lo, hi = "ribasso", h[i], l[i - 1]
        else:
            continue
        amp = (hi - lo) / a[i - 1]
        if amp <= soglia_atr:
            continue
        chiuso_dopo = None
        for j in range(i + 1, len(df)):
            if (direz == "rialzo" and l[j] <= lo) or (direz == "ribasso" and h[j] >= hi):
                chiuso_dopo = j - i
                break
        relv = v[i] / v20[i - 1] if v20[i - 1] and not np.isnan(v20[i - 1]) and v20[i - 1] > 0 else np.nan
        out.append({"i": i, "data": idx[i], "direzione": direz, "da": lo, "a": hi, "ampiezza_atr": amp,
                    "vol_rel": relv, "chiuso_dopo": chiuso_dopo})
    return out


# ─── livelli ─────────────────────────────────────────────────────────────────

def gruppi_livelli(piv: list[Pivot], tolleranza: float) -> list[dict]:
    """Raggruppa i punti di swing confermati con prezzi entro `tolleranza`
    (in valuta) dal primo punto del gruppo, ordinati per prezzo."""
    pts = sorted([p for p in piv if p.confermato], key=lambda p: p.prezzo)
    gruppi, cur = [], []
    for p in pts:
        if cur and p.prezzo - cur[0].prezzo > tolleranza:
            gruppi.append(cur)
            cur = []
        cur.append(p)
    if cur:
        gruppi.append(cur)
    out = []
    for g in gruppi:
        out.append({"prezzo": float(np.mean([p.prezzo for p in g])), "min": g[0].prezzo, "max": g[-1].prezzo,
                    "tocchi": len(g), "date": sorted(p.data for p in g),
                    "tipi": "".join(sorted({p.tipo for p in g}))})
    return out


def passo_tondo(prezzo: float) -> float:
    """Passo dei numeri tondi: meta' della potenza di 10 inferiore
    (es. 92 -> 5 ; 9,2 -> 0,5 ; 0,92 -> 0,05)."""
    return 10 ** math.floor(math.log10(prezzo)) / 2


def numeri_tondi(prezzo: float, banda: float = 0.10) -> list[float]:
    p = passo_tondo(prezzo)
    lo, hi = prezzo * (1 - banda), prezzo * (1 + banda)
    k = math.ceil(lo / p)
    out = []
    while k * p <= hi:
        out.append(round(k * p, 10))
        k += 1
    return out


# ─── figure candidate ────────────────────────────────────────────────────────

def doppi(piv: list[Pivot], df: pd.DataFrame, atr: pd.Series, tipo: str, tol_atr: float = 1.0,
          entro_sedute: int = 250) -> dict | None:
    """Ultima terna consecutiva P1-intermedio-P2 dello stesso tipo
    (H-L-H per i doppi massimi, L-H-L per i doppi minimi) con |P2-P1| <= tol_atr*ATR(P2)."""
    n = len(df)
    c = df["Close"].to_numpy(float)
    for k in range(len(piv) - 1, 1, -1):
        p2, mid, p1 = piv[k], piv[k - 1], piv[k - 2]
        if p2.tipo != tipo or p1.tipo != tipo:
            continue
        if n - 1 - p2.i > entro_sedute:
            return None
        a2 = atr.iloc[p2.i]
        if np.isnan(a2) or abs(p2.prezzo - p1.prezzo) > tol_atr * a2:
            continue
        rotto = None
        for j in range(p2.i + 1, n):
            if (tipo == "H" and c[j] < mid.prezzo) or (tipo == "L" and c[j] > mid.prezzo):
                rotto = df.index[j]
                break
        return {"p1": p1, "mid": mid, "p2": p2, "diff": p2.prezzo - p1.prezzo, "diff_atr": (p2.prezzo - p1.prezzo) / a2,
                "rotto_in_chiusura": rotto, "altezza": abs((p1.prezzo + p2.prezzo) / 2 - mid.prezzo)}
    return None


def rettangolo(df: pd.DataFrame, atr: pd.Series, max_alt_atr: float = 4.0, min_sedute: int = 15,
               cerca_indietro: int = 60) -> dict | None:
    """Base/rettangolo piu' recente: finestra di almeno `min_sedute` sedute
    il cui intervallo massimo-minimo non supera max_alt_atr * ATR14 della
    sua ultima seduta. Si cerca la finestra che termina piu' vicino a oggi
    (fino a `cerca_indietro` sedute fa), estesa all'indietro il piu' possibile."""
    h, l, c = df["High"].to_numpy(float), df["Low"].to_numpy(float), df["Close"].to_numpy(float)
    a = atr.to_numpy(float)
    n = len(df)
    for e in range(n - 1, max(n - 1 - cerca_indietro, min_sedute), -1):
        if np.isnan(a[e]):
            break
        lim = max_alt_atr * a[e]
        top, bot, s = h[e], l[e], e
        while s - 1 >= 0:
            t2, b2 = max(top, h[s - 1]), min(bot, l[s - 1])
            if t2 - b2 > lim:
                break
            top, bot, s = t2, b2, s - 1
        if e - s + 1 < min_sedute:
            continue
        alt = top - bot
        tol = 0.25 * a[e]
        tocchi_sup = _episodi(h[s:e + 1] >= top - tol)
        tocchi_inf = _episodi(l[s:e + 1] <= bot + tol)
        rottura = None
        for j in range(e + 1, n):
            if c[j] > top:
                rottura = ("rialzo", df.index[j]); break
            if c[j] < bot:
                rottura = ("ribasso", df.index[j]); break
        return {"inizio": df.index[s], "fine": df.index[e], "sedute": e - s + 1, "sup": top, "inf": bot,
                "altezza": alt, "altezza_atr": alt / a[e], "tocchi_sup": tocchi_sup, "tocchi_inf": tocchi_inf,
                "in_corso": e == n - 1, "rottura": rottura,
                "obiettivo_rialzo": top + alt, "obiettivo_ribasso": bot - alt}
    return None


def _episodi(mask: np.ndarray) -> int:
    """Numero di gruppi di sedute consecutive True."""
    m = np.asarray(mask, dtype=bool)
    return int(m[0]) + int(np.sum(m[1:] & ~m[:-1])) if len(m) else 0


def fibonacci(piv_maggiori: list[Pivot]) -> dict | None:
    """Ritracciamenti dell'ultimo swing maggiore completato (tra gli ultimi
    due punti confermati dello ZigZag a soglia maggiore)."""
    conf = [p for p in piv_maggiori if p.confermato]
    if len(conf) < 2:
        return None
    a, b = conf[-2], conf[-1]
    rng = b.prezzo - a.prezzo
    livelli = {r: b.prezzo - r * rng for r in (0.382, 0.5, 0.618, 0.786)}
    return {"da": a, "a": b, "direzione": "rialzo" if rng > 0 else "ribasso", "livelli": livelli}
