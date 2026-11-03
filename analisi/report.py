"""
Costruzione del file .md per l'analista: modalita' "titolo" (un solo
strumento, completo di dati grezzi) e "portafoglio" (posizioni e
watchlist, solo sintesi).

Convenzioni del file: separatore decimale "punto", orari Europe/Rome,
"n.d." = non disponibile (sempre seguito dal motivo).
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import dati as D
from . import indicatori as I
from . import statistiche as S
from . import struttura as T

VERSIONE = "1.0"

KAMA_DEFAULT = [(10, 2, 30), (50, 2, 30)]

TIPI_ZAINETTO = {
    "azione": "sì (plusvalenze = redditi diversi)",
    "etc": "sì (plusvalenze = redditi diversi)",
    "obbligazione": "sì (plusvalenze = redditi diversi)",
    "certificato": "sì (plusvalenze = redditi diversi)",
    "etf": "no per le plusvalenze (ETF UCITS: redditi di capitale); le minusvalenze restano compensabili",
}


# ─── formattazione ───────────────────────────────────────────────────────────

def _nan(x) -> bool:
    return x is None or (isinstance(x, (float, np.floating)) and (math.isnan(x) or math.isinf(x)))


def nd(motivo: str = "") -> str:
    return "n.d." + (f" ({motivo})" if motivo else "")


def dec_prezzo(p: float) -> int:
    p = abs(p) if not _nan(p) else 100
    return 5 if p < 1 else 4 if p < 10 else 3 if p < 100 else 2


def decimali_dati(x: pd.Series, massimo: int = 5) -> int:
    """Numero minimo di decimali che rappresenta esattamente i prezzi della
    serie (Yahoo li fornisce come float a precisione singola: tolleranza
    1e-5 relativa). Cosi' non si aggiungono cifre che il dato non ha."""
    v = x.dropna().to_numpy(float)
    if not len(v):
        return 2
    for d in range(0, massimo + 1):
        if np.all(np.abs(v - np.round(v, d)) <= 1e-6 * np.maximum(1.0, np.abs(v))):
            return max(d, 2)
    return massimo


def fp_min(x, dmax: int) -> str:
    """Prezzo con il minimo numero di decimali (da 2 a dmax) che lo
    rappresenta esattamente: 81.58 resta 81.58, 81.583 resta 81.583;
    i valori calcolati (medie ecc.) escono con dmax decimali."""
    if _nan(x):
        return "n.d."
    for d in range(2, dmax + 1):
        if abs(x - round(x, d)) <= 1e-6 * max(1.0, abs(x)):
            return f"{x:.{d}f}"
    return f"{x:.{dmax}f}"


def fp(x, d: int | None = None, rif: float | None = None) -> str:
    """Prezzo con decimali adatti all'ordine di grandezza."""
    if _nan(x):
        return "n.d."
    d = dec_prezzo(rif if rif is not None else x) if d is None else d
    return f"{x:.{d}f}"


def fn(x, d: int = 2, segno: bool = False) -> str:
    if _nan(x):
        return "n.d."
    return f"{x:+.{d}f}" if segno else f"{x:.{d}f}"


def fdata(t) -> str:
    if t is None or (isinstance(t, float) and math.isnan(t)):
        return "n.d."
    return pd.Timestamp(t).strftime("%Y-%m-%d")


def fvol(v) -> str:
    if _nan(v):
        return "n.d."
    return f"{v:,.0f}".replace(",", "")


def dist(prezzo: float, livello: float, atr: float) -> str:
    """Distanza del LIVELLO dal prezzo: (livello/prezzo - 1) in % e in ATR."""
    if _nan(prezzo) or _nan(livello) or _nan(atr) or atr == 0:
        return "n.d."
    return f"{(livello / prezzo - 1) * 100:+.2f}% / {(livello - prezzo) / atr:+.2f} ATR"


def tabella(head: list[str], righe: list[list]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in righe]
    return "\n".join(out)


# ─── configurazione strumento ────────────────────────────────────────────────

def benchmark_default(simbolo: str) -> str | None:
    s = simbolo.upper()
    if s.endswith(".MI"):
        return "FTSEMIB.MI"
    if s.endswith(".PA"):
        return "^FCHI"
    if "." not in s and s.isalpha():
        return "^GSPC"
    return None


@dataclass
class Strumento:
    simbolo: str
    nome: str = ""
    isin: str = ""
    mercato: str = ""
    valuta: str = ""
    tipo: str = ""
    benchmark: str | None = None
    tv: str = ""
    collegati: list = field(default_factory=list)
    posizione: dict = field(default_factory=dict)

    @staticmethod
    def da_dict(d: dict) -> "Strumento":
        return Strumento(
            simbolo=str(d.get("simbolo", "")).strip().upper(),
            nome=d.get("nome", "") or "", isin=d.get("isin", "") or "", mercato=d.get("mercato", "") or "",
            valuta=(d.get("valuta", "") or "").upper(), tipo=(d.get("tipo", "") or "").lower(),
            benchmark=(d.get("benchmark") or "").strip().upper() or None, tv=(d.get("tv") or "").strip(),
            collegati=d.get("collegati") or [], posizione=d.get("posizione") or {},
        )


# ─── cache download ──────────────────────────────────────────────────────────

class Archivio:
    """Evita di riscaricare benchmark e cambi condivisi tra strumenti."""

    def __init__(self):
        self._c: dict[tuple, D.Serie] = {}

    def get(self, simbolo: str, intraday=False, eventi=False) -> D.Serie:
        k = (simbolo, intraday, eventi)
        for (s, i, e), v in self._c.items():
            if s == simbolo and i >= intraday and e >= eventi:
                return v
        self._c[k] = D.scarica(simbolo, intraday=intraday, eventi=eventi)
        return self._c[k]


def fx_eur(arch: Archivio, valuta: str):
    """Cambio EUR/valuta (unita' di valuta per 1 EUR) dall'ultima chiusura Yahoo EUR<valuta>=X."""
    if not valuta or valuta == "EUR":
        return 1.0, None, None
    sym = f"EUR{valuta}=X"
    s = arch.get(sym)
    if not s.ok:
        return None, sym, s.errori.get("giornaliero", "serie vuota")
    return float(s.giornaliero["Close"].iloc[-1]), sym, fdata(s.giornaliero.index[-1])


# ─── analisi di uno strumento ────────────────────────────────────────────────

