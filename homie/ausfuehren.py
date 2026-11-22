"""Führt einen bestätigten Plan aus: legt auf Proxmox eine neue VM an und lässt sie sich selbst einrichten.

Das ist die einzige Datei in Homie, die an Proxmox schreibt. Feste Regeln, die hier im Code stehen:
- Es wird ausschließlich eine NEUE VM angelegt. Jeder Aufruf an einer VM nennt die Nummer, die beim Start
  nachweislich frei war; alles andere wird verweigert (siehe _vm).
- Es gibt keinen löschenden Aufruf. Schlägt ein Schritt fehl, bleibt stehen, was bis dahin entstanden ist,
  und das Protokoll sagt, was das ist.
- Vor dem ersten schreibenden Schritt wird der Rechner neu geprüft (Arbeitsspeicher, Platz, Nummer, Name).
- Geladen wird nur das im Plan genannte Ubuntu-Image, mit Prüfsumme von der offiziellen Quelle.
"""
from __future__ import annotations

import asyncio
import json
import time

import aiohttp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from . import proxmox, startscheibe
from .ablage import Ablage
from .db import Datenbank
from .plaene import IMAGE_NAME, IMAGE_QUELLE, RESERVE_GB

PRUEFSUMMEN = "https://cloud-images.ubuntu.com/noble/current/SHA256SUMS"
IMAGE_DATEI = IMAGE_NAME + ".qcow2"


class Abbruch(Exception):
    """Der Lauf hält an; die Meldung steht im Protokoll."""


