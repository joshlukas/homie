"""Erkundung des Heimnetzes – ausschließlich lesend.

Was Homie tut, wenn der Nutzer auf „Heimnetz erkunden“ klickt:
1. Eigenes Heimnetz bestimmen (nur private Adressbereiche, höchstens 254 Adressen).
2. Bei jeder Adresse prüfen, ob bekannte Ports offen sind (reiner Verbindungsaufbau).
3. Offene Web-Ports einmal abrufen und im Katalog nachsehen, welcher Dienst das ist.
4. Docker über den nur lesenden Zwischendienst nach laufenden Containern fragen.
Es wird nirgends angemeldet, nichts geschrieben und keine Adresse außerhalb des Heimnetzes abgerufen.
"""
from __future__ import annotations

import asyncio
import fcntl
import ipaddress
import json
import re
import socket
import struct
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import aiohttp
from yarl import URL

from .db import Datenbank
from .katalog import KATALOG, NUR_PORT, TLS_ZUERST, WEB_PORTS, Eintrag, alle_ports, eintrag

_TITEL = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_KEIN_HEIMNETZ = ("lo", "docker", "br-", "veth", "virbr", "tailscale", "wg", "tun", "zt")


# ---------- Eigenes Netz ----------

def _ioctl_adresse(sock: socket.socket, name: str, befehl: int) -> str | None:
    try:
        roh = fcntl.ioctl(sock.fileno(), befehl, struct.pack("256s", name.encode()[:15]))
        return socket.inet_ntoa(roh[20:24])
    except OSError:
        return None


def eigene_netze() -> list[ipaddress.IPv4Interface]:
    """Private IPv4-Netze der eigenen Netzwerkkarten (ohne Docker-, VPN- und Schleifen-Schnittstellen)."""
    netze = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for _, name in socket.if_nameindex():
            if name.startswith(_KEIN_HEIMNETZ):
                continue
            ip, maske = _ioctl_adresse(s, name, 0x8915), _ioctl_adresse(s, name, 0x891B)
            if ip and maske:
                netz = ipaddress.IPv4Interface(f"{ip}/{maske}")
                if netz.ip.is_private and not netz.ip.is_loopback and not netz.ip.is_link_local:
                    netze.append(netz)
    return netze


def ziele(netze: list[ipaddress.IPv4Interface]) -> list[str]:
    """Adressen, die erkundet werden: je Netz höchstens der /24-Bereich um die eigene Adresse."""
    adressen: dict[str, None] = {}
    for n in netze:
        bereich = n.network if n.network.prefixlen >= 24 else ipaddress.IPv4Network(f"{n.ip}/24", strict=False)
        for a in bereich.hosts():
            adressen[str(a)] = None
    return list(adressen)


def standard_router() -> str | None:
    try:
        with open("/proc/net/route") as f:
            for zeile in f.readlines()[1:]:
                t = zeile.split()
                if t[1] == "00000000" and int(t[3], 16) & 2:
                    return socket.inet_ntoa(struct.pack("<L", int(t[2], 16)))
    except (OSError, ValueError, IndexError):
        pass
    return None


def _mac_tabelle() -> dict[str, str]:
    macs = {}
    try:
        with open("/proc/net/arp") as f:
            for zeile in f.readlines()[1:]:
                t = zeile.split()
                if len(t) >= 4 and t[3] != "00:00:00:00:00:00":
                    macs[t[0]] = t[3]
    except OSError:
        pass
    return macs


# ---------- Ergebnis ----------

@dataclass
class Fund:
    ip: str
    port: int
    art: str
    name: str
    adresse: str = ""           # Web-Adresse, falls vorhanden
    kennung: str = ""           # Katalog-ID, leer bei unbekannten Seiten
    titel: str = ""


@dataclass
class Ergebnis:
    geraete: dict[str, dict] = field(default_factory=dict)     # ip → {name, mac, ports}
    funde: list[Fund] = field(default_factory=list)
    container: list[dict] = field(default_factory=list)
    router: str | None = None
    eigene: list[str] = field(default_factory=list)
    docker: str = "aus"


# ---------- Netz abfragen ----------

async def _offen(ip: str, port: int, grenze: asyncio.Semaphore, warten: float) -> bool:
    async with grenze:
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(ip, port), warten)
        except (OSError, asyncio.TimeoutError):
            return False
        w.close()
        try:
            await w.wait_closed()
        except OSError:
            pass
        return True