class Analisi:
    def __init__(self, st: Strumento, cfg: dict, arch: Archivio, intraday: bool):
        self.st, self.cfg, self.arch = st, cfg, arch
        self.zz_mult = float(cfg.get("zigzag_atr") or 1.5)
        self.kama_p = [tuple(int(v) for v in k) for k in (cfg.get("kama") or KAMA_DEFAULT)]
        self.s = arch.get(st.simbolo, intraday=intraday, eventi=True)
        self.ok = self.s.ok and len(self.s.giornaliero) >= 30
        if self.s.ok and not self.ok:
            self.s.errori["giornaliero"] = f"storico insufficiente: {len(self.s.giornaliero)} sedute (minimo 30)"
        if not self.ok:
            return
        self.df = self.s.giornaliero
        self.ind = I.calcola_tutti(self.df, self.kama_p)
        self.c = self.df["Close"]
        self.atr = self.ind["ATR14"]
        self.ultimo = float(self.c.iloc[-1])
        ult = self.df.iloc[-260:]
        self.dp = decimali_dati(pd.concat([ult["Open"], ult["High"], ult["Low"], ult["Close"]]))
        self.atr_now = float(self.atr.iloc[-1]) if not _nan(self.atr.iloc[-1]) else None
        self.oggi = self.df.index[-1]
        self.aperto = D.mercato_aperto(self.s)
        self.incompleta = bool(self.aperto) and fdata(self.oggi) == D.ora_roma().strftime("%Y-%m-%d")
        self.pivot = T.zigzag(self.df, self.atr, self.zz_mult)
        self.pivot_magg = T.zigzag(self.df, self.atr, max(3.0, 2 * self.zz_mult))
        self.valuta = st.valuta or (self.s.meta.get("currency") or "").upper()
        d10 = S.finestra_10_anni(self.df)
        self.d10, self.atr10, self.rsi10 = d10, self.atr.loc[d10.index], self.ind["RSI14"].loc[d10.index]
        anno = self.oggi - pd.DateOffset(months=12)
        self.gap12 = T.trova_gap(self.df, self.atr, self.ind["Vol20"], 0.5, dal=anno)
        self.gap10_1atr = T.trova_gap(d10, self.atr10, self.ind["Vol20"].loc[d10.index], 1.0)
        self.dividendi = self.df.loc[self.df.get("Dividends", pd.Series(dtype=float)) > 0, "Dividends"] \
            if "Dividends" in self.df else pd.Series(dtype=float)
        self.split = self.df.loc[self.df["Stock Splits"] > 0, "Stock Splits"] \
            if "Stock Splits" in self.df else pd.Series(dtype=float)

    # -- utilita'
    def v(self, col: str, k: int = 0):
        s = self.ind[col]
        return float(s.iloc[-1 - k]) if len(s) > k and not _nan(s.iloc[-1 - k]) else None

    def d(self, livello) -> str:
        return dist(self.ultimo, livello, self.atr_now)

    def p(self, x) -> str:
        return fp_min(x, self.dp)

    def vol_rel(self, k: int = 0):
        vol = self.df["Volume"]
        v20 = self.ind["Vol20"]
        if len(vol) < k + 2 or _nan(v20.iloc[-2 - k]) or v20.iloc[-2 - k] == 0:
            return None
        return float(vol.iloc[-1 - k] / v20.iloc[-2 - k])

    def pref(self) -> str:
        return ""

    # ─── sezioni ─────────────────────────────────────────────────────────────

    def sez_anagrafica(self, n: int) -> str:
        st, s, m = self.st, self.s, self.s.meta
        tipo = st.tipo or (m.get("instrumentType") or "").lower()
        zain = TIPI_ZAINETTO.get(st.tipo, nd("tipo non indicato nella watchlist") if not st.tipo else "da verificare: tipo non standard")
        ult = self.df.iloc[-260:]
        attese = pd.bdate_range(ult.index[0], ult.index[-1])
        mancanti = [d for d in attese if d not in ult.index]
        vol0 = int((ult["Volume"] == 0).sum())
        righe = [
            ["Nome", st.nome or m.get("longName") or m.get("shortName") or nd("non indicato")],
            ["Simbolo (Yahoo)", st.simbolo],
            ["ISIN", st.isin or nd("non indicato nella watchlist")],
            ["Mercato", st.mercato or f"{m.get('fullExchangeName') or m.get('exchangeName') or nd()} (da Yahoo)"],
            ["Valuta", f"{self.valuta or nd()}" + ("" if st.valuta else " (da Yahoo)")],
            ["Tipo", st.tipo or f"{tipo or nd()} (da Yahoo)"],
            ["Compensabile con lo zainetto fiscale", zain],
            ["Ultima seduta presente", fdata(self.oggi) + (" — barra INCOMPLETA (mercato aperto)" if self.incompleta else "")],
            ["Storico giornaliero", f"{len(self.df)} sedute, dal {fdata(self.df.index[0])}"],
            ["Giorni lun-ven senza barra (ultime 260 sedute)",
             f"{len(mancanti)}" + (f": {', '.join(fdata(x) for x in mancanti[:12])}" + (" …" if len(mancanti) > 12 else "") if mancanti else "")
             + " (include le festività di borsa: non distinguibili senza calendario ufficiale)"],
            ["Sedute con volume 0 (ultime 260)", str(vol0)],
            ["Fonte", f"{s.fonte}, scaricato {D.fmt_ora(s.scaricato_alle)}"],
        ]
        err = {k: v for k, v in s.errori.items()}
        if err:
            righe.append(["Errori fonte", "; ".join(f"{k}: {v}" for k, v in err.items())])
        return f"## {n}. Anagrafica e qualità del dato\n\n" + tabella(["Campo", "Valore"], righe)

    def sez_prezzo(self, n: int) -> str:
        r = self.df.iloc[-1]
        prev = float(self.c.iloc[-2]) if len(self.c) > 1 else None
        ora = D.ultimo_orario(self.s)
        righe = [
            ["Ultimo", self.p(self.ultimo) + f" {self.valuta}"],
            ["Orario ultimo prezzo (Yahoo regularMarketTime)", D.fmt_ora(ora) if ora is not None else nd("assente nei metadati")],
            ["Seduta", fdata(self.oggi) + (" (in corso)" if self.incompleta else "")],
            ["Apertura / Massimo / Minimo", f"{self.p(r['Open'])} / {self.p(r['High'])} / {self.p(r['Low'])}"],
            ["Chiusura precedente", f"{self.p(prev)} ({fdata(self.df.index[-2])})" if prev else nd()],
            ["Variazione", f"{self.ultimo - prev:+.{self.dp}f} ({(self.ultimo / prev - 1) * 100:+.2f}%)" if prev else nd()],
            ["Volume", fvol(r["Volume"]) + (" (parziale)" if self.incompleta else "")],
            ["Volume relativo (vol / media 20 sedute precedenti)", fn(self.vol_rel()) + (" (su volume parziale)" if self.incompleta else "")],
            ["Stato mercato alla generazione", {True: "APERTO — l'ultima barra giornaliera è incompleta", False: "chiuso",
                                               None: nd("periodo di negoziazione assente nei metadati Yahoo")}[self.aperto]],
        ]
        return f"## {n}. Prezzo\n\n" + tabella(["Campo", "Valore"], righe)

    def sez_indicatori(self, n: int, sintesi: bool = False) -> str:
        medie = ["SMA20", "SMA50", "SMA100", "SMA200", "EMA20", "EMA50"] + [f"KAMA({a},{b},{c})" for a, b, c in self.kama_p]
        righe = []
        for m in medie:
            v0, v5, v20 = self.v(m), self.v(m, 5), self.v(m, 20)
            pend = (v0 / v5 - 1) * 100 if v0 and v5 else None
            righe.append([m, self.p(v0), self.p(v5), self.p(v20),
                          dist(v0, self.ultimo, self.atr_now) if v0 else "n.d.", fn(pend, 2, True) + "%" if pend is not None else "n.d."])
        out = [f"## {n}. Indicatori (barre giornaliere; 'k sedute fa' = k barre prima dell'ultima)\n",
               "Medie mobili — distanza = prezzo rispetto alla media; pendenza = variazione % della media in 5 sedute.\n",
               tabella(["Media", "Attuale", "5 sedute fa", "20 sedute fa", "Distanza prezzo", "Pendenza 5s"], righe)]
        osc = [("RSI14", "RSI 14", 2), ("StochK", "Stoc. %K (14,3)", 2), ("StochD", "Stoc. %D (3)", 2),
               ("MACD", "MACD (12,26)", 4), ("MACDsig", "Segnale MACD (9)", 4), ("MACDhist", "Istogramma MACD", 4),
               ("ADX", "ADX 14", 2), ("+DI", "+DI 14", 2), ("-DI", "-DI 14", 2),
               ("ATR14", f"ATR 14 ({self.valuta})", self.dp), ("ATR%", "ATR 14 % del prezzo", 2),
               ("BBsup", "Bollinger superiore", self.dp), ("BBbase", "Bollinger base (SMA20)", self.dp),
               ("BBinf", "Bollinger inferiore", self.dp), ("BB%B", "Bollinger %B", 3), ("BBlarg%", "Bollinger larghezza %", 2),
               ("Vol20", "Volume medio 20", 0), ("Vol50", "Volume medio 50", 0)]
        r2 = [[nome, fn(self.v(col), d), fn(self.v(col, 5), d), fn(self.v(col, 20), d)] for col, nome, d in osc]
        out += ["\nOscillatori, volatilità e volumi:\n", tabella(["Indicatore", "Attuale", "5 sedute fa", "20 sedute fa"], r2)]
        if self.incompleta:
            out.append("\nNota: i valori 'Attuale' usano la barra di oggi ancora incompleta.")
        return "\n".join(out)

    def sez_struttura(self, n: int, n_swing: int = 12) -> str:
        piv = self.pivot[-n_swing:]
        righe = [[fdata(p.data), "massimo" if p.tipo == "H" else "minimo", self.p(p.prezzo), p.etichetta or "—",
                  "sì" if p.confermato else "provvisorio", self.d(p.prezzo)] for p in piv]
        out = [f"## {n}. Struttura\n",
               f"Punti di swing (ZigZag, soglia {self.zz_mult} × ATR14), ultimi {len(piv)}; etichetta rispetto allo swing precedente dello stesso tipo "
               "(HH massimo crescente, LH massimo decrescente, HL minimo crescente, LL minimo decrescente):\n",
               tabella(["Data", "Tipo", "Prezzo", "Etichetta", "Confermato", "Distanza dal prezzo"], righe) if righe else nd("swing insufficienti")]
        hs = [p for p in self.pivot if p.tipo == "H" and p.etichetta][-4:]
        ls = [p for p in self.pivot if p.tipo == "L" and p.etichetta][-4:]
        out.append(f"\nSequenza ultimi massimi: {' → '.join(p.etichetta for p in hs) or 'n.d.'}; "
                   f"ultimi minimi: {' → '.join(p.etichetta for p in ls) or 'n.d.'}.")
        hl = next((p for p in reversed(self.pivot) if p.etichetta == "HL"), None)
        lh = next((p for p in reversed(self.pivot) if p.etichetta == "LH"), None)
        out.append(f"Ultimo minimo crescente (HL): {f'{self.p(hl.prezzo)} del {fdata(hl.data)}, distanza {self.d(hl.prezzo)}' if hl else 'nessuno nello storico'}.")
        out.append(f"Ultimo massimo decrescente (LH): {f'{self.p(lh.prezzo)} del {fdata(lh.data)}, distanza {self.d(lh.prezzo)}' if lh else 'nessuno nello storico'}.")
        est = T.estremi_periodo(self.df, self.oggi)
        r2 = []
        for k, e in est.items():
            if e is None:
                r2.append([k, "n.d.", "", "n.d.", "", ""])
            else:
                r2.append([k, self.p(e["max"]), fdata(e["data_max"]), self.p(e["min"]), fdata(e["data_min"]), e["n"]])
        out += ["\nMassimi e minimi (finestre di calendario fino all'ultima seduta):\n",
                tabella(["Periodo", "Massimo", "Data", "Minimo", "Data", "n sedute"], r2)]
        return "\n".join(out)

    def livelli(self, max_per_lato: int = 8) -> list[dict]:
        lv = []
        if self.atr_now:
            da = self.oggi - pd.DateOffset(years=3)
            piv = [p for p in self.pivot if p.data >= da]
            for g in T.gruppi_livelli(piv, 0.5 * self.atr_now):
                if abs(g["prezzo"] / self.ultimo - 1) > 0.30:
                    continue
                det = f"{g['tocchi']} {'tocco' if g['tocchi'] == 1 else 'tocchi'}: {', '.join(fdata(x) for x in g['date'][-4:])}" \
                    + (" e precedenti" if g["tocchi"] > 4 else "")
                if g["tocchi"] > 1:
                    det += f"; da {self.p(g['min'])} a {self.p(g['max'])}"
                lv.append({"prezzo": g["prezzo"], "tipo": "swing", "descr": det})
        for g in self.gap12:
            if g["chiuso_dopo"] is None:
                lv.append({"prezzo": g["da"] if g["direzione"] == "rialzo" else g["a"], "tipo": "gap aperto",
                           "descr": f"gap al {g['direzione']} del {fdata(g['data'])}, {self.p(g['da'])}–{self.p(g['a'])}"})
        for t in T.numeri_tondi(self.ultimo):
            lv.append({"prezzo": t, "tipo": "numero tondo", "descr": f"passo {T.passo_tondo(self.ultimo):g}"})
        sopra = sorted([x for x in lv if x["prezzo"] > self.ultimo], key=lambda x: x["prezzo"])[:max_per_lato]
        sotto = sorted([x for x in lv if x["prezzo"] <= self.ultimo], key=lambda x: -x["prezzo"])[:max_per_lato]
        tutti = sopra + sotto
        for x in tutti:
            x["lato"] = "resistenza" if x["prezzo"] > self.ultimo else "supporto"
        return sorted(tutti, key=lambda x: abs(x["prezzo"] - self.ultimo))

    def sez_livelli(self, n: int, max_per_lato: int = 6) -> str:
        lv = self.livelli(max_per_lato)
        righe = [[x["lato"], self.p(x["prezzo"]), self.d(x["prezzo"]), x["tipo"], x["descr"]] for x in lv]
        return (f"## {n}. Livelli (ordinati per distanza dal prezzo {self.p(self.ultimo)})\n\n"
                f"Gruppi di punti di swing confermati degli ultimi 3 anni entro ±0.5 ATR14 (prezzo = media del gruppo, solo entro ±30%); "
                f"gap aperti degli ultimi 12 mesi (bordo più vicino alla barra precedente il gap); numeri tondi entro ±10%. "
                f"Massimo {max_per_lato} livelli per lato.\n\n"
                + (tabella(["Lato", "Prezzo", "Distanza", "Tipo", "Dettaglio"], righe) if righe else nd("nessun livello")))

    def _eventi_gap(self, g) -> str:
        i = g["i"]
        d, prev = self.df.index[i], self.df.index[i - 1]
        note = []
        if d in self.dividendi.index:
            note.append(f"stacco dividendo {self.dividendi.loc[d]:g}")
        if self.s.date_conti:
            if any(prev.date() <= x <= d.date() for x in self.s.date_conti):
                note.append("conti")
        elif "date_conti" in self.s.errori:
            note.append("date conti n.d.")
        return ", ".join(note) or "—"

    def sez_gap(self, n: int, solo_aperti: bool = False) -> str:
        gaps = [g for g in self.gap12 if not solo_aperti or g["chiuso_dopo"] is None]
        righe = [[fdata(g["data"]), g["direzione"], f"{self.p(g['da'])}–{self.p(g['a'])}", fn(g["ampiezza_atr"]),
                  fn(g["vol_rel"]), f"sì, dopo {g['chiuso_dopo']} sedute" if g["chiuso_dopo"] is not None else "no",
                  self._eventi_gap(g)] for g in gaps]
        tit = "Gap aperti degli ultimi 12 mesi" if solo_aperti else "Gap degli ultimi 12 mesi"
        return (f"## {n}. {tit} (ampiezza > 0.5 ATR14 della seduta precedente)\n\n"
                + (tabella(["Data", "Direzione", "Intervallo", "Ampiezza ATR", "Vol. rel.", "Chiuso", "Coincide con"], righe)
                   if righe else "Nessuno.")
                + ("\n\nDate conti: " + (nd(self.s.errori['date_conti']) if 'date_conti' in self.s.errori else
                                          ("fonte Yahoo (get_earnings_dates)" if self.s.date_conti else "nessuna data restituita da Yahoo"))))

    def sez_candele(self, n: int) -> str:
        w = self.df.iloc[-10:]
        righe = []
        for k in range(len(w)):
            r = w.iloc[k]
            pos = len(self.df) - len(w) + k
            a = self.atr.iloc[pos]
            rng = r["High"] - r["Low"]
            cpos = (r["Close"] - r["Low"]) / rng * 100 if rng > 0 else None
            body = (r["Close"] - r["Open"]) / a if a else None
            us = (r["High"] - max(r["Open"], r["Close"])) / a if a else None
            ls = (min(r["Open"], r["Close"]) - r["Low"]) / a if a else None
            v20 = self.ind["Vol20"].iloc[pos - 1]
            rv = r["Volume"] / v20 if v20 and not _nan(v20) else None
            righe.append([fdata(w.index[k]), self.p(r["Open"]), self.p(r["High"]), self.p(r["Low"]), self.p(r["Close"]),
                          fvol(r["Volume"]), fn(cpos, 0), fn(body, 2, True), fn(us), fn(ls), fn(rv)])
        return (f"## {n}. Ultime 10 candele giornaliere\n\nPos. chiusura = (C−L)/(H−L)·100; corpo = (C−O)/ATR14 (segno + rialzista); "
                "ombre in ATR14; vol. rel. = volume / media 20 sedute precedenti.\n\n"
                + tabella(["Data", "O", "H", "L", "C", "Volume", "Pos. chiusura %", "Corpo ATR", "Ombra sup ATR", "Ombra inf ATR", "Vol. rel."], righe))

    def sez_figure(self, n: int) -> str:
        out = [f"## {n}. Figure candidate (fatti geometrici, senza giudizio)\n"]
        for tipo, nome in (("H", "Doppio massimo"), ("L", "Doppio minimo")):
            f = T.doppi(self.pivot, self.df, self.atr, tipo)
            if not f:
                out.append(f"- **{nome}**: nessuna terna di swing consecutivi con estremi entro 1 ATR14 nelle ultime 250 sedute.")
                continue
            p1, mid, p2 = f["p1"], f["mid"], f["p2"]
            rel = "più alto" if f["diff"] > 0 else "più basso" if f["diff"] < 0 else "uguale"
            rotto = f"sì, chiusura del {fdata(f['rotto_in_chiusura'])}" if f["rotto_in_chiusura"] is not None else "no"
            out.append(f"- **{nome}**: primo {self.p(p1.prezzo)} ({fdata(p1.data)}), intermedio {self.p(mid.prezzo)} ({fdata(mid.data)}), "
                       f"secondo {self.p(p2.prezzo)} ({fdata(p2.data)}{'' if p2.confermato else ', provvisorio'}); "
                       f"il secondo è {rel} del primo di {fn(abs(f['diff']), self.dp)} ({fn(abs(f['diff_atr']))} ATR); "
                       f"livello intermedio rotto in chiusura: {rotto}; distanza dell'intermedio dal prezzo: {self.d(mid.prezzo)}; "
                       f"altezza della figura {fn(f['altezza'], self.dp)}.")
        r = T.rettangolo(self.df, self.atr)
        if r:
            rott = f"sì, al {r['rottura'][0]} con la chiusura del {fdata(r['rottura'][1])}" if r["rottura"] else "no"
            out.append(f"- **Base/rettangolo** (≥15 sedute con altezza ≤ 4 ATR14): {fdata(r['inizio'])} → {fdata(r['fine'])} "
                       f"({r['sedute']} sedute{', ancora in corso' if r['in_corso'] else ''}); estremi {self.p(r['inf'])}–{self.p(r['sup'])} "
                       f"(altezza {fn(r['altezza_atr'])} ATR); tocchi (entro 0.25 ATR) superiore {r['tocchi_sup']}, inferiore {r['tocchi_inf']}; "
                       f"rottura in chiusura: {rott}; obiettivi di misura: rialzo {self.p(r['obiettivo_rialzo'])} ({self.d(r['obiettivo_rialzo'])}), "
                       f"ribasso {self.p(r['obiettivo_ribasso'])} ({self.d(r['obiettivo_ribasso'])}).")
        else:
            out.append("- **Base/rettangolo**: nessuna finestra di ≥15 sedute con altezza ≤ 4 ATR14 terminata nelle ultime 60 sedute.")
        zzm = max(3.0, 2 * self.zz_mult)
        fibs = T.fibonacci(self.pivot_magg)
        if not fibs:
            out.append("- **Fibonacci**: n.d. (meno di due swing maggiori).")
        for fb in fibs:
            a, b = fb["da"], fb["a"]
            lv = "; ".join(f"{r * 100:.1f}% = {self.p(v)} ({self.d(v)})" for r, v in fb["livelli"].items())
            stato = "completato" if b.confermato else "in corso (estremo finale provvisorio)"
            out.append(f"- **Fibonacci, swing maggiore {stato}** (ZigZag {zzm} × ATR14): "
                       f"{'minimo' if a.tipo == 'L' else 'massimo'} {self.p(a.prezzo)} ({fdata(a.data)}) → "
                       f"{'massimo' if b.tipo == 'H' else 'minimo'} {self.p(b.prezzo)} ({fdata(b.data)}), al {fb['direzione']}. "
                       f"Ritracciamenti: {lv}.")
        return "\n".join(out)

    def sez_statistiche(self, n: int, sintesi: bool = False) -> str:
        d = self.d10
        out = [f"## {n}. Statistiche storiche (ultimi {len(d)} sedute, dal {fdata(d.index[0])} al {fdata(d.index[-1])}; max 10 anni)\n"]
        vol = S.volatilita(d["Close"])
        out.append("Deviazione standard dei rendimenti giornalieri (chiusura su chiusura, %): "
                   + "; ".join(f"{k} sedute = {fn(vol[k][0])}% (n={vol[k][1]})" for k in (20, 60, 250)) + ".")
        out.append(f"Giorni con variazione oltre ±3%: {fn(vol['oltre3'][0])}% (oltre +3%: {fn(vol['su3'])}%, oltre −3%: {fn(vol['giu3'])}%; n={vol['oltre3'][1]}).")
        esc = S.escursioni(d, self.atr10)
        hz_list = (10,) if sintesi else S.ORIZZONTI
        righe = []
        for hz in hz_list:
            e = esc.get(hz)
            if not e:
                continue
            righe.append([f"{hz}s rialzo %", *[fn(x) for x in e["su_pct"]], e["n"]])
            righe.append([f"{hz}s ribasso %", *[fn(x) for x in e["giu_pct"]], e["n"]])
            if e["su_atr"] is not None:
                righe.append([f"{hz}s rialzo ATR", *[fn(x) for x in e["su_atr"]], e["n_atr"]])
                righe.append([f"{hz}s ribasso ATR", *[fn(x) for x in e["giu_atr"]], e["n_atr"]])
        out += ["\nEscursione massima entro h sedute (massimo dei massimi / minimo dei minimi successivi rispetto alla chiusura di partenza):\n",
                tabella(["Orizzonte"] + [f"p{p}" for p in S.PERCENTILI] + ["n"], righe)]
        if not sintesi:
            cg = S.chiusura_gap(self.gap10_1atr, len(d))
            out.append(f"\nGap > 1 ATR14 nel periodo: {len(self.gap10_1atr)}. Chiusi entro: "
                       + "; ".join(f"{hz} sedute {fn(cg[hz][0], 1)}% (n={cg[hz][1]})" for hz in S.ORIZZONTI) + ".")
            ga = S.dopo_giorni_ampi(d, self.atr10)
            r2 = []
            for nome, k in (("dopo > +2 ATR", "su"), ("dopo < −2 ATR", "giu")):
                for hz in S.ORIZZONTI:
                    x = ga[k][hz]
                    r2.append([nome, f"{hz}s", x["n"], fn(x.get("media"), 2, True), fn(x.get("mediana"), 2, True), fn(x.get("pos"), 1)])
            out += ["\nRendimenti (chiusura su chiusura, %) dopo sedute con variazione oltre ±2 ATR14 (della seduta precedente); "
                    "gli eventi ravvicinati si sovrappongono:\n", tabella(["Evento", "Orizzonte", "n", "Media %", "Mediana %", "% positivi"], r2)]
            rr = S.dopo_rsi(d["Close"], self.rsi10)
            r3 = [[k, x["n"], fn(x.get("media"), 2, True), fn(x.get("mediana"), 2, True), fn(x.get("pos"), 1)]
                  for k, x in (("RSI entra sopra 70", rr["sopra70"]), ("RSI entra sotto 30", rr["sotto30"]))]
            out += ["\nRendimenti a 10 sedute dal giorno in cui l'RSI14 entra nella zona:\n",
                    tabella(["Evento", "n", "Media %", "Mediana %", "% positivi"], r3)]
        return "\n".join(out)

    def sez_forza_relativa(self, n: int) -> str:
        bm = self.st.benchmark or benchmark_default(self.st.simbolo)
        if not bm:
            return f"## {n}. Forza relativa\n\n{nd('nessun benchmark indicato nella watchlist')}"
        b = self.arch.get(bm)
        if not b.ok:
            return f"## {n}. Forza relativa vs {bm}\n\n{nd(b.errori.get('giornaliero', 'serie vuota'))}"
        bc = b.giornaliero["Close"]
        righe = []
        for nome, off in (("1 settimana", pd.DateOffset(days=7)), ("1 mese", pd.DateOffset(months=1)), ("3 mesi", pd.DateOffset(months=3))):
            r1, d1 = S.rendimento_periodo(self.c, off)
            r2, d2 = S.rendimento_periodo(bc, off)
            diff = r1 - r2 if r1 is not None and r2 is not None else None
            rap = ((1 + r1 / 100) / (1 + r2 / 100) - 1) * 100 if diff is not None else None
            righe.append([nome, fn(r1, 2, True), fdata(d1), fn(r2, 2, True), fdata(d2), fn(diff, 2, True), fn(rap, 2, True)])
        return (f"## {n}. Forza relativa vs {bm} (ultima chiusura benchmark {fdata(bc.index[-1])})\n\n"
                "Rendimento dall'ultima chiusura alla chiusura di riferimento (ultima seduta ≤ data − periodo). "
                "Valute non convertite.\n\n"
                + tabella(["Periodo", "Strumento %", "Rif. strum.", "Benchmark %", "Rif. bench.", "Differenza pp", "Rapporto %"], righe))

    def sez_collegati(self, n: int, righe_max: int = 6) -> str:
        if not self.st.collegati:
            return f"## {n}. Strumenti collegati\n\nNessuno indicato nella watchlist."
        out = [f"## {n}. Strumenti collegati\n"]
        loc = self.c
        for cg in self.st.collegati:
            sym = str(cg.get("simbolo", "")).upper()
            tipo = (cg.get("tipo") or "").lower()
            fx_sym = (cg.get("cambio") or "").upper()
            x = self.arch.get(sym)
            if not x.ok:
                out.append(f"- {sym}: {nd(x.errori.get('giornaliero', 'serie vuota'))}")
                continue
            xc = x.giornaliero["Close"]
            fx = None
            if fx_sym:
                f = self.arch.get(fx_sym)
                if not f.ok:
                    out.append(f"- {sym}: cambio {fx_sym} {nd(f.errori.get('giornaliero', 'serie vuota'))}")
                    continue
                fx = f.giornaliero["Close"]
            comuni = loc.index.intersection(xc.index)
            if fx is not None:
                comuni = comuni.intersection(fx.index)
            comuni = comuni[-25:]
            if not len(comuni):
                out.append(f"- {sym}: nessuna data in comune")
                continue
            ora = D.ultimo_orario(x)
            hdr = (f"**{cg.get('nome') or sym}** ({sym}, {x.meta.get('currency', '?')}, ultimo {fp(xc.iloc[-1])} del {fdata(xc.index[-1])}, "
                   f"orario Yahoo {D.fmt_ora(ora) if ora is not None else 'n.d.'})")
            if fx is not None:
                hdr += f"; cambio {fx_sym} ultimo {fx.iloc[-1]:.5f} del {fdata(fx.index[-1])}"
            out.append(hdr + "\n")
            sel = list(comuni[-(righe_max - 1):])
            if len(comuni) > 20:
                sel = [comuni[-21]] + sel   # 20 sedute fa, per vedere la stabilita' del rapporto
            righe = []
            if tipo == "adr":
                rap = float(cg.get("rapporto") or 0)
                if rap <= 0:
                    out.append(nd("rapporto ADR non indicato (azioni per 1 ADR)"))
                    continue
                for d0 in sel:
                    implicito = xc[d0] / rap / (fx[d0] if fx is not None else 1)
                    righe.append([fdata(d0), fp(xc[d0]), fn(fx[d0], 5) if fx is not None else "—", self.p(implicito),
                                  self.p(loc[d0]), fn((loc[d0] / implicito - 1) * 100, 2, True)])
                out.append(f"Rapporto: 1 ADR = {rap:g} azioni. Prezzo implicito dell'azione = ADR / {rap:g}"
                           + (f" / {fx_sym}" if fx is not None else "") + ". Chiusure giornaliere non simultanee "
                           "(Parigi/Milano 17:30, New York 22:00 ora italiana): lo scarto include il movimento tra i due orari.\n")
                out.append(tabella(["Data", f"{sym}", fx_sym or "cambio", "Implicito", self.st.simbolo, "Premio locale %"], righe))
            else:
                for d0 in sel:
                    sott = xc[d0] / (fx[d0] if fx is not None else 1)
                    righe.append([fdata(d0), self.p(loc[d0]), fp(xc[d0]), fn(fx[d0], 5) if fx is not None else "—",
                                  fp(sott), f"{loc[d0] / sott:.6f}"])
                ult = righe[-1][-1]
                out.append(f"Rapporto implicito R = prezzo {self.st.simbolo} / (sottostante" + (f" / {fx_sym})" if fx is not None else ")")
                           + f". Per riconvertire un livello del sottostante: livello_{self.st.simbolo} = livello_{sym}"
                           + (f" / {fx_sym}" if fx is not None else "") + f" × R (ultimo R = {ult}). Chiusure non simultanee.\n")
                out.append(tabella(["Data", self.st.simbolo, sym, fx_sym or "cambio", "Sottostante conv.", "R"], righe))
        return "\n".join(out)

    def sez_eventi(self, n: int, sintesi: bool = False) -> str:
        cal, err = self.s.calendario, self.s.errori
        out = [f"## {n}. Eventi (fonte: Yahoo Finance via yfinance Ticker.calendar, letto {D.fmt_ora(self.s.scaricato_alle)})\n"]
        if "calendario" in err:
            out.append(f"- Calendario: {nd(err['calendario'])}")
        else:
            ed = cal.get("Earnings Date")
            out.append(f"- Prossimi conti: {', '.join(str(x) for x in ed) if ed else nd('Yahoo non riporta la data')}")
            exd = cal.get("Ex-Dividend Date")
            pay = cal.get("Dividend Date")
            out.append(f"- Data di stacco dividendo indicata: {exd if exd else nd('Yahoo non riporta la data')}"
                       + (f" (pagamento {pay})" if pay else "")
                       + (" — data passata: è l'ultimo stacco noto, non il prossimo" if exd and pd.Timestamp(exd) < pd.Timestamp(D.ora_roma().date()) else ""))
            out.append("- Importo del prossimo dividendo: " + nd("Yahoo non lo fornisce nel calendario"))
        div = self.dividendi[self.dividendi.index > self.oggi - pd.DateOffset(years=3)]
        out.append("- Dividendi staccati (ultimi 3 anni, data di stacco: importo): "
                   + ("; ".join(f"{fdata(d)}: {v:g}" for d, v in div.items()) if len(div) else "nessuno nella serie Yahoo"))
        out.append("- Split nello storico: " + ("; ".join(f"{fdata(d)}: {v:g}" for d, v in self.split.items()) if len(self.split) else "nessuno"))
        out.append("- Nota: prezzi NON aggiustati per i dividendi; il giorno di stacco la serie mostra il salto reale.")
        return "\n".join(out)

    def posizione_numeri(self) -> dict | None:
        p = self.st.posizione or {}
        q = p.get("quantita")
        if not q:
            return None
        fx, fx_sym, fx_data = fx_eur(self.arch, self.valuta)
        cv = q * self.ultimo
        res = {"q": float(q), "carico": p.get("carico"), "stop": p.get("stop"), "target": p.get("target"),
               "uscita": p.get("uscita"), "cv": cv, "cv_eur": cv / fx if fx else None, "fx": fx, "fx_sym": fx_sym, "fx_data": fx_data}
        return res

    def sez_posizione(self, n: int, totali: dict | None) -> str:
        x = self.posizione_numeri()
        if not x:
            return f"## {n}. Posizione\n\nNessuna posizione indicata."
        out = [f"## {n}. Posizione\n"]
        car, stop, tgt = x["carico"], x["stop"], x["target"]
        righe = [["Quantità", f"{x['q']:g}"],
                 ["Prezzo di carico", self.p(car) if car else nd("non indicato")],
                 ["Controvalore", f"{x['cv']:.2f} {self.valuta}" + (f" = {x['cv_eur']:.2f} EUR (cambio {x['fx_sym']} {x['fx']:.5f} del {x['fx_data']})"
                                                                     if x["fx_sym"] and x["cv_eur"] else "")],
                 ]
        if car:
            righe.append(["Risultato dal carico", f"{(self.ultimo / car - 1) * 100:+.2f}% ({(self.ultimo - car) * x['q']:+.2f} {self.valuta})"])
        if totali and x["cv_eur"]:
            righe.append(["Peso sul totale investito", f"{x['cv_eur'] / totali['investito'] * 100:.2f}%" if totali["investito"] else "n.d."])
            righe.append(["Peso sul conto (investito + liquidità)", f"{x['cv_eur'] / totali['conto'] * 100:.2f}%"
                          if totali.get("conto") else nd("liquidità non indicata")])
        righe.append(["Stop", f"{self.p(stop)} — distanza {self.d(stop)}" if stop else nd("non indicato")])
        righe.append(["Target", f"{self.p(tgt)} — distanza {self.d(tgt)}" if tgt else nd("non indicato")])
        if stop and tgt and self.ultimo != stop:
            rr = (tgt - self.ultimo) / (self.ultimo - stop)
            righe.append(["Rendimento/rischio dal prezzo attuale", f"{rr:.2f} = (target − prezzo) / (prezzo − stop)"])
        if x["uscita"]:
            try:
                du = pd.Timestamp(x["uscita"])
                sed = len(pd.bdate_range(self.oggi + pd.Timedelta(days=1), du))
                righe.append(["Data di uscita pianificata", f"{fdata(du)} — {sed} giorni lun-ven dopo l'ultima seduta (festività non escluse)"])
            except Exception:
                righe.append(["Data di uscita pianificata", f"{x['uscita']} (formato non riconosciuto)"])
        out.append(tabella(["Campo", "Valore"], righe))
        return "\n".join(out)

    def sez_tv(self, n: int) -> str:
        cand = list(dict.fromkeys(([self.st.tv] if self.st.tv else []) + D.simbolo_tv_default(self.st.simbolo)))
        tk, vals, err = D.screener_tv(cand)
        out = [f"## {n}. Controllo incrociato con lo screener TradingView (letto {D.fmt_ora(D.ora_roma())})\n"]
        if err:
            out.append(nd(err))
            return "\n".join(out)
        righe = []
        for col_tv, col in D.TV_COLONNE.items():
            tv = vals.get(col_tv)
            mio = self.ultimo if col == "Chiusura" else self.v(col)
            if _nan(tv) or mio is None:
                righe.append([col, fn(tv, 4), fn(mio, 4), "n.d.", "n.d."])
                continue
            righe.append([col, fn(tv, 4), fn(mio, 4), fn(mio - tv, 4, True), fn((mio / tv - 1) * 100 if tv else None, 3, True)])
        out.append(f"Ticker {tk}; TradingView = sua barra giornaliera corrente, Calcolato = ultima barra Yahoo del {fdata(self.oggi)}. "
                   "A mercato aperto gli scarti riflettono soprattutto la differenza dell'ultimo prezzo.\n")
        out.append(tabella(["Indicatore", "TradingView", "Calcolato", "Scarto", "Scarto %"], righe))
        return "\n".join(out)

    def sez_grezzi(self, n: int) -> str:
        dp = self.dp

        def riga(t, r, fmt_idx):
            return f"{fmt_idx(t)},{fp_min(r['Open'], dp)},{fp_min(r['High'], dp)},{fp_min(r['Low'], dp)},{fp_min(r['Close'], dp)},{int(r['Volume'])}"

        def csv(df, fmt_idx, intest="data"):
            rows = [f"{intest},open,high,low,close,volume"] + [riga(t, r, fmt_idx) for t, r in df.iterrows()]
            return "```csv\n" + "\n".join(rows) + "\n```"

        out = [f"## {n}. Dati grezzi (prezzi non aggiustati, {self.valuta}; ogni prezzo con i decimali che ha nella fonte, max {dp})\n"]
        g = self.df.iloc[-260:]
        out += [f"Giornaliero, ultime {len(g)} sedute:\n", csv(g, fdata)]
        w = self.s.settimanale.iloc[-156:]
        if len(w):
            out += [f"\nSettimanale, ultime {len(w)} settimane (data = primo giorno della settimana; l'ultima può essere in corso):\n", csv(w, fdata)]
        else:
            out.append("\nSettimanale: " + nd(self.s.errori.get("settimanale", "serie vuota")))
        m = self.s.m30
        if len(m):
            giorni = sorted(set(m.index.date))[-5:]
            m5 = m[[d in giorni for d in m.index.date]]
            out.append(f"\n30 minuti, ultime {len(giorni)} sedute (un blocco per seduta; ora = inizio barra, Europe/Rome):\n")
            for g in giorni:
                out.append(f"{g:%Y-%m-%d}:\n" + csv(m5[m5.index.date == g], lambda t: t.strftime("%H:%M"), "ora"))
        else:
            out.append("\n30 minuti: " + nd(self.s.errori.get("30m", "serie vuota")))
        return "\n".join(out)


