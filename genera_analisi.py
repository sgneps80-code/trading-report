#!/usr/bin/env python3
"""
Genera il file .md di analisi tecnica (modalita' Titolo o Portafoglio).

Uso dal workflow "Analisi tecnica" (avviato dal pulsante sulla pagina):
    python genera_analisi.py --da-evento      # legge gli input dal payload di GitHub

Uso locale (PC con Python):
    python genera_analisi.py --modo titolo --simbolo SAN.PA [--config watchlist.json] [--out cartella]
    python genera_analisi.py --modo portafoglio --config watchlist.json [--out cartella]

La configurazione (watchlist, posizioni, liquidita') e' il JSON esportato
dalla pagina (pulsante "Esporta"). Non stampa mai i dati personali nei log.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

from analisi import dati as D
from analisi import report as R

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("genera_analisi")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

SIMBOLO_RE = re.compile(r"^[A-Za-z0-9.\-\^=]{1,24}$")
RICHIESTA_RE = re.compile(r"^[a-z0-9]{8,40}$")


def nome_file(modo: str, simbolo: str | None) -> str:
    t = D.ora_roma().strftime("%Y-%m-%d_%H%M")
    tag = "PORTAFOGLIO" if modo == "portafoglio" else re.sub(r"[^A-Za-z0-9.\-]", "_", simbolo or "X").upper()
    return f"analisi_{tag}_{t}.md"


def genera(modo: str, simbolo: str | None, cfg: dict) -> tuple[str, str]:
    strumenti = [R.Strumento.da_dict(x) for x in cfg.get("strumenti", []) if x.get("simbolo")]
    if modo == "titolo":
        if not simbolo or not SIMBOLO_RE.match(simbolo):
            raise SystemExit("Simbolo mancante o non valido")
        st = next((s for s in strumenti if s.simbolo == simbolo.upper()), None) or R.Strumento(simbolo=simbolo.upper())
        testo = R.documento_titolo(st, cfg)
    elif modo == "portafoglio":
        if not strumenti:
            raise SystemExit("Watchlist vuota: niente da analizzare")
        testo = R.documento_portafoglio(strumenti, cfg)
    else:
        raise SystemExit(f"Modo non valido: {modo}")
    return nome_file(modo, simbolo), testo


def da_evento() -> None:
    """Modalita' workflow: input dal payload dell'evento (mai interpolati nei comandi)."""
    ev = json.load(open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8"))
    inp = ev.get("inputs") or {}
    rid = (inp.get("request_id") or "").strip()
    if not RICHIESTA_RE.match(rid):
        raise SystemExit("request_id non valido")
    modo = (inp.get("modo") or "titolo").strip()
    simbolo = (inp.get("simbolo") or "").strip() or None
    cfg = json.loads(inp.get("config_json") or "{}")
    prova = str(inp.get("prova") or "").lower() == "true"
    if not prova and not (inp.get("chiave") or "").strip():
        raise SystemExit("Chiave di cifratura assente: la pagina va aggiornata (Ctrl+F5)")
    log.info(f"Richiesta {rid}: modo={modo}, strumenti in watchlist={len(cfg.get('strumenti', []))}")
    nome, testo = genera(modo, simbolo, cfg)
    out_dir = Path(os.environ.get("ANALISI_OUT", "out_analisi"))
    out_dir.mkdir(parents=True, exist_ok=True)
    if prova:
        # solo per i file di prova con dati fittizi: niente cifratura
        if not cfg.get("dati_di_prova"):
            raise SystemExit("prova=true ammesso solo con configurazione marcata dati_di_prova")
        (out_dir / f"{rid}.md").write_text(testo, encoding="utf-8")
        (out_dir / f"{rid}.nome").write_text(nome, encoding="utf-8")
    else:
        from analisi.cifra import chiave_da_b64, cifra
        try:
            chiave = chiave_da_b64((inp.get("chiave") or "").strip())
        except ValueError as e:
            raise SystemExit(f"Chiave di cifratura non valida ({e}): nessun output")
        (out_dir / f"{rid}.json").write_text(cifra(testo, nome, chiave), encoding="utf-8")
    log.info(f"Creato {nome}: {len(testo)} caratteri")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--da-evento", action="store_true")
    ap.add_argument("--modo", choices=["titolo", "portafoglio"])
    ap.add_argument("--simbolo")
    ap.add_argument("--config")
    ap.add_argument("--out", default=str(Path.home() / "Downloads"))
    a = ap.parse_args()
    if a.da_evento:
        da_evento()
        return
    if not a.modo:
        ap.error("--modo obbligatorio")
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8")) if a.config else {}
    nome, testo = genera(a.modo, a.simbolo, cfg)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / nome).write_text(testo, encoding="utf-8")
    print(f"Salvato: {out / nome} ({len(testo)} caratteri)")


if __name__ == "__main__":
    sys.exit(main())