async def _lesen(sitzung: aiohttp.ClientSession, url: str) -> tuple[int, str] | None:
    """Eine Seite abrufen. Weiterleitungen nur innerhalb desselben Rechners – nie hinaus ins Internet."""
    start = urlsplit(url)
    for _ in range(4):
        try:
            async with sitzung.get(url, allow_redirects=False) as r:
                if r.status in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                    ziel = urlsplit(str(r.url.join(URL(r.headers["Location"]))))
                    if ziel.hostname != start.hostname:
                        return r.status, ""
                    url = ziel.geturl()
                    continue
                return r.status, (await r.content.read(80_000)).decode("utf-8", "replace")
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
            return None
    return None


async def _erkennen(sitzung: aiohttp.ClientSession, ip: str, port: int, frei: bool = False) -> Fund | None:
    """frei=True: Port stammt aus Docker oder von Hand – dann zählt auch eine unbekannte Seite mit Titel."""
    if port in NUR_PORT and not frei:
        art, name = NUR_PORT[port]
        return Fund(ip, port, art, name)
    schemata = ("https", "http") if port in TLS_ZUERST else ("http", "https")
    basis, start = "", None
    for schema in schemata:
        antwort = await _lesen(sitzung, f"{schema}://{ip}:{port}/")
        if antwort and not (antwort[0] == 400 and "https" in antwort[1].lower() and schema == "http"):
            basis, start = f"{schema}://{ip}:{port}", antwort
            break
    if start is None:
        return None
    text = start[1].lower()
    treffer: Eintrag | None = next((e for e in KATALOG if e.pfad == "/" and any(m in text for m in e.muster)), None)
    if treffer is None:
        for e in KATALOG:
            if e.pfad != "/" and (frei or port in e.ports):
                antwort = await _lesen(sitzung, basis + e.pfad)
                if antwort and any(m in antwort[1].lower() for m in e.muster):
                    treffer = e
                    break
    m = _TITEL.search(start[1])
    titel = re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else ""
    if treffer:
        return Fund(ip, port, treffer.art, treffer.name, basis, treffer.id, titel)
    if (frei or port in WEB_PORTS) and titel:
        return Fund(ip, port, "web", titel, basis, "", titel)
    return None


async def _name(ip: str) -> str:
    try:
        name = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, socket.gethostbyaddr, ip), 2)
        return name[0].split(".")[0]
    except (OSError, asyncio.TimeoutError):
        return ""


async def docker_lesen(docker_url: str) -> tuple[str, list[dict]]:
    if not docker_url:
        return "aus", []
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s:
            async with s.get(docker_url + "/containers/json?all=1") as r:
                if r.status != 200:
                    return "fehler", []
                liste = await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
        return "fehler", []
    container = []
    for c in liste:
        ports = sorted({p["PublicPort"] for p in c.get("Ports", []) if p.get("PublicPort")})
        container.append({
            "name": (c.get("Names") or ["?"])[0].lstrip("/"), "image": c.get("Image", ""),
            "zustand": c.get("State", ""), "ports": ports,
            "stack": (c.get("Labels") or {}).get("com.docker.compose.project", ""),
        })
    return "bereit", sorted(container, key=lambda c: c["name"])


