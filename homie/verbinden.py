"""Verbinden eines gefundenen Dienstes: Schlüssel prüfen (ein lesender Aufruf beim Dienst), dann verschlüsselt ablegen.

Der Schlüssel geht ausschließlich an die Adresse, unter der der Dienst im Heimnetz gefunden wurde –
Weiterleitungen werden nicht verfolgt.
"""
from __future__ import annotations

import asyncio

import aiohttp

from .katalog import Eintrag


def _anfrage(kennung: str, w: dict[str, str]) -> tuple[str, dict[str, str], aiohttp.BasicAuth | None] | None:
    """Pfad, Kopfzeilen und Anmeldung für die Prüfung – je Dienst ein harmloser, lesender Aufruf."""
    if kennung == "homeassistant":
        return "/api/", {"Authorization": f"Bearer {w['token']}"}, None
    if kennung == "paperless":
        return "/api/documents/?page_size=1", {"Authorization": f"Token {w['token']}"}, None
    if kennung == "proxmox":
        return "/api2/json/version", {"Authorization": f"PVEAPIToken={w['token-id']}={w['token']}"}, None
    if kennung == "portainer":
        return "/api/endpoints", {"X-API-Key": w["token"]}, None
    if kennung == "immich":
        return "/api/users/me", {"x-api-key": w["token"]}, None
    if kennung == "firefly":
        return "/api/v1/about", {"Authorization": f"Bearer {w['token']}", "Accept": "application/json"}, None
    if kennung == "notizdienst":
        return "/api/eintraege?tage=1", {"Authorization": f"Bearer {w['token']}"}, None
    if kennung == "nextcloud":
        return "/ocs/v2.php/cloud/user?format=json", {"OCS-APIRequest": "true"}, aiohttp.BasicAuth(w["benutzer"], w["app-passwort"])
    return None


async def pruefen(e: Eintrag, adresse: str, werte: dict[str, str]) -> tuple[bool, str]:
    """(in Ordnung?, Meldung für den Menschen)."""
    if not e.felder:
        return True, "Verbunden."
    anfrage = _anfrage(e.id, werte)
    if anfrage is None:
        return True, "Gespeichert (für diesen Dienst gibt es noch keine automatische Prüfung)."
    pfad, kopf, anmeldung = anfrage
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=8)) as s:
            async with s.get(adresse.rstrip("/") + pfad, headers=kopf, auth=anmeldung, allow_redirects=False) as r:
                status = r.status
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
        return False, f"{e.name} ist gerade nicht erreichbar. Nichts gespeichert."
    if status == 200:
        return True, "Schlüssel geprüft und verschlüsselt abgelegt."
    if status in (401, 403):
        return False, f"{e.name} lehnt den Schlüssel ab. Nichts gespeichert."
    return False, f"{e.name} antwortet unerwartet (Fehler {status}). Nichts gespeichert."
