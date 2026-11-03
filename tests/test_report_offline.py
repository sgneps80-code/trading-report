"""
Generazione completa dei due documenti su dati SINTETICI (nessuna rete):
controlla che tutte le sezioni ci siano, i limiti di lunghezza e la
cifratura andata e ritorno. I numeri non hanno significato di mercato.
"""
import zlib

import numpy as np
import pandas as pd
import pytest

from analisi import dati as D
from analisi import report as R


def _serie_finta(simbolo, intraday=True, eventi=True):
    rng = np.random.default_rng(zlib.crc32(simbolo.encode()))
    idx = pd.bdate_range("2014-01-02", "2026-10-30")
    c = 50 * np.exp(np.cumsum(rng.normal(0.0002, 0.015, len(idx))))
    o = c * np.exp(rng.normal(0, 0.006, len(idx)))
    h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.007, len(idx))))
    l = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.007, len(idx))))
    v = rng.integers(1e5, 1e6, len(idx)).astype(float)
    o, h, l, c = (np.round(x, 2) for x in (o, h, l, c))     # prezzi reali: 2 decimali
    v = v * 10                                                 # volumi a 7 cifre
    df = pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v,
                       "Dividends": 0.0, "Stock Splits": 0.0}, index=idx)
    df.loc[idx[-100], "Dividends"] = 1.2
    s = D.Serie(simbolo=simbolo, giornaliero=df, scaricato_alle=D.ora_roma(), fonte="SINTETICO")
    s.settimanale = df.resample("W-MON", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    if intraday:
        t = pd.date_range("2026-10-26 09:00", "2026-10-30 17:00", freq="30min", tz=D.ROMA)
        t = t[(t.hour >= 9) & (t.hour < 18)]
        s.m30 = pd.DataFrame({"Open": 50.0, "High": 51.0, "Low": 49.0, "Close": 50.5, "Volume": 1000.0}, index=t)
    s.meta = {"currency": "EUR", "longName": f"Finta {simbolo}", "regularMarketTime": 1761840000}
    s.calendario = {"Earnings Date": [pd.Timestamp("2027-01-30").date()]}
    s.date_conti = [idx[-60].date()]
    return s


@pytest.fixture(autouse=True)
def niente_rete(monkeypatch):
    monkeypatch.setattr(D, "scarica", _serie_finta)
    monkeypatch.setattr(D, "screener_tv", lambda c: (None, {}, "test offline"))


CFG = {
    "dati_di_prova": True, "liquidita": 5000, "zigzag_atr": 1.5,
    "strumenti": [
        {"simbolo": "SAN.PA", "nome": "Sanofi", "tipo": "azione", "valuta": "EUR", "benchmark": "^FCHI",
         "collegati": [{"simbolo": "SNY", "tipo": "adr", "rapporto": 0.5, "cambio": "EURUSD=X"}],
         "posizione": {"quantita": 50, "carico": 45, "stop": 40, "target": 70, "uscita": "2027-03-31"}},
        {"simbolo": "SGLD.MI", "nome": "ETC oro", "tipo": "etc", "valuta": "EUR",
         "collegati": [{"simbolo": "GC=F", "tipo": "sottostante", "cambio": "EURUSD=X"}]},
    ] + [{"simbolo": f"T{k}.MI", "tipo": "azione"} for k in range(10)],
}


def test_titolo():
    st = R.Strumento.da_dict(CFG["strumenti"][0])
    md = R.documento_titolo(st, CFG)
    for k in range(1, 16):
        assert f"\n## {k}. " in md, f"manca la sezione {k}"
    assert "```csv" in md and "FILE DI PROVA" in md
    assert len(md) < 43000, len(md)      # limite indicativo ~40000 (dati sintetici con molti gap)


def test_portafoglio():
    sts = [R.Strumento.da_dict(x) for x in CFG["strumenti"]]
    md = R.documento_portafoglio(sts, CFG)
    assert "Riepilogo conto" in md and "```csv" not in md
    assert len(md) < 60000, len(md)


def test_cifratura():
    import base64
    import os
    from analisi.cifra import chiave_da_b64, cifra, decifra
    k = chiave_da_b64(base64.b64encode(os.urandom(32)).decode())
    blob = cifra("testo è", "a.md", k)
    assert decifra(blob, k) == {"nome": "a.md", "md": "testo è"}
    with pytest.raises(ValueError):
        chiave_da_b64(base64.b64encode(b"corta").decode())