async def erkunden(adressen: list[str], ports: tuple[int, ...], docker_url: str, melden=lambda text, anteil: None,
                   warten: float = 0.7, eigene: tuple[str, ...] = ()) -> Ergebnis:
    erg = Ergebnis()
    melden("Docker wird gelesen …", 0.02)
    erg.docker, erg.container = await docker_lesen(docker_url)
    # Ports, die Docker auf diesem Rechner veröffentlicht, werden hier zusätzlich angesehen –
    # so tauchen auch Dienste auf ungewöhnlichen Ports auf.
    docker_ports = {p for c in erg.container if c["zustand"] == "running" for p in c["ports"]} - set(ports)

    grenze = asyncio.Semaphore(200)
    fertig = 0

    async def pruefen(ip: str) -> tuple[str, list[int]]:
        nonlocal fertig
        hier = ports + tuple(sorted(docker_ports)) if ip in eigene else ports
        offen = await asyncio.gather(*(_offen(ip, p, grenze, warten) for p in hier))
        fertig += 1
        if fertig % 8 == 0 or fertig == len(adressen):
            melden(f"Adressen werden geprüft … {fertig} von {len(adressen)}", 0.05 + 0.6 * fertig / max(1, len(adressen)))
        return ip, [p for p, o in zip(hier, offen) if o]

    offene = [(ip, ps) for ip, ps in await asyncio.gather(*(pruefen(ip) for ip in adressen)) if ps]

    melden(f"{len(offene)} Geräte gefunden – Dienste werden erkannt …", 0.7)
    verbinder = aiohttp.TCPConnector(ssl=False, limit=40)
    async with aiohttp.ClientSession(connector=verbinder, timeout=aiohttp.ClientTimeout(total=4),
                                     headers={"User-Agent": "Homie-Erkundung"}) as sitzung:
        funde = await asyncio.gather(*(_erkennen(sitzung, ip, p, frei=p in docker_ports) for ip, ps in offene for p in ps))
    melden("Namen werden nachgeschlagen …", 0.92)
    namen = await asyncio.gather(*(_name(ip) for ip, _ in offene))
    macs = _mac_tabelle()
    for (ip, ps), name in zip(offene, namen):
        erg.geraete[ip] = {"name": name, "mac": macs.get(ip, ""), "ports": ps}

    # Derselbe Dienst auf mehreren Ports eines Geräts (z. B. 80 und 443) zählt einmal.
    gesehen: set[tuple[str, str]] = set()
    def rang(f: Fund) -> tuple:
        e = eintrag(f.kennung)   # der im Katalog zuerst genannte Port ist die eigentliche Adresse des Dienstes
        return (f.ip, f.kennung == "", e.ports.index(f.port) if e and f.port in e.ports else 99, f.port)

    for f in sorted((f for f in funde if f), key=rang):
        schluessel = (f.ip, f.kennung or f"{f.art}:{f.name}")
        if schluessel not in gesehen:
            gesehen.add(schluessel)
            erg.funde.append(f)
    return erg


# ---------- Ablegen im Datenordner ----------

def _als_karte(f: Fund) -> bool:
    e = eintrag(f.kennung)
    return e is not None and e.karte


def speichern(db: Datenbank, erg: Ergebnis) -> dict:
    jetzt = int(time.time())
    for ip in erg.eigene:   # der eigene Rechner gehört immer in den Plan, auch ohne offene Ports
        erg.geraete.setdefault(ip, {"name": socket.gethostname(), "mac": "", "ports": []})
    db.ausfuehren("DELETE FROM geraet")
    for ip, g in erg.geraete.items():
        sonst = [{"port": f.port, "art": f.art, "name": f.name, "adresse": f.adresse}
                 for f in erg.funde if f.ip == ip and not _als_karte(f)]
        db.ausfuehren("INSERT INTO geraet (ip, name, mac, ports, sonstiges, gesehen) VALUES (?,?,?,?,?,?)",
                      (ip, g["name"], g["mac"], json.dumps(g["ports"]), json.dumps(sonst), jetzt))
    db.ausfuehren("DELETE FROM container")
    for c in erg.container:
        db.ausfuehren("INSERT OR REPLACE INTO container (name, image, zustand, ports, stack) VALUES (?,?,?,?,?)",
                      (c["name"], c["image"], c["zustand"], json.dumps(c["ports"]), c["stack"]))

    vorhanden = {(z["art"], json.loads(z["details"]).get("ip", "")): z for z in db.alle("SELECT id, art, details FROM dienst")}
    neu = 0
    for f in erg.funde:
        if not _als_karte(f):
            continue
        geraet = erg.geraete.get(f.ip, {}).get("name", "")
        details = json.dumps({"ip": f.ip, "port": f.port, "kennung": f.kennung, "geraet": geraet, "gesehen": jetzt})
        alt = vorhanden.get((f.art, f.ip))
        if alt:
            db.ausfuehren("UPDATE dienst SET name=?, adresse=?, details=? WHERE id=?", (f.name, f.adresse, details, alt["id"]))
        else:
            neu += 1
            db.ausfuehren("INSERT INTO dienst (art, name, adresse, zustand, gefunden, details) VALUES (?,?,?,'gefunden',?,?)",
                          (f.art, f.name, f.adresse, jetzt, details))
    # Was nie verbunden wurde und jetzt nicht mehr antwortet, verschwindet wieder.
    # Verbundene und ausgeblendete Dienste bleiben und werden als „nicht mehr erreichbar“ markiert.
    for z in db.alle("SELECT id, details FROM dienst WHERE zustand='gefunden'"):
        d = json.loads(z["details"])
        if d.get("gesehen", 0) < jetzt and d.get("quelle") != "hand":
            db.ausfuehren("DELETE FROM dienst WHERE id=?", (z["id"],))
    bilanz = {"zeit": jetzt, "geraete": len(erg.geraete), "dienste": sum(1 for f in erg.funde if _als_karte(f)), "neu": neu,
              "container": len(erg.container), "docker": erg.docker, "router": erg.router, "eigene": erg.eigene}
    db.ausfuehren("INSERT INTO merk (name, wert) VALUES ('erkundung', ?) ON CONFLICT(name) DO UPDATE SET wert=excluded.wert",
                  (json.dumps(bilanz),))
    return bilanz