class Lauf:
    def __init__(self, db: Datenbank, ablage: Ablage, zugang: tuple[str, dict[str, str]], plan: dict, pruefsummen_url: str = PRUEFSUMMEN,
                 geduld: float = 2.0, agent_minuten: float = 8.0):
        self.db, self.ablage, self.plan = db, ablage, plan
        self.basis, self.schluessel = zugang[0].rstrip("/"), zugang[1]
        self.pruefsummen_url, self.geduld, self.agent_minuten = pruefsummen_url, geduld, agent_minuten
        self.protokoll: list[dict] = []
        self.vmid: str | None = None
        self.knoten = ""

    # ---------- Protokoll ----------
    def _sagen(self, text: str, art: str = "info") -> None:
        self.protokoll.append({"zeit": int(time.time()), "text": text, "art": art})
        self.db.ausfuehren("UPDATE plan SET protokoll=?, geaendert=? WHERE id=?", (json.dumps(self.protokoll), int(time.time()), self.plan["id"]))

    def _zustand(self, zustand: str) -> None:
        self.db.ausfuehren("UPDATE plan SET zustand=?, geaendert=? WHERE id=?", (zustand, int(time.time()), self.plan["id"]))

    # ---------- Aufrufe ----------
    def _vm(self, rest: str = "") -> str:
        if not self.vmid or not str(self.vmid).isdigit():
            raise Abbruch("Interner Schutz: keine gültige Nummer für die neue VM.")
        return f"/nodes/{self.knoten}/qemu/{self.vmid}{rest}"

    async def _senden(self, s: aiohttp.ClientSession, methode: str, pfad: str, daten=None, wofuer: str = ""):
        assert methode in ("POST", "PUT")       # kein DELETE – nirgends
        try:
            if isinstance(daten, dict):
                daten = {k: str(v) for k, v in daten.items()}
            async with s.request(methode, self.basis + "/api2/json" + pfad, data=daten, allow_redirects=False) as r:
                if r.status == 200:
                    return (await r.json()).get("data")
                grund = (r.reason or "").strip()
                try:
                    antwort = await r.json(content_type=None)
                    grund = "; ".join(f"{k}: {v}" for k, v in (antwort.get("errors") or {}).items()) or antwort.get("message") or grund
                except (ValueError, aiohttp.ClientError):
                    pass
                if r.status in (401, 403):
                    raise Abbruch(f"Proxmox erlaubt das nicht ({wofuer}): {grund}. Dem Token fehlt dafür ein Recht.")
                raise Abbruch(f"Proxmox meldet einen Fehler ({wofuer}): {r.status} {grund}")
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
            raise Abbruch(f"Proxmox ist nicht erreichbar ({wofuer}).") from e

    async def _warten(self, s: aiohttp.ClientSession, auftrag, wofuer: str, minuten: float = 15) -> None:
        """Proxmox erledigt größere Schritte im Hintergrund; hier wird auf das Ende gewartet."""
        if not isinstance(auftrag, str) or not auftrag.startswith("UPID:"):
            return
        ende = time.time() + minuten * 60
        while time.time() < ende:
            stand = await proxmox.holen(s, self.basis, f"/nodes/{self.knoten}/tasks/{auftrag}/status", pflicht=False)
            if stand and stand.get("status") == "stopped":
                if stand.get("exitstatus") == "OK":
                    return
                raise Abbruch(f"{wofuer} ist gescheitert: {stand.get('exitstatus')}")
            await asyncio.sleep(self.geduld)
        raise Abbruch(f"{wofuer} dauert zu lange – bitte in Proxmox nachsehen.")

    # ---------- Ablauf ----------
    async def laufen(self) -> None:
        self._zustand("laeuft")
        try:
            async with proxmox.sitzung(self.schluessel["token-id"], self.schluessel["token"]) as s:
                await self._schritte(s)
            self._zustand("fertig")
        except (Abbruch, proxmox.ProxmoxFehler) as e:
            self._sagen(str(e), "fehler")
            self._sagen("Angehalten. Es wurde nichts gelöscht und nichts Bestehendes verändert."
                        + (f" Die neue VM Nr. {self.vmid} existiert möglicherweise schon in Proxmox." if self.vmid else ""), "fehler")
            self._zustand("fehler")
        except Exception as e:      # darf den Server nie mitreißen
            self._sagen(f"Unerwarteter Fehler: {type(e).__name__}. Angehalten.", "fehler")
            self._zustand("fehler")

    async def _schritte(self, s: aiohttp.ClientSession) -> None:
        p, t = self.plan["parameter"], self.plan["technik"]
        self.knoten = t["knoten"]

        # 1. Neu prüfen – der Plan kann alt sein.
        lage = proxmox.aufbereiten(await proxmox.holen(s, self.basis, "/cluster/resources") or [])
        knoten = next((k for k in lage["knoten"] if k["name"] == self.knoten and k["an"]), None)
        if knoten is None:
            raise Abbruch(f"Der Rechner „{self.knoten}“ ist nicht erreichbar.")
        if knoten["ram_frei"] - p["ram_gb"] < RESERVE_GB:
            raise Abbruch(f"Zu wenig Arbeitsspeicher: {knoten['ram_frei']:g} GB frei, gebraucht werden {p['ram_gb']} GB plus {RESERVE_GB} GB Reserve.")
        if any(g["name"] == p["name"] for g in lage["gaeste"]):
            raise Abbruch(f"Den Namen „{p['name']}“ gibt es inzwischen schon.")
        vergeben = {str(g["vmid"]) for g in lage["gaeste"]}
        nummer = str(await proxmox.holen(s, self.basis, "/cluster/nextid"))
        if nummer in vergeben or not nummer.isdigit():
            raise Abbruch("Proxmox nennt keine freie Nummer für die neue VM.")
        self.vmid = nummer
        speicher = await proxmox.holen(s, self.basis, f"/nodes/{self.knoten}/storage") or []
        kann = lambda sp, was: sp.get("active") and was in str(sp.get("content", "")).split(",")
        ziel = next((sp for sp in speicher if sp["storage"] == t["speicher"] and kann(sp, "images")), None)
        if ziel is None or (ziel.get("avail") or 0) / proxmox.GIB < p["platte_gb"]:
            raise Abbruch(f"Auf „{t['speicher']}“ ist nicht genug Platz für {p['platte_gb']} GB.")
        lager = next((sp["storage"] for sp in speicher if kann(sp, "import")), None)
        scheiben = next((sp["storage"] for sp in speicher if kann(sp, "iso")), None)
        if lager is None or scheiben is None:
            raise Abbruch("Auf dem Rechner fehlt ein Speicher, der Images („import“) und CD-Abbilder („iso“) aufnehmen darf.")
        self._sagen(f"Geprüft: {knoten['ram_frei']:g} GB Arbeitsspeicher frei, Nummer {self.vmid} ist frei, Name ist frei.", "gut")

        # 2. Ubuntu-Image bereitstellen.
        image = f"{lager}:import/{IMAGE_DATEI}"
        inhalt = await proxmox.holen(s, self.basis, f"/nodes/{self.knoten}/storage/{lager}/content", pflicht=False) or []
        if any(v.get("volid") == image for v in inhalt):
            self._sagen("Das Ubuntu-Image liegt bereit.", "gut")
        else:
            summe = await self._pruefsumme()
            self._sagen(f"Ubuntu-Image wird geladen (ca. 600 MB von {IMAGE_QUELLE}) …")
            auftrag = await self._senden(s, "POST", f"/nodes/{self.knoten}/storage/{lager}/download-url", {
                "url": IMAGE_QUELLE, "content": "import", "filename": IMAGE_DATEI, "checksum": summe, "checksum-algorithm": "sha256"}, "Image laden")
            await self._warten(s, auftrag, "Das Laden des Images", 30)
            self._sagen("Image geladen, Prüfsumme stimmt.", "gut")

        # 3. Zugangsschlüssel und Startscheibe.
        geheim = ed25519.Ed25519PrivateKey.generate()
        oeffentlich = geheim.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode() + f" homie-plan-{self.plan['id']}"
        self.ablage.setzen(f"plan:{self.plan['id']}:ssh", geheim.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()).decode())
        schluessel = [oeffentlich] + ([p["ssh_schluessel"]] if p.get("ssh_schluessel") else [])
        scheibe = startscheibe.abbild(startscheibe.anweisung(p["name"], schluessel, self.vmid))
        scheibenname = f"homie-start-{self.vmid}.iso"
        form = aiohttp.FormData()
        form.add_field("content", "iso")
        form.add_field("filename", scheibe, filename=scheibenname, content_type="application/octet-stream")
        await self._warten(s, await self._senden(s, "POST", f"/nodes/{self.knoten}/storage/{scheiben}/upload", form, "Startscheibe ablegen"), "Das Ablegen der Startscheibe")
        self._sagen("Zugangsschlüssel erzeugt (verschlüsselt abgelegt) und Einrichtungsanweisung für die VM hinterlegt.", "gut")

        # 4. VM anlegen – ab hier existiert etwas Neues in Proxmox.
        pools = await proxmox.holen(s, self.basis, "/pools", pflicht=False) or []
        daten = {
            "vmid": self.vmid, "name": p["name"], "cores": p["kerne"], "memory": p["ram_gb"] * 1024, "ostype": "l26", "agent": 1,
            "scsihw": "virtio-scsi-single", "scsi0": f"{t['speicher']}:0,import-from={image}",
            "ide2": f"{scheiben}:iso/{scheibenname},media=cdrom", "net0": f"virtio,bridge={t['bruecke']}",
            "boot": "order=scsi0", "tags": "homie", "description": f"Angelegt von Homie (Plan {self.plan['id']}).",
        }
        if any(x.get("poolid") == "homie" for x in pools):
            daten["pool"] = "homie"
        self._sagen(f"VM Nr. {self.vmid} „{p['name']}“ wird angelegt …")
        await self._warten(s, await self._senden(s, "POST", f"/nodes/{self.knoten}/qemu", daten, "VM anlegen"), "Das Anlegen der VM")
        await self._warten(s, await self._senden(s, "PUT", self._vm("/resize"), {"disk": "scsi0", "size": f"{p['platte_gb']}G"}, "Platte vergrößern"), "Das Vergrößern der Platte")
        self._sagen(f"VM angelegt: {p['kerne']} Kerne, {p['ram_gb']} GB Arbeitsspeicher, {p['platte_gb']} GB Platte.", "gut")

        # 5. Starten und auf das Lebenszeichen warten.
        await self._warten(s, await self._senden(s, "POST", self._vm("/status/start"), None, "VM starten"), "Das Starten der VM")
        self._sagen("VM gestartet. Sie richtet sich jetzt selbst ein; das erste Lebenszeichen kommt nach ein paar Minuten …")
        adresse = await self._lebenszeichen(s)
        ergebnis = {"vmid": self.vmid, "adresse": adresse}
        self.db.ausfuehren("UPDATE plan SET ergebnis=? WHERE id=?", (json.dumps(ergebnis), self.plan["id"]))
        if adresse:
            self._sagen(f"Fertig: Die VM ist unter {adresse} im Heimnetz. Docker wird in den nächsten Minuten fertig installiert.", "gut")
        else:
            self._sagen("Die VM läuft, hat sich aber noch nicht gemeldet. Sie ist in Proxmox zu sehen; ihre Adresse zeigt die nächste Erkundung.", "info")

    async def _pruefsumme(self) -> str:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
                async with s.get(self.pruefsummen_url) as r:
                    text = await r.text() if r.status == 200 else ""
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            text = ""
        for zeile in text.splitlines():
            teile = zeile.split()
            if len(teile) == 2 and teile[1].lstrip("*") == IMAGE_NAME + ".img" and len(teile[0]) == 64:
                return teile[0]
        raise Abbruch("Die Prüfsumme des Ubuntu-Images lässt sich nicht abrufen. Ohne Prüfsumme wird nichts geladen.")

    async def _lebenszeichen(self, s: aiohttp.ClientSession) -> str:
        ende = time.time() + self.agent_minuten * 60
        while time.time() < ende:
            antwort = await proxmox.holen(s, self.basis, self._vm("/agent/network-get-interfaces"), pflicht=False)
            for karte in (antwort or {}).get("result", []) if isinstance(antwort, dict) else []:
                for a in karte.get("ip-addresses", []):
                    if a.get("ip-address-type") == "ipv4" and not str(a.get("ip-address", "")).startswith("127."):
                        return a["ip-address"]
            await asyncio.sleep(self.geduld * 3)
        return ""


LAEUFE: dict[int, asyncio.Task] = {}


def starten(db: Datenbank, ablage: Ablage, zugang, plan: dict, **einstellungen) -> None:
    lauf = Lauf(db, ablage, zugang, plan, **einstellungen)
    LAEUFE[plan["id"]] = asyncio.create_task(lauf.laufen())
