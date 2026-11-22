"""Konto, Passwort und Sitzungen.

Es gibt genau ein Konto. Das Passwort legt der Nutzer beim ersten Aufruf selbst an; gespeichert wird
nur ein scrypt-Hash im Datenordner. Die Sitzung ist ein zufälliger Cookie-Wert, von dem die Datenbank
nur den SHA-256 kennt.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass

from .db import Datenbank

COOKIE = "homie_sitzung"
MIN_LAENGE = 10
MAX_LAENGE = 256
_N, _R, _P = 2**15, 8, 1


def _scrypt(passwort: str, salz: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(passwort.encode(), salt=salz, n=n, r=r, p=p, dklen=32, maxmem=128 * 1024 * 1024)


def passwort_hashen(passwort: str) -> str:
    salz = os.urandom(16)
    h = _scrypt(passwort, salz, _N, _R, _P)
    return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(salz).decode(), base64.b64encode(h).decode())


def passwort_pruefen(passwort: str, gespeichert: str) -> bool:
    try:
        art, n, r, p, salz, h = gespeichert.split("$")
        if art != "scrypt":
            return False
        neu = _scrypt(passwort, base64.b64decode(salz), int(n), int(r), int(p))
        return hmac.compare_digest(neu, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def passwort_maengel(passwort: str, wiederholung: str) -> str | None:
    if passwort != wiederholung:
        return "Die beiden Eingaben stimmen nicht überein."
    if len(passwort) < MIN_LAENGE:
        return f"Das Passwort braucht mindestens {MIN_LAENGE} Zeichen."
    if len(passwort) > MAX_LAENGE:
        return f"Das Passwort darf höchstens {MAX_LAENGE} Zeichen haben."
    return None


@dataclass(frozen=True)
class Sitzung:
    kennung: str
    csrf: str


class Anmeldung:
    def __init__(self, db: Datenbank, sitzung_tage: int = 30):
        self._db = db
        self._dauer = sitzung_tage * 86400
        self._fehl: dict[str, tuple[int, float]] = {}  # Adresse → (Fehlversuche, gesperrt bis)

    # --- Konto ---
    def eingerichtet(self) -> bool:
        return self._db.eine("SELECT 1 FROM konto WHERE id=1") is not None

    def konto_anlegen(self, passwort: str) -> bool:
        """Legt das eine Konto an. False, wenn es schon eines gibt (auch bei zwei gleichzeitigen Versuchen)."""
        try:
            self._db.ausfuehren(
                "INSERT INTO konto (id, passwort, angelegt) VALUES (1, ?, ?)", (passwort_hashen(passwort), int(time.time()))
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def passwort_stimmt(self, passwort: str) -> bool:
        z = self._db.eine("SELECT passwort FROM konto WHERE id=1")
        if z is None:
            passwort_hashen(passwort)  # gleiche Rechenzeit, damit nichts verraten wird
            return False
        return passwort_pruefen(passwort, z["passwort"])

    def konto_loeschen(self) -> None:
        """Für „Passwort vergessen“: Konto und alle Sitzungen weg, Daten und Ablage bleiben."""
        self._db.ausfuehren("DELETE FROM sitzung")
        self._db.ausfuehren("DELETE FROM konto")

    # --- Bremse gegen Durchprobieren ---
    def gesperrt_sekunden(self, adresse: str) -> int:
        n, bis = self._fehl.get(adresse, (0, 0.0))
        return max(0, int(bis - time.time()) + 1) if bis > time.time() else 0

    def fehlversuch(self, adresse: str) -> None:
        n, _ = self._fehl.get(adresse, (0, 0.0))
        n += 1
        warten = 0 if n < 5 else min(900, 30 * 2 ** (n - 5))
        self._fehl[adresse] = (n, time.time() + warten)
        if len(self._fehl) > 2000:
            self._fehl.clear()

    def erfolg(self, adresse: str) -> None:
        self._fehl.pop(adresse, None)

    # --- Sitzungen ---
    @staticmethod
    def _kennung(cookie_wert: str) -> str:
        return hashlib.sha256(cookie_wert.encode()).hexdigest()

    def sitzung_anlegen(self, geraet: str = "") -> str:
        wert = secrets.token_urlsafe(32)
        jetzt = int(time.time())
        self._db.ausfuehren("DELETE FROM sitzung WHERE ablauf < ?", (jetzt,))
        self._db.ausfuehren(
            "INSERT INTO sitzung (kennung, csrf, angelegt, zuletzt, ablauf, geraet) VALUES (?,?,?,?,?,?)",
            (self._kennung(wert), secrets.token_urlsafe(24), jetzt, jetzt, jetzt + self._dauer, geraet[:200]),
        )
        return wert

    def sitzung_finden(self, cookie_wert: str | None) -> Sitzung | None:
        if not cookie_wert or len(cookie_wert) > 200:
            return None
        k = self._kennung(cookie_wert)
        jetzt = int(time.time())
        z = self._db.eine("SELECT csrf, zuletzt FROM sitzung WHERE kennung=? AND ablauf>=?", (k, jetzt))
        if z is None:
            return None
        if jetzt - z["zuletzt"] > 3600:  # gleitende Verlängerung, höchstens einmal je Stunde schreiben
            self._db.ausfuehren("UPDATE sitzung SET zuletzt=?, ablauf=? WHERE kennung=?", (jetzt, jetzt + self._dauer, k))
        return Sitzung(kennung=k, csrf=z["csrf"])

    def sitzung_beenden(self, kennung: str) -> None:
        self._db.ausfuehren("DELETE FROM sitzung WHERE kennung=?", (kennung,))

    @property
    def dauer(self) -> int:
        return self._dauer