async def von_hand(db: Datenbank, eingabe: str) -> tuple[bool, str]:
    """Einen Dienst über seine Adresse hinzufügen – für alles, was die Erkundung nicht findet,
    etwa Dienste, die nur über einen Namen hinter einem Proxy erreichbar sind."""
    eingabe = eingabe.strip().rstrip("/")
    if "://" not in eingabe:
        eingabe = "http://" + eingabe
    teile = urlsplit(eingabe)
    if teile.scheme not in ("http", "https") or not teile.hostname:
        return False, "Das ist keine gültige Adresse. Beispiel: https://cloud.beispiel.de"
    try:
        port = teile.port or (443 if teile.scheme == "https" else 80)
    except ValueError:
        return False, "Der Port in der Adresse ist ungültig."
    basis = f"{teile.scheme}://{teile.hostname}" + (f":{teile.port}" if teile.port else "")
    verbinder = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=verbinder, timeout=aiohttp.ClientTimeout(total=6),
                                     headers={"User-Agent": "Homie-Erkundung"}) as sitzung:
        start = await _lesen(sitzung, basis + "/")
        if start is None:
            return False, "Unter dieser Adresse antwortet nichts."
        text, treffer = start[1].lower(), None
        treffer = next((e for e in KATALOG if e.karte and e.pfad == "/" and any(m in text for m in e.muster)), None)
        if treffer is None:
            for e in KATALOG:
                if e.karte and e.pfad != "/":
                    antwort = await _lesen(sitzung, basis + e.pfad)
                    if antwort and any(m in antwort[1].lower() for m in e.muster):
                        treffer = e
                        break
    if treffer is None:
        return False, "Dort läuft kein Dienst, den Homie kennt."
    for z in db.alle("SELECT adresse FROM dienst WHERE art=?", (treffer.art,)):
        if z["adresse"] == basis:
            return False, f"{treffer.name} unter dieser Adresse ist schon eingetragen."
    details = json.dumps({"ip": teile.hostname, "port": port, "kennung": treffer.id, "geraet": teile.hostname,
                          "gesehen": int(time.time()), "quelle": "hand"})
    db.ausfuehren("INSERT INTO dienst (art, name, adresse, zustand, gefunden, details) VALUES (?,?,?,'gefunden',?,?)",
                  (treffer.art, treffer.name, basis, int(time.time()), details))
    return True, f"{treffer.name} hinzugefügt."


def letzte(db: Datenbank) -> dict | None:
    z = db.eine("SELECT wert FROM merk WHERE name='erkundung'")
    return json.loads(z["wert"]) if z else None


class Erkundung:
    """Hält fest, ob gerade erkundet wird, und startet einen Lauf im Hintergrund."""

    def __init__(self, db: Datenbank, docker_url: str, adressen: list[str] | None = None, ports: tuple[int, ...] | None = None):
        self._db, self._docker_url = db, docker_url
        self._adressen, self._ports = adressen, ports or alle_ports()
        self._lauf: asyncio.Task | None = None
        self.text, self.anteil, self.fehler = "", 0.0, ""

    @property
    def laeuft(self) -> bool:
        return self._lauf is not None and not self._lauf.done()

    def _melden(self, text: str, anteil: float) -> None:
        self.text, self.anteil = text, anteil

    def starten(self) -> bool:
        if self.laeuft:
            return False
        self.fehler = ""
        self._melden("Erkundung beginnt …", 0.0)
        self._lauf = asyncio.create_task(self._ablauf())
        return True

    async def warten(self) -> None:
        if self._lauf:
            await self._lauf

    async def _ablauf(self) -> None:
        try:
            netze = eigene_netze() if self._adressen is None else []
            adressen = ziele(netze) if self._adressen is None else self._adressen
            erg = await erkunden(adressen, self._ports, self._docker_url, self._melden, eigene=tuple(str(n.ip) for n in netze))
            erg.router, erg.eigene = standard_router(), [str(n.ip) for n in netze]
            speichern(self._db, erg)
            self._melden("Fertig.", 1.0)
        except Exception as e:  # der Lauf darf den Server nie mitreißen
            self.fehler = f"Die Erkundung ist abgebrochen: {type(e).__name__}"
            self._melden("", 0.0)
