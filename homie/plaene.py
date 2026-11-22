"""Pläne: Bevor Homie irgendetwas anlegt, entsteht ein Plan, den ein Mensch liest und bestätigt.

Ein Plan sagt in einfachen Worten, was passieren würde, was dafür geladen wird und woher, und was die
Prüfung des Rechners ergeben hat. Vorschlagen darf ihn der Mensch oder ein helfender Agent;
bestätigen kann ihn nur der angemeldete Mensch im Dashboard.

In dieser Datei steht kein einziger schreibender Aufruf an Proxmox. Ausgeführt wird ein bestätigter
Plan in ausfuehren.py.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from . import proxmox
from .db import Datenbank

IMAGE_NAME = "noble-server-cloudimg-amd64"
IMAGE_QUELLE = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
RESERVE_GB = 4     # so viel Arbeitsspeicher soll dem Rechner nach dem Anlegen mindestens frei bleiben


@dataclass(frozen=True)
class Zahl:
    name: str
    titel: str
    standard: int
    von: int
    bis: int
    einheit: str


@dataclass(frozen=True)
class Rezept:
    id: str
    titel: str
    beschreibung: str
    zahlen: tuple[Zahl, ...]


REZEPTE: tuple[Rezept, ...] = (
    Rezept(
        "docker-vm", "Neue VM mit Docker", "Eine frische virtuelle Maschine mit Ubuntu und Docker – die Grundlage für einen neuen Dienst.",
        (Zahl("kerne", "Prozessorkerne", 2, 1, 4, ""), Zahl("ram_gb", "Arbeitsspeicher", 4, 1, 8, "GB"), Zahl("platte_gb", "Platte", 32, 8, 64, "GB")),
    ),
)


class PlanFehler(Exception):
    """Meldung, die dem Nutzer (oder dem Agenten) gezeigt werden kann."""


def rezept(kennung: str) -> Rezept | None:
    return next((r for r in REZEPTE if r.id == kennung), None)


def _parameter(r: Rezept, eingabe: dict) -> dict:
    name = str(eingabe.get("name", "")).strip().lower()
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?", name):
        raise PlanFehler("Der Name darf nur Kleinbuchstaben, Ziffern und Bindestriche enthalten (höchstens 32 Zeichen).")
    werte = {"name": name}
    for z in r.zahlen:
        try:
            wert = int(str(eingabe.get(z.name, z.standard)).strip() or z.standard)
        except ValueError:
            raise PlanFehler(f"{z.titel}: bitte eine ganze Zahl eingeben.")
        if not z.von <= wert <= z.bis:
            raise PlanFehler(f"{z.titel}: erlaubt sind {z.von} bis {z.bis}{' ' + z.einheit if z.einheit else ''}.")
        werte[z.name] = wert
    eigener = " ".join(str(eingabe.get("ssh_schluessel", "")).split())
    if eigener:
        if not re.fullmatch(r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/=]{40,1000}( [\w@.+-]{1,80})?", eigener):
            raise PlanFehler("Das ist kein öffentlicher SSH-Schlüssel. Er beginnt mit „ssh-ed25519“ oder „ssh-rsa“ und ist eine einzige Zeile.")
        werte["ssh_schluessel"] = eigener
    return werte


async def entwerfen(db: Datenbank, zugang: tuple[str, dict[str, str]], kennung: str, eingabe: dict, von: str) -> int:
    """Liest den Rechner, prüft, schreibt den Plan auf. Ändert an Proxmox nichts."""
    r = rezept(kennung)
    if r is None:
        raise PlanFehler("Dieses Rezept gibt es nicht.")
    p = _parameter(r, eingabe)
    basis, schluessel = zugang
    try:
        async with proxmox.sitzung(schluessel["token-id"], schluessel["token"]) as s:
            lage = proxmox.aufbereiten(await proxmox.holen(s, basis, "/cluster/resources") or [])
            knoten = max((k for k in lage["knoten"] if k["an"]), key=lambda k: k["ram_frei"], default=None)
            if knoten is None:
                raise PlanFehler("In Proxmox ist kein Rechner eingeschaltet.")
            n = knoten["name"]
            nummer = await proxmox.holen(s, basis, "/cluster/nextid")
            speicher = await proxmox.holen(s, basis, f"/nodes/{n}/storage") or []
            netze = await proxmox.holen(s, basis, f"/nodes/{n}/network?type=bridge", pflicht=False) or []
            rechte = await proxmox.holen(s, basis, "/access/permissions", pflicht=False) or {}
            image = False
            for sp in speicher:
                if sp.get("active") and set(str(sp.get("content", "")).split(",")) & {"import", "iso"}:
                    inhalt = await proxmox.holen(s, basis, f"/nodes/{n}/storage/{sp['storage']}/content", pflicht=False) or []
                    image = image or any(IMAGE_NAME in str(v.get("volid", "")) for v in inhalt)
    except proxmox.ProxmoxFehler as e:
        raise PlanFehler(str(e)) from e

    platten = [sp for sp in speicher if sp.get("active") and "images" in str(sp.get("content", "")).split(",")]
    ziel = max(platten, key=lambda sp: sp.get("avail") or 0, default=None)
    bruecken = sorted(x.get("iface", "") for x in netze)
    bruecke = "vmbr0" if "vmbr0" in bruecken or not bruecken else bruecken[0]
    frei_danach = round(knoten["ram_frei"] - p["ram_gb"], 1)
    platz = round((ziel.get("avail") or 0) / proxmox.GIB) if ziel else 0

    pruefung = [
        {"ok": frei_danach >= RESERVE_GB,
         "text": f"Arbeitsspeicher: {_de(knoten['ram_frei'])} GB sind frei; nach dem Anlegen blieben {_de(frei_danach)} GB."
                 + ("" if frei_danach >= RESERVE_GB else f" Das ist zu knapp – mindestens {RESERVE_GB} GB sollen frei bleiben.")},
        {"ok": bool(ziel) and platz >= p["platte_gb"],
         "text": f"Plattenplatz: auf „{ziel['storage']}“ sind {platz} GB frei." if ziel else "Plattenplatz: Es gibt keinen Speicher für VM-Platten."},
        {"ok": not any(g["name"] == p["name"] for g in lage["gaeste"]),
         "text": f"Name „{p['name']}“ ist noch frei." if not any(g["name"] == p["name"] for g in lage["gaeste"]) else f"Den Namen „{p['name']}“ gibt es schon."},
    ]
    schritte = [
        "Das Ubuntu-24.04-Image liegt schon auf dem Rechner und wird wiederverwendet." if image else
        f"Ubuntu-24.04-Image laden: ca. 600 MB von {IMAGE_QUELLE} (offizielle Quelle, mit Prüfsumme).",
        f"Neue VM Nr. {nummer} „{p['name']}“ auf „{n}“ anlegen: {p['kerne']} Kerne, {p['ram_gb']} GB Arbeitsspeicher, "
        f"{p['platte_gb']} GB Platte auf „{ziel['storage'] if ziel else '?'}“, im Netz „{bruecke}“.",
        "Zugang nur mit einem Schlüssel, den Homie eigens dafür erzeugt und verschlüsselt ablegt. Es wird kein Passwort gesetzt.",
        "VM starten. Beim ersten Start richtet sie sich selbst ein und installiert Docker (lädt dafür Pakete von download.docker.com, ca. 400 MB).",
        "Homie sucht die neue VM im Heimnetz und zeigt sie im Netzplan.",
    ]
    grenzen = [
        "Keine bestehende VM und kein bestehender Container wird verändert, gestoppt oder gelöscht.",
        "Aus dem Internet wird nichts erreichbar gemacht.",
        "Rückgängig machen: Die neue VM lässt sich in Proxmox jederzeit löschen; sonst ändert sich nichts.",
    ]
    kann = lambda sp, was: sp.get("active") and was in str(sp.get("content", "")).split(",")
    technik = {"knoten": n, "vmid": nummer, "speicher": ziel["storage"] if ziel else "", "bruecke": bruecke, "image_vorhanden": image,
               "lager": next((sp["storage"] for sp in speicher if kann(sp, "import")), ""),
               "scheiben": next((sp["storage"] for sp in speicher if kann(sp, "iso")), "")}
    technik["rechte_fehlen"] = rechte_fehlen(rechte, technik)
    if p.get("ssh_schluessel"):
        schritte[2] += " Zusätzlich wird dein eigener öffentlicher Schlüssel hinterlegt, damit du selbst auf die VM kommst."
    jetzt = int(time.time())
    c = db.ausfuehren(
        "INSERT INTO plan (rezept, titel, parameter, inhalt, zustand, von, angelegt, geaendert) VALUES (?,?,?,?,'entwurf',?,?,?)",
        (r.id, f"{r.titel}: {p['name']}", json.dumps(p),
         json.dumps({"schritte": schritte, "pruefung": pruefung, "grenzen": grenzen, "technik": technik}), von[:80], jetzt, jetzt),
    )
    return c.lastrowid


def _zeile(z) -> dict:
    inhalt = json.loads(z["inhalt"])
    return {"id": z["id"], "rezept": z["rezept"], "titel": z["titel"], "parameter": json.loads(z["parameter"]), "zustand": z["zustand"],
            "von": z["von"], "angelegt": z["angelegt"], **inhalt, "machbar": all(p["ok"] for p in inhalt["pruefung"]),
            "protokoll": json.loads(z["protokoll"] or "[]"), "ergebnis": json.loads(z["ergebnis"] or "{}")}


def alle(db: Datenbank) -> list[dict]:
    return [_zeile(z) for z in db.alle("SELECT * FROM plan WHERE zustand != 'verworfen' ORDER BY id DESC")]


def einer(db: Datenbank, nummer: int) -> dict | None:
    z = db.eine("SELECT * FROM plan WHERE id=?", (nummer,))
    return _zeile(z) if z else None


VM_RECHTE = ("VM.Allocate", "VM.Config.Disk", "VM.Config.CPU", "VM.Config.Memory", "VM.Config.Network", "VM.Config.Options",
             "VM.Config.CDROM", "VM.PowerMgmt")


def _de(zahl: float) -> str:
    return f"{zahl:g}".replace(".", ",")


def _wirksam(rechte: dict, pfad: str) -> dict:
    """Rechte an einem Pfad; fehlt er, gelten die des nächsthöheren (Proxmox vererbt nach unten)."""
    while True:
        if pfad in rechte:
            return rechte[pfad] or {}
        if pfad in ("", "/"):
            return {}
        pfad = pfad.rsplit("/", 1)[0] or "/"


def rechte_fehlen(rechte: dict, technik: dict) -> list[str]:
    """Was dem Token zum Anlegen fehlt – in Worten. Leere Liste: alles da."""
    fehlt = []
    vm = {**_wirksam(rechte, f"/vms/{technik['vmid']}"), **rechte.get("/pool/homie", {})}
    if not all(vm.get(r) for r in VM_RECHTE):
        fehlt.append("virtuelle Maschinen anlegen, einstellen und starten")
    if not _wirksam(rechte, f"/storage/{technik['speicher']}").get("Datastore.AllocateSpace"):
        fehlt.append(f"Platz auf „{technik['speicher']}“ belegen")
    for sp in {technik.get("lager"), technik.get("scheiben")} - {"", None}:
        if not _wirksam(rechte, f"/storage/{sp}").get("Datastore.AllocateTemplate"):
            fehlt.append(f"Image und Startscheibe auf „{sp}“ ablegen")
    if not _wirksam(rechte, f"/sdn/zones/localnetwork/{technik['bruecke']}").get("SDN.Use"):
        fehlt.append(f"das Netz „{technik['bruecke']}“ benutzen")
    if not technik.get("image_vorhanden") and not _wirksam(rechte, "/").get("Sys.AccessNetwork"):
        fehlt.append("das Ubuntu-Image aus dem Internet laden")
    return fehlt


def rechte_befehle(token_id: str, technik: dict) -> list[str]:
    """Befehle für die Proxmox-Shell, die dem Token genau die nötigen Rechte geben – und keine an bestehenden VMs."""
    orte = ["/pool/homie", f"/storage/{technik['speicher']}"] + sorted({f"/storage/{sp}" for sp in (technik.get("lager"), technik.get("scheiben")) if sp} - {f"/storage/{technik['speicher']}"}) + ["/sdn/zones/localnetwork"]
    return [
        'pveum role add HomieAnlegen -privs "VM.Allocate VM.Audit VM.Config.CDROM VM.Config.CPU VM.Config.Disk VM.Config.Memory '
        'VM.Config.Network VM.Config.Options VM.PowerMgmt VM.GuestAgent.Audit Datastore.AllocateSpace Datastore.AllocateTemplate Datastore.Audit SDN.Use"',
        'pveum role add HomieLaden -privs "Sys.AccessNetwork Sys.Audit"',
        "pveum pool add homie",
        *[f"pveum acl modify {ort} -token '{token_id}' -role HomieAnlegen" for ort in orte],
        f"pveum acl modify / -token '{token_id}' -role HomieLaden",
    ]


def bestaetigen(db: Datenbank, nummer: int) -> bool:
    c = db.ausfuehren("UPDATE plan SET zustand='bestaetigt', geaendert=? WHERE id=? AND zustand='entwurf'", (int(time.time()), nummer))
    return c.rowcount == 1


def unterbrochene_markieren(db: Datenbank) -> None:
    """Nach einem Neustart von Homie: Läufe, die mittendrin waren, ehrlich als unterbrochen kennzeichnen."""
    for z in db.alle("SELECT id, protokoll FROM plan WHERE zustand IN ('bestaetigt', 'laeuft')"):
        protokoll = json.loads(z["protokoll"] or "[]") + [{"zeit": int(time.time()), "art": "fehler",
                    "text": "Homie wurde währenddessen neu gestartet. Bitte in Proxmox nachsehen, wie weit die neue VM gekommen ist."}]
        db.ausfuehren("UPDATE plan SET zustand='fehler', protokoll=? WHERE id=?", (json.dumps(protokoll), z["id"]))


def verwerfen(db: Datenbank, nummer: int) -> None:
    db.ausfuehren("UPDATE plan SET zustand='verworfen', geaendert=? WHERE id=? AND zustand='entwurf'", (int(time.time()), nummer))
