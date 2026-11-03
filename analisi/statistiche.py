"""
Statistiche storiche per i tassi base (fino a 10 anni di sedute).
Ogni risultato porta la dimensione del campione n.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .qualita import wilson

PERCENTILI = (5, 10, 25, 50, 75, 90, 95)
ORIZZONTI = (5, 10, 20)


def finestra_10_anni(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df[df.index > df.index[-1] - pd.DateOffset(years=10)]


def volatilita(c: pd.Series) -> dict:
    r = c.pct_change() * 100
    out = {}
    for n in (20, 60, 250):
        w = r.iloc[-n:]
        out[n] = (float(w.std(ddof=1)) if w.notna().sum() == n else None, int(w.notna().sum()))
    rr = r.dropna()
    out["oltre3"] = (float((rr.abs() > 3).mean() * 100) if len(rr) else None, len(rr))
    out["oltre3_ic"] = wilson(int((rr.abs() > 3).sum()), len(rr))
    out["su3"] = float((rr > 3).mean() * 100) if len(rr) else None
    out["giu3"] = float((rr < -3).mean() * 100) if len(rr) else None
    return out


def escursioni(df: pd.DataFrame, atr: pd.Series) -> dict:
    """Per ogni seduta t: massimo dei massimi e minimo dei minimi nelle
    h sedute successive, rispetto alla chiusura di t (in % e in ATR14 di t)."""
    c, h, l = df["Close"].to_numpy(float), df["High"].to_numpy(float), df["Low"].to_numpy(float)
    a = atr.to_numpy(float)
    out = {}
    for hz in ORIZZONTI:
        n = len(c) - hz
        if n <= 0:
            out[hz] = None
            continue
        su_p, giu_p, su_a, giu_a = [], [], [], []
        for t in range(n):
            mx, mn = h[t + 1:t + 1 + hz].max(), l[t + 1:t + 1 + hz].min()
            su_p.append((mx / c[t] - 1) * 100)
            giu_p.append((mn / c[t] - 1) * 100)
            if not np.isnan(a[t]) and a[t] > 0:
                su_a.append((mx - c[t]) / a[t])
                giu_a.append((mn - c[t]) / a[t])
        out[hz] = {
            "n": n, "n_atr": len(su_a),
            "su_pct": np.percentile(su_p, PERCENTILI), "giu_pct": np.percentile(giu_p, PERCENTILI),
            "su_atr": np.percentile(su_a, PERCENTILI) if su_a else None,
            "giu_atr": np.percentile(giu_a, PERCENTILI) if giu_a else None,
        }
    return out


def chiusura_gap(gaps: list[dict], df: pd.DataFrame, atr: pd.Series) -> dict:
    """Per ogni orizzonte h: quota di gap chiusi entro h sedute (solo gap con
    almeno h sedute successive), con IC di Wilson, e TASSO ATTESO: la stessa
    prova applicata a tutte le sedute. Per ogni gap si misura la distanza d
    (in ATR14 del giorno del gap) tra la chiusura del giorno del gap e il bordo
    da richiudere; il tasso atteso e' la frequenza, su tutte le sedute, di un
    movimento contrario >= d entro h sedute (minimo dei minimi per i gap al
    rialzo, massimo dei massimi per quelli al ribasso), mediata sui gap."""
    c, h, l = df["Close"].to_numpy(float), df["High"].to_numpy(float), df["Low"].to_numpy(float)
    a = atr.to_numpy(float)
    n_tot = len(c)
    out = {}
    for hz in ORIZZONTI:
        validi = [g for g in gaps if n_tot - 1 - g["i"] >= hz]
        chiusi = [g for g in validi if g["chiuso_dopo"] is not None and g["chiuso_dopo"] <= hz]
        t = np.arange(max(n_tot - hz, 0))
        t = t[~np.isnan(a[t]) & (a[t] > 0)] if len(t) else t
        giu = np.array([(c[i] - l[i + 1:i + 1 + hz].min()) / a[i] for i in t])
        su = np.array([(h[i + 1:i + 1 + hz].max() - c[i]) / a[i] for i in t])
        attesi = []
        for g in validi:
            i, ag = g["i"], a[g["i"]]
            if np.isnan(ag) or ag <= 0 or not len(t):
                continue
            if g["direzione"] == "rialzo":
                attesi.append(float((giu >= (c[i] - g["da"]) / ag).mean()))
            else:
                attesi.append(float((su >= (g["a"] - c[i]) / ag).mean()))
        atteso = float(np.mean(attesi)) * 100 if attesi else None
        out[hz] = {"pct": len(chiusi) / len(validi) * 100 if validi else None, "n": len(validi),
                   "ic": wilson(len(chiusi), len(validi)), "atteso": atteso, "n_sedute": len(t),
                   "ic_atteso": wilson(round(atteso / 100 * len(t)), len(t)) if atteso is not None else None}
    return out


def _riassunto(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    v = np.array(vals)
    k = int((v > 0).sum())
    return {"n": len(v), "media": float(v.mean()), "mediana": float(np.median(v)), "pos": k / len(v) * 100,
            "ic": wilson(k, len(v))}


def incondizionato(c, hz: int) -> dict:
    """Rendimento a hz sedute da TUTTE le sedute (base di confronto)."""
    cv = np.asarray(c, dtype=float)
    if len(cv) <= hz:
        return {"n": 0}
    return _riassunto(list((cv[hz:] / cv[:-hz] - 1) * 100))


def dopo_giorni_ampi(df: pd.DataFrame, atr: pd.Series, k: float = 2.0) -> dict:
    """Sedute con variazione chiusura-su-chiusura > +k*ATR14 (della seduta
    precedente) o < -k*ATR14; rendimento chiusura(t+h)/chiusura(t)-1."""
    c = df["Close"].to_numpy(float)
    a = atr.to_numpy(float)
    out = {"su": {}, "giu": {}}
    ev_su = [t for t in range(1, len(c)) if not np.isnan(a[t - 1]) and c[t] - c[t - 1] > k * a[t - 1]]
    ev_giu = [t for t in range(1, len(c)) if not np.isnan(a[t - 1]) and c[t] - c[t - 1] < -k * a[t - 1]]
    for nome, ev in (("su", ev_su), ("giu", ev_giu)):
        for hz in ORIZZONTI:
            out[nome][hz] = _riassunto([(c[t + hz] / c[t] - 1) * 100 for t in ev if t + hz < len(c)])
        out[nome]["eventi"] = len(ev)
    return out


def dopo_rsi(c: pd.Series, rsi: pd.Series, hz: int = 10) -> dict:
    """Sedute in cui l'RSI14 entra sopra 70 (ieri <= 70, oggi > 70) o sotto 30
    (ieri >= 30, oggi < 30); rendimento a hz sedute dalla chiusura del giorno d'ingresso."""
    cv, r = c.to_numpy(float), rsi.to_numpy(float)
    su, giu = [], []
    for t in range(1, len(cv) - hz):
        if np.isnan(r[t - 1]) or np.isnan(r[t]):
            continue
        ret = (cv[t + hz] / cv[t] - 1) * 100
        if r[t - 1] <= 70 < r[t]:
            su.append(ret)
        if r[t - 1] >= 30 > r[t]:
            giu.append(ret)
    return {"sopra70": _riassunto(su), "sotto30": _riassunto(giu)}


def rendimento_periodo(c: pd.Series, off: pd.DateOffset) -> tuple[float | None, pd.Timestamp | None]:
    """Rendimento % dall'ultima chiusura disponibile alla data (oggi - off) o prima."""
    if c.empty:
        return None, None
    rif = c[c.index <= c.index[-1] - off]
    if rif.empty:
        return None, None
    return (c.iloc[-1] / rif.iloc[-1] - 1) * 100, rif.index[-1]
