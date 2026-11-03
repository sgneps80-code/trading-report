"""
Qualita' del dato e mercato principale.

- barre incoerenti: apertura o chiusura fuori dall'intervallo [minimo, massimo];
- ombre anomale: ombra oltre k ATR14 con volume basso (tipiche stampe isolate);
- stampe fuori dal mercato principale: massimi/minimi di un listino secondario
  oltre il range della stessa seduta sul mercato principale;
- mercato principale di un listino secondario (es. 1SAN.MI -> SAN.PA);
- intervallo di confidenza di Wilson per le proporzioni.

Le barre segnalate NON vengono modificate: vengono elencate e, dove
indicato, escluse dal calcolo degli swing.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

# Paese dell'ISIN -> suffisso Yahoo della borsa principale
SUFFISSO_DA_PAESE = {"FR": ".PA", "NL": ".AS", "BE": ".BR", "PT": ".LS", "DE": ".DE", "ES": ".MC",
                     "IT": ".MI", "GB": ".L", "CH": ".SW", "FI": ".HE", "AT": ".VI", "DK": ".CO",
                     "SE": ".ST", "NO": ".OL", "US": ""}

NOME_MERCATO = {".MI": "Borsa Italiana (Euronext Milan)", ".PA": "Euronext Parigi", ".AS": "Euronext Amsterdam",
                ".BR": "Euronext Bruxelles", ".LS": "Euronext Lisbona", ".DE": "Xetra", ".MC": "Bolsa de Madrid",
                ".L": "London Stock Exchange", ".SW": "SIX Swiss Exchange", ".HE": "Nasdaq Helsinki",
                ".VI": "Wiener Börse", ".CO": "Nasdaq Copenhagen", ".ST": "Nasdaq Stockholm", ".OL": "Oslo Børs"}


def suffisso(simbolo: str) -> str:
    s = simbolo.upper()
    return "." + s.rsplit(".", 1)[1] if "." in s else ""


def nome_mercato(simbolo: str) -> str | None:
    suf = suffisso(simbolo)
    if suf in NOME_MERCATO:
        return NOME_MERCATO[suf]
    if not suf and simbolo.isalpha():
        return "USA (NYSE/Nasdaq)"
    return None


def principale_da_isin(simbolo: str, isin: str) -> str | None:
    """Candidato mercato principale per i listini esteri di Borsa Italiana
    (simboli 1XXX.MI, es. 1SAN.MI): ticker senza "1" + suffisso del paese
    dell'ISIN. Va sempre verificato sui prezzi prima di usarlo."""
    s, isin = simbolo.upper(), (isin or "").upper()
    m = re.fullmatch(r"1([A-Z0-9]+)\.MI", s)
    if not m or len(isin) != 12:
        return None
    suf = SUFFISSO_DA_PAESE.get(isin[:2])
    if suf is None or suf == ".MI":
        return None
    return m.group(1) + suf


def incoerenti(df: pd.DataFrame) -> pd.Series:
    """True dove apertura o chiusura stanno fuori da [minimo, massimo], o minimo > massimo."""
    o, h, l, c = (df[k] for k in ("Open", "High", "Low", "Close"))
    tol = 1e-9 * h.abs().clip(lower=1)
    return (o > h + tol) | (o < l - tol) | (c > h + tol) | (c < l - tol) | (l > h + tol)


def ombre_anomale(df: pd.DataFrame, atr: pd.Series, vol20: pd.Series, k: float = 3.0,
                  vol_max: float = 0.5) -> pd.Series:
    """True dove un'ombra supera k*ATR14 (della seduta precedente) e il volume
    e' inferiore a vol_max volte la media dei 20 volumi precedenti."""
    o, h, l, c, v = (df[x] for x in ("Open", "High", "Low", "Close", "Volume"))
    a_prev, v_prev = atr.shift(1), vol20.shift(1)
    sup = h - np.maximum(o, c)
    inf = np.minimum(o, c) - l
    ombra = (sup > k * a_prev) | (inf > k * a_prev)
    poco_vol = v < vol_max * v_prev
    return (ombra & poco_vol).fillna(False).astype(bool)


def fuori_principale(listino: pd.DataFrame, principale: pd.DataFrame, atr_pr: pd.Series,
                     conv: pd.Series | None = None, k: float = 0.5) -> pd.DataFrame:
    """Sedute comuni in cui il massimo (minimo) del listino supera il massimo
    (scende sotto il minimo) del mercato principale di oltre k*ATR14 del
    principale. `conv` converte i prezzi del principale nella valuta del
    listino (moltiplicatore per data), se le valute differiscono."""
    comuni = listino.index.intersection(principale.index)
    if not len(comuni):
        return pd.DataFrame()
    L, P = listino.loc[comuni], principale.loc[comuni]
    f = conv.reindex(comuni) if conv is not None else pd.Series(1.0, index=comuni)
    a = atr_pr.reindex(comuni) * f
    ph, pl = P["High"] * f, P["Low"] * f
    sopra = (L["High"] - ph) / a
    sotto = (pl - L["Low"]) / a
    out = pd.DataFrame({"max_listino": L["High"], "max_princ": ph, "oltre_max_atr": sopra,
                        "min_listino": L["Low"], "min_princ": pl, "oltre_min_atr": sotto})
    return out[(sopra > k) | (sotto > k)]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Intervallo di confidenza di Wilson al 95% per k successi su n, in %."""
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    mezzo = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centro - mezzo) * 100, min(1.0, centro + mezzo) * 100)


def fmt_ic(ic) -> str:
    return "n.d." if ic is None else f"[{ic[0]:.1f}–{ic[1]:.1f}]"
