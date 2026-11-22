"""Proxmox lesen: Rechner, virtuelle Maschinen, Container, Speicher. Hier wird ausschließlich gelesen.

Für alles in dieser Datei genügt in Proxmox ein API-Token mit der Rolle „PVEAuditor“.
"""
from __future__ import annotations

import asyncio

import aiohttp

GIB = 1024 ** 3


class ProxmoxFehler(Exception):
    """Meldung, die dem Nutzer gezeigt werden kann."""


def sitzung(token_id: str, token: str) -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=15),
        headers={"Authorization": f"PVEAPIToken={token_id}={token}"},
    )


async def holen(s: aiohttp.ClientSession, basis: str, pfad: str, pflicht: bool = True):
    try:
        async with s.get(basis.rstrip("/") + "/api2/json" + pfad, allow_redirects=False) as r:
            if r.status == 401:
                raise ProxmoxFehler("Proxmox lehnt den Schlüssel ab. Bitte im Onboarding trennen und neu verbinden.")
            if r.status != 200:
                if pflicht:
                    raise ProxmoxFehler(f"Proxmox antwortet mit Fehler {r.status}." + (" Dem Token fehlt dafür das Leserecht." if r.status == 403 else ""))
                return None
            return (await r.json()).get("data")
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as e:
        if pflicht:
            raise ProxmoxFehler("Proxmox ist gerade nicht erreichbar.") from e
        return None


def _gb(wert) -> float:
    return round((wert or 0) / GIB, 1)


def aufbereiten(roh: list[dict]) -> dict:
    knoten = [{
        "name": x.get("node", ""), "an": x.get("status") == "online", "kerne": x.get("maxcpu") or 0,
        "ram_gesamt": _gb(x.get("maxmem")), "ram_frei": _gb((x.get("maxmem") or 0) - (x.get("mem") or 0)),
        "ram_anteil": int(100 * (x.get("mem") or 0) / x["maxmem"]) if x.get("maxmem") else 0,
    } for x in roh if x.get("type") == "node"]
    gaeste = [{
        "vmid": x.get("vmid"), "name": x.get("name") or f"Nr. {x.get('vmid')}", "art": "VM" if x.get("type") == "qemu" else "Container",
        "an": x.get("status") == "running", "kerne": x.get("maxcpu") or 0, "ram": _gb(x.get("maxmem")), "platte": _gb(x.get("maxdisk")),
        "knoten": x.get("node", ""),
    } for x in roh if x.get("type") in ("qemu", "lxc") and not x.get("template")]
    return {"knoten": sorted(knoten, key=lambda k: k["name"]), "gaeste": sorted(gaeste, key=lambda g: g["vmid"] or 0)}


async def lesen(basis: str, token_id: str, token: str) -> dict:
    async with sitzung(token_id, token) as s:
        return aufbereiten(await holen(s, basis, "/cluster/resources") or [])
