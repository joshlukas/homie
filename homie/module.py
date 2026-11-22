"""Modul-Register.

Jedes Modul erklärt hier, welchen Dienst und welche Schlüssel es braucht. Es erscheint erst im Menü,
wenn das erfüllt ist: ein passender Dienst ist verbunden und seine Schlüssel liegen in der Ablage.
Ein neues Modul = ein Eintrag in MODULE (und später seine eigene Seite).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .ablage import Ablage
from .db import Datenbank


@dataclass(frozen=True)
class Bedarf:
    art: str                       # Art des Dienstes, "*" = irgendein Dienst
    bezeichnung: str               # für Menschen: was ist das, mit Beispiel
    schluessel: tuple[str, ...] = ()   # Namen der nötigen Schlüssel, z. B. ("token",)
    zustand: str = "verbunden"     # "verbunden" (Standard) oder "gefunden"


@dataclass(frozen=True)
class Modul:
    id: str
    titel: str
    beschreibung: str
    braucht: tuple[Bedarf, ...] = ()
    kern: bool = False             # Kern-Module sind immer da (Onboarding)
    farbe: str = "#8b7cff"


@dataclass
class ModulStand:
    modul: Modul
    aktiv: bool
    fehlt: list[str] = field(default_factory=list)   # verständliche Sätze, was noch fehlt

    def als_dict(self) -> dict:
        m = self.modul
        return {
            "id": m.id, "titel": m.titel, "beschreibung": m.beschreibung, "kern": m.kern, "aktiv": self.aktiv,
            "braucht": [{"art": b.art, "bezeichnung": b.bezeichnung, "schluessel": list(b.schluessel)} for b in m.braucht],
            "fehlt": self.fehlt,
        }


MODULE: tuple[Modul, ...] = (
    Modul("onboarding", "Onboarding", "Dienste finden, verbinden und Module freischalten.", kern=True),
    Modul(
        "tag", "Mein Tag", "Termine, Aufgaben und das Wichtigste für heute.",
        (Bedarf("homeassistant", "Home Assistant (kennt Kalender, Aufgaben und Wetter)", ("token",)),), farbe="#ff5fa2",
    ),
    Modul(
        "aufnahme", "Aufnahme", "Sprachnotizen aufnehmen; eine lokale KI schreibt mit und ordnet ein.",
        (Bedarf("assistent", "ein Notiz-Assistent (eigener Dienst, der Sprachnotizen verschriftlicht)", ("token",)),), farbe="#2fd4c4",
    ),
    Modul(
        "gesundheit", "Gesundheit", "Schlaf, Bewegung und Messwerte im Verlauf.",
        (Bedarf("homeassistant", "Home Assistant (mit der Handy-App, die Gesundheitswerte meldet)", ("token",)),), farbe="#3ddc97",
    ),
    Modul(
        "finanzen", "Finanzen", "Kontostand, Ausgaben und Ausblick auf den Monat.",
        (Bedarf("assistent", "ein Notiz-Assistent (eigener Dienst, der Kontoumsätze auswertet)", ("token",)),), farbe="#ffc46b",
    ),
    Modul(
        "dokumente", "Dokumente", "Post und Unterlagen durchsuchen, Fristen im Blick.",
        (Bedarf("dokumente", "ein Dokumentenarchiv (z. B. Paperless-ngx)", ("token",)),), farbe="#5b9dff",
    ),
    Modul(
        "netzplan", "Netzplan", "Alle Geräte und Dienste im Heimnetz als Plan.",
        (Bedarf("*", "mindestens ein gefundenes Gerät (nach der ersten Erkundung)", zustand="gefunden"),), farbe="#c77dff",
    ),
)


def schluesselname(dienst_id: int, schluessel: str) -> str:
    return f"dienst:{dienst_id}:{schluessel}"


def stand(db: Datenbank, ablage: Ablage) -> list[ModulStand]:
    dienste = db.alle("SELECT id, art, zustand FROM dienst WHERE zustand != 'ignoriert'")
    geraete = db.eine("SELECT COUNT(*) AS n FROM geraet")["n"]
    ergebnis = []
    for m in MODULE:
        fehlt: list[str] = []
        for b in m.braucht:
            passend = [d for d in dienste if b.art in ("*", d["art"])]
            if b.zustand == "verbunden":
                verbunden = [d for d in passend if d["zustand"] == "verbunden"]
                if not passend:
                    fehlt.append(f"Noch nicht gefunden: {b.bezeichnung}.")
                elif not verbunden:
                    fehlt.append(f"Gefunden, aber noch nicht verbunden: {b.bezeichnung}.")
                elif not any(all(ablage.hat(schluesselname(d["id"], s)) for s in b.schluessel) for d in verbunden):
                    fehlt.append(f"Schlüssel fehlt für: {b.bezeichnung}.")
            elif not passend and not (b.art == "*" and geraete):
                fehlt.append(f"Noch nicht vorhanden: {b.bezeichnung}.")
        ergebnis.append(ModulStand(m, aktiv=m.kern or not fehlt, fehlt=fehlt))
    return ergebnis
