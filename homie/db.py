"""SQLite-Datenbank im Datenordner. Enthält Konto, Sitzungen, gefundene Dienste und die verschlüsselte Ablage."""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS konto (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    passwort TEXT NOT NULL,
    angelegt INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sitzung (
    kennung TEXT PRIMARY KEY,          -- SHA-256 des Cookie-Werts, nie der Wert selbst
    csrf TEXT NOT NULL,
    angelegt INTEGER NOT NULL,
    zuletzt INTEGER NOT NULL,
    ablauf INTEGER NOT NULL,
    geraet TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS dienst (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    art TEXT NOT NULL,                 -- z. B. homeassistant, dokumente, ki-lokal
    name TEXT NOT NULL,
    adresse TEXT NOT NULL DEFAULT '',
    zustand TEXT NOT NULL DEFAULT 'gefunden',  -- gefunden | verbunden | ignoriert
    gefunden INTEGER NOT NULL,
    details TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS geraet (             -- Ergebnis der letzten Erkundung: Geräte im Heimnetz
    ip TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    mac TEXT NOT NULL DEFAULT '',
    ports TEXT NOT NULL DEFAULT '[]',
    sonstiges TEXT NOT NULL DEFAULT '[]',       -- unbekannte Webseiten und einfache Dienste auf dem Gerät
    gesehen INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS container (          -- Docker-Container auf diesem Rechner (nur gelesen)
    name TEXT PRIMARY KEY,
    image TEXT NOT NULL DEFAULT '',
    zustand TEXT NOT NULL DEFAULT '',
    ports TEXT NOT NULL DEFAULT '[]',
    stack TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS merk (
    name TEXT PRIMARY KEY,
    wert TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ablage (
    name TEXT PRIMARY KEY,             -- z. B. dienst:3:token
    nonce BLOB NOT NULL,
    geheim BLOB NOT NULL,              -- AES-256-GCM, nie Klartext
    geaendert INTEGER NOT NULL
);
"""


class Datenbank:
    """Eine Verbindung, durch eine Sperre geschützt. Für ein Dashboard im Heimnetz reicht das."""

    def __init__(self, pfad: Path):
        pfad.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(pfad.parent, 0o700)
        except OSError:
            pass
        self._sperre = threading.RLock()
        self._c = sqlite3.connect(pfad, check_same_thread=False, isolation_level=None)
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.execute("PRAGMA foreign_keys=ON")
        self._c.executescript(SCHEMA)
        try:
            os.chmod(pfad, 0o600)
        except OSError:
            pass

    def ausfuehren(self, sql: str, werte: tuple = ()) -> sqlite3.Cursor:
        with self._sperre:
            return self._c.execute(sql, werte)

    def eine(self, sql: str, werte: tuple = ()) -> sqlite3.Row | None:
        with self._sperre:
            return self._c.execute(sql, werte).fetchone()

    def alle(self, sql: str, werte: tuple = ()) -> list[sqlite3.Row]:
        with self._sperre:
            return self._c.execute(sql, werte).fetchall()

    def schliessen(self) -> None:
        with self._sperre:
            self._c.close()
