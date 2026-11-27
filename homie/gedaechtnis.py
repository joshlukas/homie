"""Modul „Gedächtnis“: Fragen an das eigene Gedächtnis stellen und Notizen tippen.

Das Gedächtnis ist ein zweiter kleiner Dienst des Notiz-Assistenten: Er durchsucht Notizen, Profil und
Dokumente und antwortet mit lokaler KI; nur wenn der Nutzer es zulässt, fragt er eine KI außerhalb.
Homie reicht die Frage weiter und zeigt die Antwort mit ihren Fundstellen. Homie speichert nichts davon.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from urllib.parse import urlsplit

import aiohttp

from .assistent import AssistentFehler
from .tag import zone

PORT = 8097
MAX_FRAGE = 2000          # Zeichen
MAX_NOTIZ = 20_000        # Bytes, so viel nimmt der Assistent als getippte Notiz an
QUELLEN = {"notiz": ("Notiz", "Notizen"), "profil": ("Profil", "Profil"), "paperless": ("Dokument", "Dokumente")}


def adresse(assistent: str, eigene: str = "") -> str:
    """Adresse des Gedächtnisses: ausdrücklich eingestellt oder derselbe Rechner wie der Notiz-Assistent."""
    if eigene:
        return eigene.rstrip("/")
    teile = urlsplit(assistent if "://" in assistent else "http://" + assistent)
    return f"{teile.scheme}://{teile.hostname}:{PORT}"


def _datum(wert) -> str:
    try:
        t = dt.date.fromisoformat(str(wert or "")[:10])
        return f"{t.day}.{t.month}.{t.year}"
    except ValueError:
        return ""


def _fundstelle(q: dict) -> dict:
    link = str(q.get("link") or "")
    return {"nr": q.get("nr"), "art": QUELLEN.get(q.get("quelle"), ("Fundstelle",))[0], "titel": str(q.get("titel") or "")[:200],
            "datum": _datum(q.get("datum")), "ausschnitt": str(q.get("ausschnitt") or "")[:1500],
            "link": link if link.startswith(("http://", "https://")) else ""}


async def fragen(basis: str, token: str, frage: str, claude: bool) -> dict:
    """Stellt die Frage. claude=True heißt: ausdrücklich auch außerhalb fragen (Frage und Fundstellen verlassen das Heimnetz)."""
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=150),
                                         headers={"Authorization": f"Bearer {token}"}) as s:
            async with s.post(basis + "/api/frage", json={"frage": frage, "claude": "immer" if claude else "auto"}, allow_redirects=False) as r:
                if r.status in (401, 403):
                    raise AssistentFehler("Das Gedächtnis lehnt den Schlüssel ab. Bitte den Notiz-Assistenten im Onboarding trennen und neu verbinden.")
                antwort = await r.json(content_type=None)
                if r.status != 200 or not isinstance(antwort, dict) or "antwort" not in antwort:
                    raise AssistentFehler(str((antwort or {}).get("fehler") or f"Das Gedächtnis antwortet mit Fehler {r.status}.")[:200])
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, AttributeError) as e:
        raise AssistentFehler("Das Gedächtnis ist gerade nicht erreichbar.") from e
    sekunden = antwort.get("sekunden")
    return {"antwort": str(antwort.get("antwort") or "")[:20000], "gefunden": bool(antwort.get("gefunden")), "sicher": bool(antwort.get("sicher")),
            "weg": "claude" if antwort.get("weg") == "claude" else "lokal", "hinweis": str(antwort.get("hinweis") or "")[:300],
            "sekunden": round(sekunden) if isinstance(sekunden, (int, float)) else None,
            "quellen": [_fundstelle(q) for q in antwort.get("quellen") or [] if isinstance(q, dict)][:30]}


async def stand(basis: str, token: str) -> dict | None:
    """Wie viel das Gedächtnis kennt und wann es zuletzt eingelesen hat. None, wenn es gerade nicht antwortet."""
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=5),
                                         headers={"Authorization": f"Bearer {token}"}) as s:
            async with s.get(basis + "/api/stand", allow_redirects=False) as r:
                if r.status != 200:
                    return None
                roh = await r.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
        return None
    if not isinstance(roh, dict):
        return None
    teile = []
    for kennung, (_, mehrzahl) in QUELLEN.items():
        n = ((roh.get("quellen") or {}).get(kennung) or {}).get("eintraege")
        if n:
            teile.append("Profil" if kennung == "profil" else f"{n} {mehrzahl}")
    zuletzt = ""
    try:
        t = dt.datetime.fromisoformat(str(roh.get("zuletzt_eingelesen"))).astimezone(zone())
        heute = dt.datetime.now(zone()).date()
        zuletzt = ("heute" if t.date() == heute else "gestern" if t.date() == heute - dt.timedelta(days=1) else f"am {t.day}.{t.month}.") + f" um {t:%H:%M} Uhr"
    except (ValueError, TypeError):
        pass
    return {"kennt": teile, "zuletzt": zuletzt, "claude": bool((roh.get("claude") or {}).get("frei"))}
