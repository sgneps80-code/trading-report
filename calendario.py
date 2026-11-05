#!/usr/bin/env python3
"""
Calendario (Sezione 2) e colonna "Eventi (30gg)" delle posizioni: un'unica
lista di eventi, da tre fonti.

- Macro: riunioni BCE/Fed (data/eventi_macro.yaml).
- Inseriti a mano nella riga della posizione (regole, campo "eventi"): la
  fonte affidabile, perche' per i titoli italiani a bassa capitalizzazione
  quelle automatiche sono incomplete. Per gli stacchi si puo' indicare
  l'importo, da cui l'effetto atteso sul prezzo.
- Automatici: date di trimestrale e di stacco dividendo dal calendario
  Yahoo Finance (via yfinance, senza importo: Yahoo non lo da' per gli stacchi
  futuri) e scadenza dei certificati letta dal nome ("... 23/09/2026").
  Un evento inserito a mano dello stesso tipo entro pochi giorni prevale su
  quello automatico, che non viene ripetuto.

Uno stacco dividendo fa scendere meccanicamente il prezzo dell'importo
staccato: senza segnalarlo verrebbe letto come un segnale di mercato.
"""
import logging
import re
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)
# yfinance scrive nei suoi messaggi d'errore il simbolo richiesto (es. un 404
# "No fundamentals data found for symbol: ..."): nel log pubblico di GitHub
# Actions rivelerebbe le posizioni. I suoi errori qui sono gia' gestiti come
# "nessun evento", quindi il suo logger tace del tutto.
logging.getLogger("yfinance").setLevel(logging.CRITICAL + 1)
logging.getLogger("yfinance").propagate = False

TRIMESTRALE = "Trimestrale / CdA"
STACCO = "Stacco dividendo"
ULTIMO_GIORNO_DIRITTO = "Ultimo giorno con diritto al dividendo"
PAGAMENTO = "Pagamento dividendo"
SCADENZA_CERTIFICATO = "Scadenza certificato"
ASSEMBLEA_STRAORDINARIA = "Assemblea straordinaria"
ALTRO = "Altro"

# Ordine del menu nella pagina.
TIPI = [TRIMESTRALE, STACCO, ULTIMO_GIORNO_DIRITTO, PAGAMENTO, SCADENZA_CERTIFICATO,
        ASSEMBLEA_STRAORDINARIA, ALTRO]

_DATA_NEL_NOME = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")


def scadenza_da_nome(*testi):
    """Data di scadenza scritta nel nome di un certificato (es. 'FBK FIXLEV -4x
    SH OIL 23/09/2026'). None se nessun testo ne contiene una valida."""
    for t in testi:
        m = _DATA_NEL_NOME.search(t or "")
        if m:
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                continue
    return None


def _a_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if hasattr(v, "date"):                      # pandas.Timestamp
        try:
            return v.date()
        except Exception:
            return None
    return None


def eventi_yahoo(simbolo_yahoo):
    """(eventi, errore) dal calendario Yahoo Finance: date di trimestrale e di
    stacco dividendo. Mai un'eccezione: un errore torna come testo."""
    if not simbolo_yahoo:
        return [], "simbolo Yahoo non disponibile"
    try:
        import yfinance as yf
        cal = yf.Ticker(simbolo_yahoo).calendar or {}
    except Exception as e:
        return [], f"{type(e).__name__}"
    out = []
    for d in cal.get("Earnings Date") or []:
        d = _a_date(d)
        if d:
            out.append({"data": d, "tipo": TRIMESTRALE, "fonte": "Yahoo"})
    for chiave, tipo in (("Ex-Dividend Date", STACCO), ("Dividend Date", PAGAMENTO)):
        d = _a_date(cal.get(chiave))
        if d:
            out.append({"data": d, "tipo": tipo, "fonte": "Yahoo"})
    return out, None


def effetto_stacco(importo, prezzo):
    """Calo meccanico atteso allo stacco, in % del prezzo attuale (negativo)."""
    if not importo or not prezzo:
        return None
    return -importo / prezzo * 100


def _ha_manuale_vicino(manuali, ev, giorni=5):
    return any(m["tipo"] == ev["tipo"] and abs((m["data"] - ev["data"]).days) <= giorni for m in manuali)


def costruisci(portfolio, regole_map, eventi_macro, eventi_auto=None, oggi=None, giorni=60):
    """Lista ordinata degli eventi dei prossimi `giorni` giorni.
    eventi_auto: {isin: [eventi automatici]} gia' scaricati.
    Ogni voce: data, tipo, titolo, isin (None per macro), fonte, e per gli
    stacchi importo/valuta/effetto_pct quando l'importo e' noto."""
    oggi = oggi or date.today()
    limite = oggi + timedelta(days=giorni)
    eventi_auto = eventi_auto or {}
    voci = [dict(e, isin=None, fonte="Macro") for e in eventi_macro if oggi <= e["data"] <= limite]
    for p in portfolio:
        isin = p.get("isin")
        nome = p.get("name", isin)
        manuali = [dict(ev, fonte="inserito a mano") for ev in ((regole_map.get(isin) or {}).get("eventi") or [])]
        automatici = list(eventi_auto.get(isin) or [])
        scadenza = scadenza_da_nome(p.get("name"), p.get("titolo"))
        if scadenza:
            automatici.append({"data": scadenza, "tipo": SCADENZA_CERTIFICATO, "fonte": "dal nome"})
        automatici = [ev for ev in automatici if not _ha_manuale_vicino(manuali, ev)]
        for ev in manuali + automatici:
            if not (oggi <= ev["data"] <= limite):
                continue
            voce = {"data": ev["data"], "tipo": ev.get("tipo") or ALTRO, "titolo": nome, "isin": isin,
                    "fonte": ev.get("fonte"), "nota": ev.get("nota") or ""}
            if voce["tipo"] == STACCO:
                voce["importo"] = ev.get("importo")
                voce["valuta"] = p.get("valuta_prezzo") or p.get("divisa") or ""
                voce["effetto_pct"] = effetto_stacco(ev.get("importo"), p.get("price"))
            voci.append(voce)
    voci.sort(key=lambda v: (v["data"], v["titolo"] or ""))
    return voci


def scarica_automatici(portfolio, simbolo_yahoo):
    """{isin: eventi} dal calendario Yahoo per le posizioni; simbolo_yahoo e'
    una funzione posizione -> simbolo Yahoo. Nel log solo conteggi (repo pubblico)."""
    out = {}
    for p in portfolio:
        isin = p.get("isin")
        if not isin:
            continue
        out[isin], _ = eventi_yahoo(simbolo_yahoo(p))
    con_eventi = sum(1 for v in out.values() if v)
    logger.info(f"Calendario Yahoo: {sum(len(v) for v in out.values())} eventi; {con_eventi} posizioni su "
                f"{len(out)} con almeno un evento (le altre: nessun dato Yahoo, solo inserimento manuale)")
    return out
