"""
Indicatori tecnici con le STESSE formule delle funzioni Pine di TradingView.

Ogni funzione prende pandas.Series allineate per indice e restituisce
Series dello stesso indice; i valori non ancora calcolabili sono NaN
(in Pine: na). Nessuna chiamata di rete qui dentro.

Riferimenti (manuale Pine v5/v6, sezione "ta."):
- ta.sma, ta.ema (seed = SMA dei primi n valori), ta.rma (media di Wilder,
  alpha = 1/n, seed = SMA dei primi n valori), ta.rsi, ta.tr, ta.atr,
  ta.stoch, ta.stdev (deviazione standard di popolazione), indicatore
  integrato "DMI"/"ADX", "MACD", "Bollinger Bands", "Stochastic".
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


# ─── medie di base ───────────────────────────────────────────────────────────

def sma(x: pd.Series, n: int) -> pd.Series:
    """ta.sma: NaN finche' la finestra non e' piena o contiene NaN."""
    return x.rolling(n, min_periods=n).mean()


def _ricorsiva(x: pd.Series, n: int, alpha: float) -> pd.Series:
    """Schema comune di ta.ema e ta.rma:
        sum := na(sum[1]) ? ta.sma(src, n) : alpha*src + (1-alpha)*sum[1]
    Il seed e' la SMA della prima finestra completa senza NaN."""
    v = x.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    prev = np.nan
    for i in range(len(v)):
        if math.isnan(prev):
            if i >= n - 1:
                w = v[i - n + 1:i + 1]
                if not np.isnan(w).any():
                    prev = w.mean()
        else:
            prev = alpha * v[i] + (1 - alpha) * prev
        out[i] = prev
    return pd.Series(out, index=x.index)


def ema(x: pd.Series, n: int) -> pd.Series:
    """ta.ema: alpha = 2/(n+1), seed = SMA(n)."""
    return _ricorsiva(x, n, 2.0 / (n + 1))


def rma(x: pd.Series, n: int) -> pd.Series:
    """ta.rma (media di Wilder): alpha = 1/n, seed = SMA(n)."""
    return _ricorsiva(x, n, 1.0 / n)


