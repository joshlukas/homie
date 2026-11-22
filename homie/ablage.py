"""Verschlüsselte Ablage für Schlüssel und Zugänge, die später im Dashboard eingetragen werden.

Jeder Eintrag wird mit AES-256-GCM verschlüsselt in der Datenbank gespeichert. Der Hauptschlüssel
liegt entweder als Datei im Datenordner (Standard, keine Vorkonfiguration nötig) oder kommt über
HOMIE_MASTER_KEY von außen – dann schützt die Ablage auch eine kopierte Datensicherung.
Werte verlassen dieses Modul nur für den Aufruf beim jeweiligen Dienst, nie Richtung Browser.
"""
from __future__ import annotations

import base64
import hashlib
import os
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .db import Datenbank

SCHLUESSELDATEI = "hauptschluessel.key"


class AblageFehler(Exception):
    pass


def _hauptschluessel(daten: Path, von_aussen: str) -> bytes:
    if von_aussen:
        # Beliebig langer Text von außen → fester 32-Byte-Schlüssel.
        return hashlib.scrypt(von_aussen.encode(), salt=b"homie-ablage-v1", n=2**14, r=8, p=1, dklen=32)
    datei = daten / SCHLUESSELDATEI
    if not datei.exists():
        daten.mkdir(parents=True, exist_ok=True)
        fd = os.open(datei, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64encode(os.urandom(32)))
    roh = base64.b64decode(datei.read_bytes().strip())
    if len(roh) != 32:
        raise AblageFehler("Hauptschlüssel-Datei ist beschädigt.")
    return roh


class Ablage:
    def __init__(self, db: Datenbank, daten: Path, von_aussen: str = ""):
        self._db = db
        self._aes = AESGCM(_hauptschluessel(daten, von_aussen))

    def setzen(self, name: str, wert: str) -> None:
        nonce = os.urandom(12)
        geheim = self._aes.encrypt(nonce, wert.encode(), name.encode())
        self._db.ausfuehren(
            "INSERT INTO ablage (name, nonce, geheim, geaendert) VALUES (?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET nonce=excluded.nonce, geheim=excluded.geheim, geaendert=excluded.geaendert",
            (name, nonce, geheim, int(time.time())),
        )

    def lesen(self, name: str) -> str | None:
        z = self._db.eine("SELECT nonce, geheim FROM ablage WHERE name=?", (name,))
        if z is None:
            return None
        try:
            return self._aes.decrypt(z["nonce"], z["geheim"], name.encode()).decode()
        except InvalidTag as e:
            raise AblageFehler(f"Eintrag „{name}“ lässt sich mit diesem Hauptschlüssel nicht öffnen.") from e

    def hat(self, name: str) -> bool:
        return self._db.eine("SELECT 1 FROM ablage WHERE name=?", (name,)) is not None

    def loeschen(self, name: str) -> None:
        self._db.ausfuehren("DELETE FROM ablage WHERE name=?", (name,))

    def namen(self) -> list[str]:
        return [z["name"] for z in self._db.alle("SELECT name FROM ablage ORDER BY name")]