# ─── documento ───────────────────────────────────────────────────────────────

def intestazione_definizioni(cfg: dict) -> str:
    zz = float(cfg.get("zigzag_atr") or 1.5)
    kp = [tuple(k) for k in (cfg.get("kama") or KAMA_DEFAULT)]
    return "\n".join([
        "## Definizioni e parametri",
        "",
        "Formule identiche alle funzioni Pine di TradingView (ta.sma, ta.ema, ta.rma, ta.rsi, ta.atr, indicatori integrati DMI, MACD, Stochastic, Bollinger Bands).",
        "",
        "- **Dati**: Yahoo Finance via yfinance, `auto_adjust=False` (prezzi NON aggiustati per dividendi; gli split sono già applicati da Yahoo a tutta la serie). Orari Europe/Rome. Decimale = punto. n.d. = non disponibile (motivo tra parentesi). Distanze = (livello/prezzo − 1) in % e (livello − prezzo)/ATR14 in multipli di ATR.",
        "- **SMA n**: media aritmetica delle ultime n chiusure. **EMA n**: α = 2/(n+1), primo valore = SMA n.",
        "- **RMA n (Wilder)**: α = 1/n, primo valore = SMA n.",
        f"- **KAMA(n, veloce, lenta)**: ER = |C − C[n]| / Σn|C − C[1]|; SC = (ER·(2/(veloce+1) − 2/(lenta+1)) + 2/(lenta+1))²; KAMA = KAMA[1] + SC·(C − KAMA[1]); primo valore = C alla barra n. Usate: {', '.join(f'KAMA({a},{b},{c})' for a, b, c in kp)} su chiusura.",
        "- **RSI 14**: 100 − 100/(1 + RMA14(guadagni)/RMA14(perdite)).",
        "- **Stocastico 14-3-3**: %K = SMA3(100·(C − min14 L)/(max14 H − min14 L)); %D = SMA3(%K).",
        "- **MACD 12-26-9**: EMA12 − EMA26; segnale = EMA9 del MACD; istogramma = MACD − segnale.",
        "- **DMI/ADX 14-14**: +DM/−DM di Wilder; +DI = 100·RMA14(+DM)/RMA14(TR); ADX = 100·RMA14(|+DI − −DI|/(+DI + −DI)).",
        "- **ATR 14**: RMA14 del True Range = max(H − L, |H − C[1]|, |L − C[1]|). ATR% = ATR/C·100.",
        "- **Bollinger 20-2**: base SMA20 ± 2·deviazione standard di popolazione a 20; %B = (C − inf)/(sup − inf); larghezza % = (sup − inf)/base·100.",
        "- **Volume relativo**: volume della seduta / media dei volumi delle 20 sedute precedenti.",
        f"- **ZigZag**: un massimo (minimo) diventa swing quando il prezzo si allontana in senso opposto di almeno {zz} × ATR14 (ATR della barra dello swing). L'ultimo estremo non ancora confermato è \"provvisorio\". Swing maggiori (Fibonacci): soglia {max(3.0, 2 * zz)} × ATR14; Fibonacci sull'ultimo swing maggiore completato e su quello in corso.",
        "- **Livelli**: gruppi di swing confermati degli ultimi 3 anni entro ±0.5 ATR14; numeri tondi con passo = metà della potenza di 10 inferiore al prezzo.",
        "- **Gap**: minimo della seduta > massimo della precedente (o massimo < minimo); chiuso quando una seduta successiva tocca il bordo della seduta precedente il gap.",
        "- **Doppio massimo/minimo candidato**: tre swing consecutivi H-L-H (L-H-L) con i due estremi entro 1 ATR14. **Base/rettangolo**: ≥15 sedute con (max H − min L) ≤ 4 ATR14; tocco = seduta entro 0.25 ATR dal bordo, sedute consecutive contano una volta; obiettivo di misura = bordo rotto ± altezza.",
        "- **Statistiche**: al massimo 10 anni di sedute; percentili lineari; n = numero di osservazioni.",
    ])


