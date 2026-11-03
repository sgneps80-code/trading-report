"""
Scaricamento dati: Yahoo Finance via yfinance (storico OHLCV NON aggiustato,
dividendi, split, calendario eventi) e screener TradingView via
tradingview-screener (solo per il controllo incrociato degli indicatori).

Regola: nessun dato stimato. Se una chiamata fallisce si registra il
motivo in `errori` e il report scrive "non disponibile (motivo)".
"""
from __future__ import annotations

import datetime as dt
import logging
import warnings
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import pandas as pd

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

ROMA = ZoneInfo("Europe/Rome")


def ora_roma() -> dt.datetime:
    return dt.datetime.now(ROMA)


def fmt_ora(t: dt.datetime | pd.Timestamp | None) -> str:
    if t is None or (isinstance(t, float)):
        return "non disponibile"
    if getattr(t, "tzinfo", None) is None:
        t = pd.Timestamp(t).tz_localize("UTC")
    return pd.Timestamp(t).tz_convert(ROMA).strftime("%Y-%m-%d %H:%M")


@dataclass
class Serie:
    simbolo: str
    giornaliero: pd.DataFrame = field(default_factory=pd.DataFrame)
    settimanale: pd.DataFrame = field(default_factory=pd.DataFrame)
    m30: pd.DataFrame = field(default_factory=pd.DataFrame)
    meta: dict = field(default_factory=dict)
    calendario: dict = field(default_factory=dict)
    date_conti: list = field(default_factory=list)      # date passate/future dei conti
    errori: dict = field(default_factory=dict)
    scaricato_alle: dt.datetime | None = None
    fonte: str = ""

    @property
    def ok(self) -> bool:
        return not self.giornaliero.empty


def _versione_yf() -> str:
    try:
        import yfinance as yf
        return yf.__version__
    except Exception:
        return "?"


def _pulisci(df: pd.DataFrame, giornaliero: bool) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits") if c in df]
    df = df[keep]
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if giornaliero:
        # indice = data di seduta (senza ora), fuso della borsa
        df.index = pd.DatetimeIndex(df.index.tz_localize(None).normalize() if df.index.tz is not None
                                    else df.index.normalize())
    else:
        df.index = df.index.tz_convert(ROMA) if df.index.tz is not None else df.index
    df = df[~df.index.duplicated(keep="last")]
    df["Volume"] = df["Volume"].fillna(0)
    return df


def scarica(simbolo: str, intraday: bool = True, eventi: bool = True) -> Serie:
    """Scarica giornaliero e settimanale (tutto lo storico) e 30m (60 giorni,
    limite di Yahoo). Le statistiche usano poi al massimo gli ultimi 10 anni."""
    import yfinance as yf

    s = Serie(simbolo=simbolo, scaricato_alle=ora_roma(),
              fonte=f"Yahoo Finance via yfinance {_versione_yf()} (auto_adjust=False)")
    t = yf.Ticker(simbolo)
    try:
        d = t.history(period="max", interval="1d",
                      auto_adjust=False, actions=True, raise_errors=True)
        s.giornaliero = _pulisci(d, True)
        if s.giornaliero.empty:
            s.errori["giornaliero"] = "Yahoo ha restituito una serie vuota"
    except Exception as e:
        s.errori["giornaliero"] = f"{type(e).__name__}: {str(e)[:160]}"
    try:
        s.meta = dict(t.history_metadata or {})
    except Exception as e:
        s.errori["meta"] = f"{type(e).__name__}"
    try:
        w = t.history(period="max", interval="1wk", auto_adjust=False, raise_errors=True)
        s.settimanale = _pulisci(w, True)
    except Exception as e:
        s.errori["settimanale"] = f"{type(e).__name__}: {str(e)[:160]}"
    if intraday:
        try:
            m = t.history(period="60d", interval="30m", auto_adjust=False, raise_errors=True)
            s.m30 = _pulisci(m, False)
        except Exception as e:
            s.errori["30m"] = f"{type(e).__name__}: {str(e)[:160]}"
    if eventi:
        try:
            s.calendario = dict(t.calendar or {})
        except Exception as e:
            s.errori["calendario"] = f"{type(e).__name__}: {str(e)[:160]}"
        try:
            ed = t.get_earnings_dates(limit=24)
            if ed is not None and len(ed):
                s.date_conti = sorted({pd.Timestamp(x).tz_convert(ROMA).date() if pd.Timestamp(x).tzinfo
                                       else pd.Timestamp(x).date() for x in ed.index})
        except Exception as e:
            s.errori["date_conti"] = f"{type(e).__name__}: {str(e)[:160]}"
    return s


