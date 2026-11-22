"""Schlüssel für helfende Agenten (Claude Code, Codex o. Ä.).

Ein Agent darf über /agent/… den Stand lesen und Pläne vorschlagen. Bestätigen, verbinden, erkunden
oder Schlüssel sehen kann er nicht – das bleibt dem angemeldeten Menschen im Dashboard vorbehalten.
Gespeichert wird nur der SHA-256 des Schlüssels; der Schlüssel selbst wird genau einmal angezeigt.
"""
from __future__ import annotations

import hashlib
import secrets
import time

from .db import Datenbank

VORSATZ = "hm_"


def _kennung(schluessel: str) -> str:
    return hashlib.sha256(schluessel.encode()).hexdigest()


def anlegen(db: Datenbank, name: str) -> str:
    schluessel = VORSATZ + secrets.token_urlsafe(32)
    db.ausfuehren("INSERT INTO agent (name, kennung, angelegt, zuletzt) VALUES (?,?,?,0)",
                  ((name.strip() or "Agent")[:40], _kennung(schluessel), int(time.time())))
    return schluessel


def finden(db: Datenbank, kopfzeile: str | None) -> str | None:
    """Name des Agenten zu „Authorization: Bearer hm_…“ – oder None."""
    if not kopfzeile or not kopfzeile.startswith("Bearer " + VORSATZ) or len(kopfzeile) > 200:
        return None
    z = db.eine("SELECT id, name, zuletzt FROM agent WHERE kennung=?", (_kennung(kopfzeile[7:]),))
    if z is None:
        return None
    if time.time() - z["zuletzt"] > 60:
        db.ausfuehren("UPDATE agent SET zuletzt=? WHERE id=?", (int(time.time()), z["id"]))
    return z["name"]


def alle(db: Datenbank) -> list[dict]:
    return [dict(z) for z in db.alle("SELECT id, name, angelegt, zuletzt FROM agent ORDER BY id")]


def entziehen(db: Datenbank, nummer: int) -> None:
    db.ausfuehren("DELETE FROM agent WHERE id=?", (nummer,))
