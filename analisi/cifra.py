"""
Cifratura del file prodotto dal workflow: il repo e' pubblico, quindi il
file (che contiene posizioni e liquidita') viaggia solo cifrato.

AES-256-GCM con una chiave CASUALE generata dalla pagina a ogni richiesta
(32 byte, base64), passata al workflow come input mascherato insieme alla
watchlist e tenuta dalla pagina solo in memoria per decifrare il file.
Nessuna password da ricordare o inserire.
"""
from __future__ import annotations

import base64
import binascii
import json
import os


def chiave_da_b64(b64: str) -> bytes:
    try:
        k = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("chiave non in base64") from None
    if len(k) != 32:
        raise ValueError("la chiave deve essere di 32 byte")
    return k


def cifra(testo: str, nome_file: str, chiave: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = os.urandom(12)
    payload = json.dumps({"nome": nome_file, "md": testo}, ensure_ascii=False).encode("utf-8")
    ct = AESGCM(chiave).encrypt(iv, payload, None)
    return json.dumps({"v": 2, "alg": "AES-256-GCM", "iv": base64.b64encode(iv).decode(),
                       "ct": base64.b64encode(ct).decode()})


def decifra(blob: str, chiave: bytes) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    d = json.loads(blob)
    pt = AESGCM(chiave).decrypt(base64.b64decode(d["iv"]), base64.b64decode(d["ct"]), None)
    return json.loads(pt)