def mercato_aperto(s: Serie, adesso: dt.datetime | None = None) -> bool | None:
    """True/False dal periodo di negoziazione regolare indicato da Yahoo;
    None se l'informazione non c'e'."""
    adesso = adesso or ora_roma()
    try:
        reg = s.meta["currentTradingPeriod"]["regular"]
        start = pd.Timestamp(reg["start"], unit="s", tz="UTC") if not isinstance(reg["start"], pd.Timestamp) else reg["start"]
        end = pd.Timestamp(reg["end"], unit="s", tz="UTC") if not isinstance(reg["end"], pd.Timestamp) else reg["end"]
        now = pd.Timestamp(adesso).tz_convert("UTC")
        return bool(start <= now < end)
    except Exception:
        return None


def ultimo_orario(s: Serie):
    """Orario dell'ultimo prezzo secondo Yahoo (regularMarketTime)."""
    v = s.meta.get("regularMarketTime")
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            return pd.Timestamp(v, unit="s", tz="UTC")
        ts = pd.Timestamp(v)
        return ts if ts.tzinfo else ts.tz_localize("UTC")
    except Exception:
        return None


# ─── TradingView ─────────────────────────────────────────────────────────────

def simbolo_tv_default(simbolo_yahoo: str) -> list[str]:
    """Candidati TradingView per un simbolo Yahoo (il primo che risponde vince).
    Si puo' sempre forzare il simbolo TV nella watchlist (campo "tv")."""
    s = simbolo_yahoo.upper()
    mappa = {"EURUSD=X": ["FX_IDC:EURUSD", "FX:EURUSD"], "GC=F": ["COMEX:GC1!"],
             "FTSEMIB.MI": ["INDEX:FTSEMIB", "TVC:FTMIB"], "^FCHI": ["EURONEXT:PX1", "TVC:CAC40"],
             "^GSPC": ["SP:SPX"], "^STOXX50E": ["TVC:SX5E"]}
    if s in mappa:
        return mappa[s]
    if "." in s:
        base, suf = s.rsplit(".", 1)
        ex = {"MI": ["MIL"], "PA": ["EURONEXT"], "AS": ["EURONEXT"], "BR": ["EURONEXT"],
              "DE": ["XETR"], "F": ["FWB"], "L": ["LSE"], "SW": ["SIX"], "MC": ["BME"]}.get(suf, [])
        return [f"{e}:{base}" for e in ex]
    if s.isalpha():
        return [f"NASDAQ:{s}", f"NYSE:{s}", f"AMEX:{s}"]
    return []


TV_COLONNE = {
    "close": "Chiusura", "RSI": "RSI14", "ATR": "ATR14",
    "SMA20": "SMA20", "SMA50": "SMA50", "SMA100": "SMA100", "SMA200": "SMA200",
    "EMA20": "EMA20", "EMA50": "EMA50",
    "Stoch.K": "StochK", "Stoch.D": "StochD",
    "MACD.macd": "MACD", "MACD.signal": "MACDsig",
    "ADX": "ADX", "ADX+DI": "+DI", "ADX-DI": "-DI",
    "BB.upper": "BBsup", "BB.lower": "BBinf",
}


def screener_tv(candidati: list[str]) -> tuple[str | None, dict, str | None]:
    """Restituisce (ticker TV, {colonna: valore}, errore)."""
    if not candidati:
        return None, {}, "nessun simbolo TradingView noto per questo strumento"
    try:
        from tradingview_screener import Query
    except Exception as e:
        return None, {}, f"libreria tradingview-screener non disponibile ({e})"
    import time
    err = None
    for tentativo in range(3):
        try:
            n, df = Query().select(*TV_COLONNE.keys()).set_tickers(*candidati).get_scanner_data()
            err = None
            break
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:160]}"
            time.sleep(2 * (tentativo + 1))
    if err:
        return None, {}, f"{err} (dopo 3 tentativi)"
    if not n or df is None or df.empty:
        return None, {}, f"lo screener non ha restituito righe per {', '.join(candidati)}"
    ordine = {c: i for i, c in enumerate(candidati)}
    df = df.assign(_o=df["ticker"].map(ordine)).sort_values("_o")
    r = df.iloc[0]
    return r["ticker"], {k: r.get(k) for k in TV_COLONNE}, None
