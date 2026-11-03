"""
Test degli indicatori su valori noti.

1. Valori calcolati a mano (piccole serie) per SMA, EMA con seed SMA,
   RMA, RSI, ATR, stocastico, Bollinger.
2. Confronto con TA-Lib (se installata: pip install TA-Lib) su 3.000 barre
   sintetiche. TA-Lib usa le stesse formule di Wilder ma con seed un po'
   diversi in qualche caso: dopo il periodo di convergenza i valori
   devono coincidere fino a 1e-6.

Esecuzione:  python -m pytest tests -q
"""
import math

import numpy as np
import pandas as pd
import pytest

from analisi import indicatori as ind


def s(vals):
    return pd.Series(vals, dtype=float)


# ─── valori calcolati a mano ─────────────────────────────────────────────────

def test_sma_ema_rma_a_mano():
    x = s([1, 2, 3, 4, 5, 6])
    assert ind.sma(x, 3).tolist()[2:] == [2, 3, 4, 5]
    # EMA(3): alpha = 0.5, seed = SMA(1,2,3) = 2 ; poi 0.5*4+0.5*2 = 3 ; 4 ; 5
    e = ind.ema(x, 3)
    assert math.isnan(e[1]) and e.tolist()[2:] == [2, 3, 4, 5]
    # RMA(3): alpha = 1/3, seed 2 ; 4/3+4/3=... -> (4 + 2*2)/3 = 8/3
    r = ind.rma(x, 3)
    assert r[2] == 2 and abs(r[3] - 8 / 3) < 1e-12
    assert abs(r[4] - (5 + 2 * 8 / 3) / 3) < 1e-12


def test_rsi_a_mano():
    # variazioni: +1,+1,-1,+1  con n=2
    c = s([10, 11, 12, 11, 12])
    r = ind.rsi(c, 2)
    # barra 2: u=[1,1] d=[0,0] -> rma(d)=0 -> RSI 100
    assert r[2] == 100
    # barra 3: ru = 0.5*0 + 0.5*1 = 0.5 ; rd = 0.5*1 + 0.5*0 = 0.5 -> 50
    assert abs(r[3] - 50) < 1e-12
    # barra 4: ru = 0.5*1+0.5*0.5 = 0.75 ; rd = 0.25 -> RS 3 -> 75
    assert abs(r[4] - 75) < 1e-12


def test_atr_a_mano():
    h = s([10, 12, 13])
    l = s([8, 9, 11])
    c = s([9, 11, 12])
    # TR: barra0 = h-l = 2 ; barra1 = max(3, |12-9|, |9-9|) = 3 ; barra2 = max(2, 2, 0) = 2
    tr = ind.true_range(h, l, c)
    assert tr.tolist() == [2, 3, 2]
    a = ind.atr(h, l, c, 2)
    assert math.isnan(a[0]) and a[1] == 2.5 and a[2] == 2.25


def test_stoch_bollinger_a_mano():
    c = s([1, 2, 3, 4, 5])
    h, l = c + 1, c - 1
    k, d = ind.stoch(c, h, l, 3, 1, 1)
    # barra 2: LL = 0, HH = 4 -> 100*(3-0)/4 = 75
    assert abs(k[2] - 75) < 1e-12 and abs(d[2] - 75) < 1e-12
    base, up, lo, pb, bw = ind.bollinger(s([1, 2, 3]), 3, 2)
    sd = math.sqrt(2 / 3)                      # popolazione
    assert abs(up[2] - (2 + 2 * sd)) < 1e-12
    assert abs(pb[2] - (3 - (2 - 2 * sd)) / (4 * sd)) < 1e-12


def test_kama_efficienza_1():
    # serie lineare: ER = 1 -> SC = (2/3)^2
    c = s(list(range(1, 30)))
    k = ind.kama(c, 10, 2, 30)
    sc = (2 / 3) ** 2
    assert k[10] == 11
    assert abs(k[11] - (11 + sc * (12 - 11))) < 1e-12


# ─── confronto con TA-Lib ────────────────────────────────────────────────────

talib = pytest.importorskip("talib")


@pytest.fixture(scope="module")
def ohlc():
    rng = np.random.default_rng(42)
    n = 3000
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
    o = c * np.exp(rng.normal(0, 0.005, n))
    h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.008, n)))
    l = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.008, n)))
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c})


def _coda(a, b, da=500):
    a = np.asarray(a, dtype=float)[da:]
    b = np.asarray(b, dtype=float)[da:]
    return np.nanmax(np.abs(a - b))


def test_vs_talib(ohlc):
    o, h, l, c = (ohlc[k] for k in ("Open", "High", "Low", "Close"))
    cv, hv, lv = c.values, h.values, l.values
    assert _coda(ind.sma(c, 50), talib.SMA(cv, 50)) < 1e-9
    assert _coda(ind.ema(c, 20), talib.EMA(cv, 20)) < 1e-9          # TA-Lib: seed SMA, come Pine
    assert _coda(ind.rsi(c, 14), talib.RSI(cv, 14)) < 1e-6
    assert _coda(ind.atr(h, l, c, 14), talib.ATR(hv, lv, cv, 14)) < 1e-6
    m, sg, hi = ind.macd(c)
    tm, ts, th = talib.MACD(cv, 12, 26, 9)
    assert _coda(m, tm) < 1e-6 and _coda(sg, ts) < 1e-6
    k, d = ind.stoch(c, h, l)
    tk, td = talib.STOCH(hv, lv, cv, 14, 3, 0, 3, 0)
    assert _coda(k, tk) < 1e-9 and _coda(d, td) < 1e-9
    p, mi, adx = ind.dmi(h, l, c)
    assert _coda(p, talib.PLUS_DI(hv, lv, cv, 14)) < 1e-6
    assert _coda(mi, talib.MINUS_DI(hv, lv, cv, 14)) < 1e-6
    assert _coda(adx, talib.ADX(hv, lv, cv, 14)) < 1e-6
    _, up, lo, _, _ = ind.bollinger(c)
    tu, _, tl = talib.BBANDS(cv, 20, 2, 2, 0)
    assert _coda(up, tu) < 1e-9 and _coda(lo, tl) < 1e-9
    # TA-Lib KAMA ha fast=2 e slow=30 fissi
    assert _coda(ind.kama(c, 10, 2, 30), talib.KAMA(cv, 10)) < 1e-6