def _testa(titolo: str, cfg: dict, avvisi: list[str], modo: str) -> str:
    adesso = D.ora_roma()
    righe = [f"# {titolo}", "",
             f"Generato il {adesso:%Y-%m-%d %H:%M} (Europe/Rome) · modalità {modo} · generatore v{VERSIONE}"]
    if cfg.get("dati_di_prova"):
        righe += ["", "> **FILE DI PROVA: posizioni e liquidità sono fittizie.**"]
    for a in avvisi:
        righe += ["", f"> {a}"]
    return "\n".join(righe)


def documento_titolo(st: Strumento, cfg: dict) -> str:
    arch = Archivio()
    a = Analisi(st, cfg, arch, intraday=True)
    if not a.ok:
        return (_testa(f"Analisi tecnica — {st.simbolo}", cfg, [], "Titolo") +
                f"\n\nDati non disponibili per {st.simbolo}: {a.s.errori}\n")
    avvisi = []
    if a.incompleta:
        avvisi.append("**ATTENZIONE: mercato aperto. L'ultima barra giornaliera (e settimanale) è incompleta; volume parziale.**")
    totali = None
    if st.posizione.get("quantita"):
        x = a.posizione_numeri()
        liq = cfg.get("liquidita")
        totali = {"investito": x["cv_eur"], "conto": (x["cv_eur"] + float(liq)) if liq not in (None, "") and x["cv_eur"] else None}
    sezioni = [
        (a.sez_anagrafica, "Anagrafica e qualità del dato"), (a.sez_prezzo, "Prezzo"), (a.sez_indicatori, "Indicatori"),
        (a.sez_struttura, "Struttura"), (a.sez_livelli, "Livelli"), (a.sez_gap, "Gap"), (a.sez_candele, "Ultime 10 candele"),
        (a.sez_figure, "Figure candidate"), (a.sez_statistiche, "Statistiche storiche"), (a.sez_forza_relativa, "Forza relativa"),
        (a.sez_collegati, "Strumenti collegati"), (a.sez_eventi, "Eventi"),
        (lambda n: a.sez_posizione(n, totali), "Posizione"), (a.sez_tv, "Controllo incrociato TradingView"), (a.sez_grezzi, "Dati grezzi"),
    ]
    sez = [_testa(f"Analisi tecnica — {st.simbolo} ({st.nome or a.s.meta.get('longName') or ''})", cfg, avvisi, "Titolo"),
           intestazione_definizioni(cfg)]
    sez += [_protetta(fn_, n, tit) for n, (fn_, tit) in enumerate(sezioni, start=1)]
    doc = "\n\n".join(sez) + "\n"
    if len(doc) > 42000:
        doc += f"\n> Nota: file di {len(doc)} caratteri, oltre il limite indicativo di 40000.\n"
    return doc


