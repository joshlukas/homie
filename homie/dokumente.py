"""Modul „Dokumente“: liest ein Paperless-ngx-Archiv – Suche, neueste Dokumente, Vorschaubilder.

Es wird ausschließlich gelesen. Inhalte der Dokumente werden nicht gespeichert; jede Ansicht fragt
Paperless neu. Nur die Namen von Korrespondenten, Arten und Schlagwörtern bleiben ein paar Minuten
im Arbeitsspeicher, damit nicht jede Seite sie neu laden muss.
"""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urlencode

import aiohttp

JE_SEITE = 24
_FELDER = "id,title,correspondent,document_type,tags,created,page_count"
_namen: dict[str, tuple[float, dict]] = {}


class DokumenteFehler(Exception):
    """Meldung, die dem Nutzer gezeigt werden kann."""


def _sitzung(token: str) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=12),
        headers={"Authorization": f"Token {token}", "Accept": "application/json"},
    )


async def _json(s: aiohttp.ClientSession, url: str) -> dict:
    try:
        async with s.get(url, allow_redirects=False) as r:
            if r.status in (401, 403):
                raise DokumenteFehler("Das Archiv lehnt den Schlüssel ab. Bitte im Onboarding trennen und neu verbinden.")
            if r.status != 200:
                raise DokumenteFehler(f"Das Archiv antwortet mit Fehler {r.status}.")
            return await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as e:
        raise DokumenteFehler("Das Archiv ist gerade nicht erreichbar.") from e


async def _alle_namen(s: aiohttp.ClientSession, basis: str) -> dict:
    alt = _namen.get(basis)
    if alt and time.time() - alt[0] < 300:
        return alt[1]
    teile = await asyncio.gather(*(_json(s, f"{basis}/api/{was}/?page_size=1000&fields=id,name,color,text_color")
                                   for was in ("correspondents", "document_types", "tags")))
    namen = {
        "korrespondent": {x["id"]: x["name"] for x in teile[0].get("results", [])},
        "art": {x["id"]: x["name"] for x in teile[1].get("results", [])},
        "schlagwort": {x["id"]: x["name"] for x in teile[2].get("results", [])},
    }
    _namen[basis] = (time.time(), namen)
    return namen


def _datum(wert: str | None) -> str:
    try:
        j, m, t = (wert or "")[:10].split("-")
        return f"{t}.{m}.{j}"
    except ValueError:
        return ""


async def uebersicht(basis: str, token: str, suche: str = "", seite: int = 1) -> dict:
    basis = basis.rstrip("/")
    werte = {"page": max(1, seite), "page_size": JE_SEITE, "fields": _FELDER}
    if suche:
        werte["query"] = suche          # Volltextsuche von Paperless, beste Treffer zuerst
    else:
        werte["ordering"] = "-created"
    async with _sitzung(token) as s:
        liste, zahlen, namen = await asyncio.gather(
            _json(s, f"{basis}/api/documents/?{urlencode(werte)}"),
            _json(s, f"{basis}/api/statistics/"),
            _alle_namen(s, basis),
        )
    dokumente = [{
        "id": d["id"], "titel": d.get("title") or "Ohne Titel", "datum": _datum(d.get("created")),
        "korrespondent": namen["korrespondent"].get(d.get("correspondent"), ""),
        "art": namen["art"].get(d.get("document_type"), ""),
        "schlagwoerter": [namen["schlagwort"][t] for t in d.get("tags", []) if t in namen["schlagwort"]],
        "seiten": d.get("page_count") or 0,
        "link": f"{basis}/documents/{d['id']}/details",
    } for d in liste.get("results", [])]
    treffer = liste.get("count", len(dokumente))
    return {
        "dokumente": dokumente, "treffer": treffer, "seite": max(1, seite),
        "seiten": max(1, -(-treffer // JE_SEITE)),
        "gesamt": zahlen.get("documents_total", 0), "posteingang": zahlen.get("documents_inbox") or 0,
    }


async def vorschau(basis: str, token: str, nummer: int) -> tuple[bytes, str]:
    try:
        async with _sitzung(token) as s:
            async with s.get(f"{basis.rstrip('/')}/api/documents/{nummer}/thumb/", allow_redirects=False) as r:
                art = r.headers.get("Content-Type", "")
                if r.status != 200 or not art.startswith("image/"):
                    raise DokumenteFehler("Keine Vorschau.")
                return await r.content.read(3_000_000), art.split(";")[0]
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        raise DokumenteFehler("Keine Vorschau.") from e
