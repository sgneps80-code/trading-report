#!/usr/bin/env python3
"""
Cifratura di docs/index.html: il repo e' pubblico e la pagina contiene le
posizioni (ISIN, prezzi, stop/target, tesi). Prima una password confrontata
con il suo hash nascondeva solo la VISUALIZZAZIONE: i dati restavano in
chiaro nel file, leggibili da chiunque aprisse il sorgente o il repo.

Ora il contenuto viaggia solo cifrato: AES-256-GCM con chiave derivata dalla
password del sito (secret SITE_PASSWORD) con PBKDF2-HMAC-SHA256. La pagina
contiene solo il blob cifrato e il codice che lo decifra nel browser
(WebCrypto) quando si inserisce la password: senza password non c'e' nulla
da leggere, e non c'e' piu' nemmeno l'hash della password da attaccare.

Sale fisso (pubblico, come sempre per un sale): la chiave resta la stessa da
un giorno all'altro, cosi' il browser puo' ricordarla per 7 giorni come
faceva prima con l'accesso. La robustezza dipende dalla password: con
PBKDF2 a 600.000 iterazioni una passphrase lunga regge, una password corta no.
"""
import base64
import hashlib
import json
import os

ITERAZIONI = 600_000
SALE = b"trading-report|docs/index.html|v1"


def deriva_chiave(password, iterazioni=ITERAZIONI, sale=SALE):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sale, iterazioni, 32)


def cifra(dati, password, iterazioni=ITERAZIONI):
    """dati: oggetto serializzabile in JSON. Restituisce il blob da inserire
    nella pagina (solo base64 e numeri: nessun testo in chiaro)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = os.urandom(12)
    testo = json.dumps(dati, ensure_ascii=False).encode("utf-8")
    ct = AESGCM(deriva_chiave(password, iterazioni)).encrypt(iv, testo, None)
    return {"v": 1, "alg": "AES-256-GCM", "kdf": "PBKDF2-SHA256", "iter": iterazioni,
            "salt": base64.b64encode(SALE).decode(), "iv": base64.b64encode(iv).decode(),
            "ct": base64.b64encode(ct).decode()}


def decifra(blob, password):
    """Inverso di cifra (usato dai test; nel sito decifra il browser)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    chiave = deriva_chiave(password, blob["iter"], base64.b64decode(blob["salt"]))
    pt = AESGCM(chiave).decrypt(base64.b64decode(blob["iv"]), base64.b64decode(blob["ct"]), None)
    return json.loads(pt)