def _protetta(fn_, n: int, titolo: str) -> str:
    """Una sezione che fallisce diventa "n.d." con il motivo, senza bloccare il file."""
    try:
        return fn_(n)
    except Exception as e:                      # noqa: BLE001 - qualunque errore va riportato, non nascosto
        return f"## {n}. {titolo}\n\n{nd(f'errore di calcolo: {type(e).__name__}: {str(e)[:200]}')}"


def _blocco_sintesi_protetto(a: "Analisi", totali: dict, k: int) -> str:
    try:
        return _blocco_sintesi(a, totali, k)
    except Exception as e:                      # noqa: BLE001
        return f"## {k}. {a.st.simbolo}\n\n{nd(f'errore di calcolo: {type(e).__name__}: {str(e)[:200]}')}"


def _blocco_sintesi(a: Analisi, totali: dict, k: int) -> str:
    st = a.st
    r = [f"## {k}. {st.nome or a.s.meta.get('longName') or st.simbolo} — {st.simbolo}"
         + (" (in portafoglio)" if st.posizione.get("quantita") else " (watchlist)")]
    if not a.ok:
        r.append(nd(str(a.s.errori)))
        return "\n\n".join(r)
    prev = float(a.c.iloc[-2])
    tipo = st.tipo or nd("tipo non indicato")
    r.append(f"ISIN {st.isin or 'n.d.'} · {st.mercato or a.s.meta.get('fullExchangeName', '')} · {a.valuta} · {tipo} · zainetto: "
             f"{TIPI_ZAINETTO.get(st.tipo, 'n.d.')} · ultima seduta {fdata(a.oggi)}{' (INCOMPLETA, mercato aperto)' if a.incompleta else ''} · "
             f"fonte {a.s.fonte}, {D.fmt_ora(a.s.scaricato_alle)}"
             + (f" · errori fonte: {a.s.errori}" if a.s.errori else ""))
    ora = D.ultimo_orario(a.s)
    rr = a.df.iloc[-1]
    r.append(f"**Prezzo** {a.p(a.ultimo)} (orario {D.fmt_ora(ora) if ora is not None else 'n.d.'}); O/H/L {a.p(rr['Open'])}/{a.p(rr['High'])}/{a.p(rr['Low'])}; "
             f"prec. {a.p(prev)}; var {(a.ultimo / prev - 1) * 100:+.2f}%; volume {fvol(rr['Volume'])}, rel. {fn(a.vol_rel())}.")
    # indicatori compatti
    medie = ["SMA20", "SMA50", "SMA100", "SMA200", "EMA20", "EMA50"] + [f"KAMA({x},{y},{z})" for x, y, z in a.kama_p]
    righe = []
    for m in medie:
        v0, v5, v20 = a.v(m), a.v(m, 5), a.v(m, 20)
        pend = (v0 / v5 - 1) * 100 if v0 and v5 else None
        righe.append([m, a.p(v0), a.p(v5), a.p(v20), dist(v0, a.ultimo, a.atr_now) if v0 else "n.d.", fn(pend, 2, True)])
    r.append(tabella(["Media", "Att.", "−5s", "−20s", "Dist. prezzo dalla media", "Pend. 5s %"], righe))
    righe = []
    for col, nome, d in (("RSI14", "RSI14", 1), ("StochK", "Stoc %K", 1), ("StochD", "Stoc %D", 1), ("MACD", "MACD", 4),
                         ("MACDsig", "Segnale", 4), ("MACDhist", "Istogr.", 4), ("ADX", "ADX", 1), ("+DI", "+DI", 1), ("-DI", "-DI", 1),
                         ("ATR14", "ATR14", a.dp), ("ATR%", "ATR%", 2), ("BB%B", "BB %B", 2), ("BBlarg%", "BB larg.%", 2)):
        righe.append([nome, fn(a.v(col), d), fn(a.v(col, 5), d), fn(a.v(col, 20), d)])
    r.append(tabella(["Indicatore", "Att.", "−5s", "−20s"], righe))
    hs = [p for p in a.pivot if p.tipo == "H" and p.etichetta][-3:]
    ls = [p for p in a.pivot if p.tipo == "L" and p.etichetta][-3:]
    ult = a.pivot[-6:]
    r.append(f"**Struttura** (ZigZag {a.zz_mult}×ATR): ultimi swing "
             + "; ".join(f"{fdata(p.data)} {'H' if p.tipo == 'H' else 'L'} {a.p(p.prezzo)}{' ' + p.etichetta if p.etichetta else ''}{' (provv.)' if not p.confermato else ''}"
                         for p in ult)
             + f". Sequenza massimi {'→'.join(p.etichetta for p in hs) or 'n.d.'}, minimi {'→'.join(p.etichetta for p in ls) or 'n.d.'}.")
    est = T.estremi_periodo(a.df, a.oggi)
    r.append("**Estremi**: " + "; ".join(f"{k} {a.p(e['max'])} ({fdata(e['data_max'])}) / {a.p(e['min'])} ({fdata(e['data_min'])})"
                                       for k, e in est.items() if e))
    lv = a.livelli(4)
    r.append("**Livelli più vicini**: " + ("; ".join(f"{x['lato'][:3]}. {a.p(x['prezzo'])} [{x['tipo']}"
                                                     + (f", {x['descr'].split(':')[0]}" if x['tipo'] == 'swing' else '') + f"] {a.d(x['prezzo'])}"
                                                     for x in lv) or "nessuno"))
    aperti = [g for g in a.gap12 if g["chiuso_dopo"] is None]
    r.append("**Gap aperti 12 mesi** (>0.5 ATR): " + ("; ".join(f"{fdata(g['data'])} {g['direzione']} {a.p(g['da'])}–{a.p(g['a'])} ({fn(g['ampiezza_atr'])} ATR)"
                                                       for g in aperti) or "nessuno"))
    vol = S.volatilita(a.d10["Close"])
    esc = S.escursioni(a.d10, a.atr10).get(10)
    r.append(f"**Statistiche** (n={len(a.d10)} sedute): dev. std rendimenti 20/60/250s = {fn(vol[20][0])}/{fn(vol[60][0])}/{fn(vol[250][0])}%; "
             f"giorni oltre ±3% = {fn(vol['oltre3'][0])}%"
             + (f"; escursione a 10 sedute p10/p50/p90: rialzo {'/'.join(fn(esc['su_pct'][i]) for i in (1, 3, 5))}%, "
                f"ribasso {'/'.join(fn(esc['giu_pct'][i]) for i in (1, 3, 5))}% (n={esc['n']})" if esc else "") + ".")
    fr = a.sez_forza_relativa(0).split("\n\n")
    r.append("**Forza relativa**: " + fr[0].replace("## 0. ", "") + "\n\n" + fr[-1] if len(fr) > 1 else "")
    if st.collegati:
        r.append(a.sez_collegati(0, righe_max=2).replace("## 0. Strumenti collegati\n", "**Strumenti collegati**\n").strip())
    ev = a.sez_eventi(0).split("\n")[1:]
    r.append("**Eventi**:\n" + "\n".join(x for x in ev if x and "Split" not in x and "Nota" not in x and "Importo" not in x))
    if st.posizione.get("quantita"):
        r.append(a.sez_posizione(0, totali).replace("## 0. Posizione\n", "**Posizione**\n").strip())
    return "\n\n".join(x for x in r if x)


