"""Modul „Dokumente“: liest ein Paperless-ngx-Archiv – alle Dokumente als Liste, Volltextsuche, Vorschaubilder, PDF.

Es wird ausschließlich gelesen. Inhalte der Dokumente werden nicht gespeichert. Nur die Liste (Titel, Datum,
Absender, Art, Schlagwörter) bleibt fünf Minuten im Arbeitsspeicher, damit nicht jede Ansicht sie neu laden muss.
"""
from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import urlencode

import aiohttp


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


async def _ganz(r: aiohttp.ClientResponse, grenze: int) -> bytes:
    """Liest eine Antwort vollständig, bricht aber ab, wenn sie größer als erlaubt ist."""
    teile, laenge = [], 0
    async for stueck in r.content.iter_chunked(65536):
        laenge += len(stueck)
        if laenge > grenze:
            raise DokumenteFehler("Die Datei ist zu groß.")
        teile.append(stueck)
    return b"".join(teile)


async def vorschau(basis: str, token: str, nummer: int) -> tuple[bytes, str]:
    try:
        async with _sitzung(token) as s:
            async with s.get(f"{basis.rstrip('/')}/api/documents/{nummer}/thumb/", allow_redirects=False) as r:
                art = r.headers.get("Content-Type", "")
                if r.status != 200 or not art.startswith("image/"):
                    raise DokumenteFehler("Keine Vorschau.")
                return await _ganz(r, 5_000_000), art.split(";")[0]
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        raise DokumenteFehler("Keine Vorschau.") from e


# ---------- Dokumentstream: alle Dokumente auf einmal (für Lineal, Filter und Raster), Volltextsuche, PDF ----------

_listen: dict[str, tuple[float, dict]] = {}
_HILFSMARKEN = {"ai-processed"}      # Arbeitsmarken von Zusatzprogrammen, für Menschen ohne Aussage
MAX_DATEI = 80_000_000


async def _seiten(s: aiohttp.ClientSession, url: str) -> list[dict]:
    """Holt eine Liste vollständig, Seite für Seite (höchstens 10.000 Einträge)."""
    aus, seite = [], 1
    while seite <= 40:
        d = await _json(s, f"{url}{'&' if '?' in url else '?'}page_size=250&page={seite}")
        aus += d.get("results", [])
        if not d.get("next"):
            break
        seite += 1
    return aus


async def alle(basis: str, token: str, frisch: bool = False) -> dict:
    """Alle Dokumente, neueste zuerst – nur die Angaben, die die Seite zum Zeichnen braucht. Fünf Minuten gemerkt."""
    basis = basis.rstrip("/")
    alt = _listen.get(basis)
    if alt and not frisch and time.time() - alt[0] < 300:
        return alt[1]
    async with _sitzung(token) as s:
        von, arten, marken, dokumente = await asyncio.gather(
            _seiten(s, f"{basis}/api/correspondents/?fields=id,name"), _seiten(s, f"{basis}/api/document_types/?fields=id,name"),
            _seiten(s, f"{basis}/api/tags/?fields=id,name,is_inbox_tag"),
            _seiten(s, f"{basis}/api/documents/?ordering=-created&fields=id,title,created,added,correspondent,document_type,tags,page_count"))
    n_von, n_art = {x["id"]: x["name"] for x in von}, {x["id"]: x["name"] for x in arten}
    n_marke = {x["id"]: x["name"] for x in marken if x["name"] not in _HILFSMARKEN}
    eingang = {x["id"] for x in marken if x.get("is_inbox_tag")}
    aus = {"anzahl": len(dokumente), "archiv": basis, "stand": int(time.time()), "dokumente": [{
        "id": d["id"], "titel": d.get("title") or "Ohne Titel", "datum": (d.get("created") or "")[:10], "neu": (d.get("added") or "")[:10],
        "von": n_von.get(d.get("correspondent"), ""), "art": n_art.get(d.get("document_type"), ""),
        "tags": [n_marke[t] for t in d.get("tags") or [] if t in n_marke], "seiten": d.get("page_count") or 0,
        "eingang": any(t in eingang for t in d.get("tags") or []),
    } for d in dokumente]}
    _listen[basis] = (time.time(), aus)
    return aus


async def volltext(basis: str, token: str, frage: str) -> dict:
    """Volltextsuche des Archivs: Nummern der Treffer (beste zuerst) und je ein kurzer Auszug aus dem Text."""
    async with _sitzung(token) as s:
        d = await _json(s, f"{basis.rstrip('/')}/api/documents/?{urlencode({'query': frage, 'page_size': 100, 'fields': 'id,__search_hit__'})}")
    treffer = []
    for x in d.get("results", []):
        roh = ((x.get("__search_hit__") or {}).get("highlights") or "")
        auszug = " ".join(re.sub(r"<[^>]+>", "", roh).split())[:220]
        treffer.append({"id": x["id"], "auszug": auszug})
    return {"anzahl": d.get("count", len(treffer)), "treffer": treffer}


async def datei(basis: str, token: str, nummer: int, laden: bool = False) -> tuple[bytes, str, str]:
    """Das PDF eines Dokuments (zum Lesen) oder die Originaldatei (zum Herunterladen): Inhalt, Typ, Dateiname."""
    weg = "download" if laden else "preview"
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=90),
                                         headers={"Authorization": f"Token {token}"}) as s:
            async with s.get(f"{basis.rstrip('/')}/api/documents/{nummer}/{weg}/", allow_redirects=False) as r:
                if r.status != 200:
                    raise DokumenteFehler("Das Dokument lässt sich nicht laden.")
                inhalt = await _ganz(r, MAX_DATEI)
                name = (r.content_disposition.filename if r.content_disposition else None) or f"dokument-{nummer}.pdf"
                return inhalt, r.headers.get("Content-Type", "application/pdf").split(";")[0], name
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        raise DokumenteFehler("Das Archiv ist gerade nicht erreichbar.") from e