def kama(x: pd.Series, n: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman Adaptive Moving Average.
        ER  = |src - src[n]| / somma_n(|src - src[1]|)
        SC  = (ER*(2/(fast+1) - 2/(slow+1)) + 2/(slow+1))^2
        KAMA = KAMA[1] + SC*(src - KAMA[1])
    Seed: KAMA = src sulla prima barra in cui ER e' calcolabile (barra n).
    Con molti anni di storico il seed non incide sui valori recenti."""
    v = x.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    fsc, ssc = 2.0 / (fast + 1), 2.0 / (slow + 1)
    absdiff = np.abs(np.diff(v, prepend=np.nan))
    prev = np.nan
    for i in range(n, len(v)):
        noise = np.nansum(absdiff[i - n + 1:i + 1])
        er = abs(v[i] - v[i - n]) / noise if noise != 0 else 0.0
        sc = (er * (fsc - ssc) + ssc) ** 2
        prev = v[i] if math.isnan(prev) else prev + sc * (v[i] - prev)
        out[i] = prev
    return pd.Series(out, index=x.index)


# ─── oscillatori ─────────────────────────────────────────────────────────────

def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    """ta.rsi: u = max(c-c[1],0), d = max(c[1]-c,0), RS = rma(u)/rma(d).
    rma(d)=0 -> 100; rma(u)=0 -> 0."""
    ch = c.diff()
    u = ch.clip(lower=0)
    d = (-ch).clip(lower=0)
    ru, rd = rma(u, n), rma(d, n)
    out = 100 - 100 / (1 + ru / rd)
    out = out.where(rd != 0, 100.0)
    out = out.where(ru != 0, 0.0)
    return out.where(ru.notna() & rd.notna())


def true_range(h: pd.Series, l: pd.Series, c: pd.Series, handle_na: bool = True) -> pd.Series:
    """ta.tr(handle_na): con handle_na=True la prima barra vale high-low
    (come in ta.atr); con False e' NaN (come nell'indicatore DMI)."""
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1, skipna=False)
    if handle_na:
        tr = tr.where(pc.notna(), h - l)
    return tr


def atr(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14) -> pd.Series:
    """ta.atr = ta.rma(ta.tr(true), n)."""
    return rma(true_range(h, l, c, True), n)


def stoch(c: pd.Series, h: pd.Series, l: pd.Series, k: int = 14, smooth_k: int = 3, d: int = 3):
    """Indicatore integrato "Stochastic" (14,3,3):
        %K = sma(ta.stoch(close, high, low, 14), 3) ; %D = sma(%K, 3)"""
    ll, hh = l.rolling(k, min_periods=k).min(), h.rolling(k, min_periods=k).max()
    raw = 100 * (c - ll) / (hh - ll)
    kk = sma(raw, smooth_k)
    return kk, sma(kk, d)


def macd(c: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Indicatore integrato "MACD": linea = ema(12)-ema(26),
    segnale = ema(linea, 9), istogramma = linea - segnale."""
    line = ema(c, fast) - ema(c, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def dmi(h: pd.Series, l: pd.Series, c: pd.Series, n: int = 14, adx_n: int = 14):
    """Indicatore integrato "DMI" (Directional Movement Index), lunghezza DI
    14 e smoothing ADX 14, stesso codice Pine:
        up = change(high), down = -change(low)
        +DM = up > down and up > 0 ? up : 0   (idem -DM)
        trur = rma(ta.tr, n)                  (ta.tr senza handle_na)
        +DI = 100*rma(+DM, n)/trur ; -DI analogo
        ADX = 100*rma(|+DI - -DI| / (+DI + -DI, 1 se zero), adx_n)"""
    up = h.diff()
    down = -l.diff()
    # plusDM = na(up) ? na : (...)  -> NaN sulla prima barra, come in Pine
    pdm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=h.index).where(up.notna())
    mdm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=h.index).where(down.notna())
    trur = rma(true_range(h, l, c, handle_na=False), n)
    plus = (100 * rma(pdm, n) / trur).ffill()      # fixnan()
    minus = (100 * rma(mdm, n) / trur).ffill()
    s = plus + minus
    adx = 100 * rma((plus - minus).abs() / s.where(s != 0, 1.0), adx_n)
    return plus, minus, adx


def bollinger(c: pd.Series, n: int = 20, mult: float = 2.0):
    """Indicatore integrato "Bollinger Bands": base = sma(20),
    dev = mult * ta.stdev(20) (deviazione standard di POPOLAZIONE).
    Restituisce base, superiore, inferiore, %B, larghezza % = (sup-inf)/base*100."""
    basis = sma(c, n)
    dev = mult * c.rolling(n, min_periods=n).std(ddof=0)
    up, lo = basis + dev, basis - dev
    pb = (c - lo) / (up - lo)
    bw = (up - lo) / basis * 100
    return basis, up, lo, pb, bw


# ─── tabella completa ────────────────────────────────────────────────────────

def calcola_tutti(df: pd.DataFrame, kama_param: list[tuple[int, int, int]]) -> pd.DataFrame:
    """df con colonne Open/High/Low/Close/Volume (giornaliero).
    Restituisce un DataFrame con tutte le colonne indicatore."""
    o, h, l, c, v = (df[k] for k in ("Open", "High", "Low", "Close", "Volume"))
    out = pd.DataFrame(index=df.index)
    for n in (20, 50, 100, 200):
        out[f"SMA{n}"] = sma(c, n)
    for n in (20, 50):
        out[f"EMA{n}"] = ema(c, n)
    for (n, f, s) in kama_param:
        out[f"KAMA({n},{f},{s})"] = kama(c, n, f, s)
    out["RSI14"] = rsi(c, 14)
    out["StochK"], out["StochD"] = stoch(c, h, l, 14, 3, 3)
    out["MACD"], out["MACDsig"], out["MACDhist"] = macd(c)
    out["+DI"], out["-DI"], out["ADX"] = dmi(h, l, c, 14, 14)
    out["ATR14"] = atr(h, l, c, 14)
    out["ATR%"] = out["ATR14"] / c * 100
    out["BBbase"], out["BBsup"], out["BBinf"], out["BB%B"], out["BBlarg%"] = bollinger(c)
    out["Vol20"] = sma(v.astype(float), 20)
    out["Vol50"] = sma(v.astype(float), 50)
    return out