def documento_portafoglio(strumenti: list[Strumento], cfg: dict, limite: int = 60000) -> str:
    arch = Archivio()
    analisi = [Analisi(s, cfg, arch, intraday=False) for s in strumenti]
    liq = cfg.get("liquidita")
    investito, mancanti = 0.0, []
    for a in analisi:
        if a.ok and a.st.posizione.get("quantita"):
            x = a.posizione_numeri()
            if x["cv_eur"] is None:
                mancanti.append(a.st.simbolo)
            else:
                investito += x["cv_eur"]
    totali = {"investito": investito, "conto": investito + float(liq) if liq not in (None, "") else None}
    avvisi = []
    if any(a.ok and a.incompleta for a in analisi):
        avvisi.append("**ATTENZIONE: per gli strumenti segnati \"INCOMPLETA\" il mercato è aperto e l'ultima barra è incompleta.**")
    pos = [a for a in analisi if a.st.posizione.get("quantita")]
    righe = []
    for a in pos:
        if not a.ok:
            righe.append([a.st.simbolo, "n.d.", "", "", "", "", ""])
            continue
        x = a.posizione_numeri()
        p = a.st.posizione
        righe.append([a.st.simbolo, f"{x['q']:g}", a.p(p.get("carico")) if p.get("carico") else "n.d.", a.p(a.ultimo),
                      f"{x['cv_eur']:.2f}" if x["cv_eur"] else "n.d.",
                      f"{x['cv_eur'] / investito * 100:.1f}%" if x["cv_eur"] and investito else "n.d.",
                      f"{x['cv_eur'] / totali['conto'] * 100:.1f}%" if x["cv_eur"] and totali["conto"] else "n.d."])
    riep = ["## Riepilogo conto", "",
            f"Liquidità: {f'{float(liq):.2f} EUR' if liq not in (None, '') else nd('non indicata')}. "
            f"Totale investito (controvalori in EUR): {investito:.2f}. "
            f"Conto (investito + liquidità): {'n.d.' if not totali['conto'] else format(totali['conto'], '.2f')} EUR."
            + (f" Controvalore in EUR non calcolabile per: {', '.join(mancanti)}." if mancanti else ""), "",
            tabella(["Simbolo", "Quantità", "Carico", "Prezzo", "Controvalore EUR", "Peso investito", "Peso conto"], righe) if righe else "Nessuna posizione."]
    testa = [_testa("Analisi tecnica — PORTAFOGLIO", cfg, avvisi, "Portafoglio"), intestazione_definizioni(cfg), "\n".join(riep)]
    blocchi = [_blocco_sintesi_protetto(a, totali, k + 1) for k, a in enumerate(analisi)]
    doc = "\n\n".join(testa + blocchi) + "\n"
    if len(doc) > limite:
        doc += (f"\n> Nota: il file supera il limite indicativo di {limite} caratteri ({len(doc)}). "
                "Valuta di ridurre la watchlist.\n")
    return doc
