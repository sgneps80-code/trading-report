"""
Cifratura del file prodotto dal workflow: il repo e' pubblico, quindi il
file (che contiene posizioni e liquidita') viaggia solo cifrato.

AES-256-GCM con chiave = PBKDF2-HMAC-SHA256(password del sito, SALE, ITER).
La pagina deriva la stessa chiave con WebCrypto quando inserisci la
password e decifra nel browser. Il sale e' fisso e pubblico (serve solo
a separare questa chiave da altri usi della stessa password).
"""
from __future__ import annotations

import base64
import json
import os

SALE = b"trading-report/analisi-tecnica/v1"
ITER = 310_000


def deriva_chiave(password: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALE, iterations=ITER).derive(password.encode("utf-8"))


def cifra(testo: str, nome_file: str, password: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = os.urandom(12)
    payload = json.dumps({"nome": nome_file, "md": testo}, ensure_ascii=False).encode("utf-8")
    ct = AESGCM(deriva_chiave(password)).encrypt(iv, payload, None)
    return json.dumps({"v": 1, "alg": "AES-256-GCM", "kdf": "PBKDF2-SHA256", "iter": ITER,
                       "sale": SALE.decode(), "iv": base64.b64encode(iv).decode(),
                       "ct": base64.b64encode(ct).decode()})


def decifra(blob: str, password: str) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    d = json.loads(blob)
    pt = AESGCM(deriva_chiave(password)).decrypt(base64.b64decode(d["iv"]), base64.b64decode(d["ct"]), None)
    return json.loads(pt)
