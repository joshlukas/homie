"""Etappe 3: Proxmox lesen, Pläne entwerfen und ausführen, Agenten-Schnittstelle – gegen ein nachgestelltes Proxmox.

Das nachgestellte Proxmox schreibt jeden Aufruf mit, der kein Lesen ist. So lässt sich nachweisen, dass Homie
ohne Bestätigung nichts schreibt, beim Ausführen nur die neue VM anfasst und nie etwas löscht.
"""
import json
import re
import secrets
import tempfile
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from homie import ausfuehren, plaene
from homie.config import laden
from homie.db import Datenbank
from homie.server import K_ABLAGE, K_DB, app_bauen

PW = secrets.token_urlsafe(18)
GEHEIM = secrets.token_urlsafe(16)
KENNUNG = "homie@pam!lesen"
GIB = 1024 ** 3
SUMME = "ab" * 32
NUR_LESEN = {"/": {"Sys.Audit": 1, "VM.Audit": 1, "Datastore.Audit": 1}}
ALLES = {
    "/": {"Sys.Audit": 1, "Sys.AccessNetwork": 1},
    "/pool/homie": {r: 1 for r in plaene.VM_RECHTE},
    "/storage/tank": {"Datastore.AllocateSpace": 1},
    "/storage/local": {"Datastore.AllocateTemplate": 1},
    "/sdn/zones/localnetwork": {"SDN.Use": 1},
}


class Rechner:
    """Zustand des nachgestellten Proxmox für einen Test."""

    def __init__(self):
        self.rechte = NUR_LESEN
        self.geschrieben: list[tuple[str, str, dict]] = []
        self.frei_gb = 10
        self.inhalt = [{"volid": "local:iso/noble-server-cloudimg-amd64.img"}]
        self.gaeste = [
            {"type": "qemu", "node": "knoten1", "vmid": 100, "name": "medien", "status": "running", "maxcpu": 4, "maxmem": 8 * GIB, "maxdisk": 100 * GIB},
            {"type": "lxc", "node": "knoten1", "vmid": 101, "name": "werbefilter", "status": "stopped", "maxcpu": 1, "maxmem": 1 * GIB, "maxdisk": 8 * GIB},
            {"type": "qemu", "node": "knoten1", "vmid": 900, "name": "vorlage", "status": "stopped", "template": 1, "maxmem": GIB},
        ]
        self.verweigert: str | None = None      # Pfadende, bei dem das nachgestellte Proxmox „verboten“ sagt
        self.hochgeladen = b""

    def lesen(self, pfad: str):
        if pfad == "/version":
            return {"version": "9.2"}
        if pfad == "/cluster/resources":
            return [{"type": "node", "node": "knoten1", "status": "online", "maxcpu": 16, "maxmem": 64 * GIB, "mem": (64 - self.frei_gb) * GIB}, *self.gaeste]
        if pfad == "/cluster/nextid":
            return "102"
        if pfad == "/access/permissions":
            return self.rechte
        if pfad == "/pools":
            return [{"poolid": "homie"}]
        if pfad == "/nodes/knoten1/storage":
            return [{"storage": "local", "content": "iso,import,backup", "active": 1, "avail": 20 * GIB},
                    {"storage": "tank", "content": "images,rootdir", "active": 1, "avail": 500 * GIB}]
        if pfad == "/nodes/knoten1/network":
            return [{"iface": "vmbr0", "type": "bridge"}]
        if pfad == "/nodes/knoten1/storage/local/content":
            return self.inhalt
        if pfad.startswith("/nodes/knoten1/tasks/"):
            return {"status": "stopped", "exitstatus": "OK"}
        if pfad == "/nodes/knoten1/qemu/102/agent/network-get-interfaces":
            return {"result": [{"name": "lo", "ip-addresses": [{"ip-address": "127.0.0.1", "ip-address-type": "ipv4"}]},
                               {"name": "eth0", "ip-addresses": [{"ip-address": "192.0.2.77", "ip-address-type": "ipv4"}]}]}
        return None

    async def antworten(self, request: web.Request) -> web.Response:
        pfad = request.path.removeprefix("/api2/json")
        if request.method == "GET" and request.path == "/":
            return web.Response(text="<title>knoten1 - Proxmox Virtual Environment</title>", content_type="text/html")
        if request.headers.get("Authorization") != f"PVEAPIToken={KENNUNG}={GEHEIM}":
            return web.json_response({"data": None}, status=401)
        if request.method == "GET":
            daten = self.lesen(pfad)
            return web.json_response({"data": daten}, status=200 if daten is not None else 404)
        if request.content_type.startswith("multipart/"):
            felder = {}
            async for teil in await request.multipart():
                inhalt = await teil.read()
                felder[teil.name] = teil.filename or inhalt.decode()
                if teil.filename:
                    self.hochgeladen = bytes(inhalt)
        else:
            felder = dict(await request.post())
        self.geschrieben.append((request.method, pfad, felder))
        if self.verweigert and pfad.endswith(self.verweigert):
            return web.json_response({"data": None, "message": "Permission check failed"}, status=403)
        if pfad.endswith("/download-url"):
            self.inhalt = self.inhalt + [{"volid": f"local:import/{felder['filename']}"}]
        return web.json_response({"data": "UPID:knoten1:0001:" + pfad.rsplit("/", 1)[-1]})


class Plaene(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.r = Rechner()
        fake = web.Application(client_max_size=4 * 1024 * 1024)
        fake.router.add_route("*", "/{pfad:.*}", self.r.antworten)
        summen = web.Application()
        summen.router.add_get("/SHA256SUMS", lambda q: web.Response(text=f"{'cd' * 32} *anderes.img\n{SUMME} *noble-server-cloudimg-amd64.img\n"))
        self.rechner, self.summen = TestServer(fake, host="127.0.0.1"), TestServer(summen, host="127.0.0.1")
        await self.rechner.start_server()
        await self.summen.start_server()
        self.tmp = tempfile.TemporaryDirectory()
        self.app = app_bauen(laden({"HOMIE_DATA": self.tmp.name, "HOMIE_DOCKER_LESEN": "0"}), erkundung_ziele=[],
                             lauf={"pruefsummen_url": f"http://127.0.0.1:{self.summen.port}/SHA256SUMS", "geduld": 0.01, "agent_minuten": 0.02})
        self.c = TestClient(TestServer(self.app))
        await self.c.start_server()
        await self.c.post("/einrichten", data={"passwort": PW, "wiederholung": PW}, allow_redirects=False)
        text = await (await self.c.get("/onboarding")).text()
        self.csrf = text.split('name="csrf" value="')[1].split('"')[0]
        self.assertNotIn("Neue VM planen", text)        # ohne Proxmox kein Planformular
        r = await self.c.post("/dienst/neu", data={"csrf": self.csrf, "adresse": f"http://127.0.0.1:{self.rechner.port}"}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        r = await self.c.post("/dienst/1/verbinden", data={"csrf": self.csrf, "token-id": KENNUNG, "token": GEHEIM}, allow_redirects=False)
        self.assertEqual(r.status, 303)

    async def asyncTearDown(self):
        self.assertEqual([g for g in self.r.geschrieben if g[0] == "DELETE"], [], "Homie darf nie löschen")
        await self.c.close()
        await self.rechner.close()
        await self.summen.close()
        self.tmp.cleanup()

    async def plan(self, **werte):
        return await self.c.post("/plan/neu", data={"csrf": self.csrf, "rezept": "docker-vm", **werte}, allow_redirects=False)

    async def lauf(self, nummer: int = 1, **felder):
        r = await self.c.post(f"/plan/{nummer}/bestaetigen", data={"csrf": self.csrf, **felder}, allow_redirects=False)
        if nummer in ausfuehren.LAEUFE:
            await ausfuehren.LAEUFE.pop(nummer)
        return r

    async def test_netzplan_zeigt_vms(self):
        r = await self.c.get("/m/netzplan")
        text = await r.text()
        self.assertEqual(r.status, 200)
        for erwartet in ("Virtuelle Maschinen", "knoten1", "10 von 64 GB Arbeitsspeicher frei", "medien", "VM 100", "werbefilter", "Container 101"):
            self.assertIn(erwartet, text)
        self.assertNotIn("vorlage", text)
        self.assertNotIn(GEHEIM, text)
        self.assertEqual(self.r.geschrieben, [])

    async def test_plan_mit_nur_lesendem_schluessel(self):
        for werte in ({"name": "Böser Name"}, {"name": "ok", "ram_gb": "64"}, {"name": "ok", "kerne": "viele"}, {"name": "ok", "ssh_schluessel": "kein schlüssel"}):
            self.assertEqual((await self.plan(**werte)).status, 400, werte)
        self.assertEqual((await self.c.post("/plan/neu", data={"csrf": self.csrf, "rezept": "gibtsnicht", "name": "x"})).status, 400)
        r = await self.plan(name="dokumente", kerne="2", ram_gb="4", platte_gb="32")
        self.assertEqual((r.status, r.headers["Location"]), (303, "/plan/1"))
        text = await (await self.c.get("/plan/1")).text()
        for erwartet in ("Neue VM mit Docker: dokumente", "liegt schon auf dem Rechner", "Neue VM Nr. 102", "2 Kerne, 4 GB Arbeitsspeicher", "32 GB Platte auf „tank“",
                         "im Netz „vmbr0“", "10 GB sind frei; nach dem Anlegen blieben 6 GB", "kein Passwort", "Keine bestehende VM", "Bis jetzt wurde nichts angelegt",
                         "darf bisher nur lesen", "virtuelle Maschinen anlegen", "pveum pool add homie",
                         "pveum acl modify /pool/homie -token &#39;homie@pam!lesen&#39; -role HomieAnlegen", "pveum acl modify /storage/tank"):
            self.assertIn(erwartet, text)
        self.assertNotIn("/bestaetigen", text)          # kein Knopf …
        r = await self.lauf(gelesen="ja")               # … und auch der direkte Aufruf startet nichts
        self.assertEqual(r.headers["Location"], "/plan/1?fehler=1")
        self.assertIn("Entwurf, machbar", await (await self.c.get("/onboarding")).text())
        # zu groß für den freien Arbeitsspeicher, Name schon vergeben → als nicht machbar markiert
        r = await self.plan(name="medien", ram_gb="8")
        text = await (await self.c.get(r.headers["Location"])).text()
        for erwartet in ("Das ist zu knapp", "Den Namen „medien“ gibt es schon", "So ist der Plan nicht machbar"):
            self.assertIn(erwartet, text)
        self.assertEqual((await self.c.post("/plan/2/verwerfen", data={"csrf": self.csrf}, allow_redirects=False)).status, 303)
        self.assertEqual((await self.c.get("/plan/2")).status, 404)
        self.assertEqual((await self.c.get("/plan/99")).status, 404)
        self.assertEqual(self.r.geschrieben, [], "ohne Bestätigung darf nichts geschrieben werden")

    async def test_bestaetigter_plan_wird_ausgefuehrt(self):
        self.r.rechte = ALLES
        eigener = "ssh-ed25519 " + "A" * 68 + " ich@notebook"
        await self.plan(name="dokumente", kerne="2", ram_gb="4", platte_gb="32", ssh_schluessel=eigener)
        text = await (await self.c.get("/plan/1")).text()
        for erwartet in ("hat die nötigen Rechte", "/plan/1/bestaetigen", "Ich habe den Plan gelesen", "dein eigener öffentlicher Schlüssel"):
            self.assertIn(erwartet, text)
        self.assertNotIn("pveum", text)
        self.assertEqual((await self.lauf()).headers["Location"], "/plan/1?fehler=1")     # ohne Haken passiert nichts
        self.assertEqual(self.r.geschrieben, [])
        self.assertEqual((await self.lauf(gelesen="ja")).headers["Location"], "/plan/1")
        plan = plaene.einer(self.app[K_DB], 1)
        self.assertEqual(plan["zustand"], "fertig", plan["protokoll"])
        self.assertEqual(plan["ergebnis"], {"vmid": "102", "adresse": "192.0.2.77"})
        # genau diese Schreibaufrufe, in dieser Reihenfolge – und nur an der neuen VM
        wege = [(m, p) for m, p, _ in self.r.geschrieben]
        self.assertEqual(wege, [
            ("POST", "/nodes/knoten1/storage/local/download-url"), ("POST", "/nodes/knoten1/storage/local/upload"),
            ("POST", "/nodes/knoten1/qemu"), ("PUT", "/nodes/knoten1/qemu/102/resize"), ("POST", "/nodes/knoten1/qemu/102/status/start")])
        laden_, scheibe, vm, platte, _ = (f for _, _, f in self.r.geschrieben)
        self.assertEqual((laden_["content"], laden_["filename"], laden_["checksum"]), ("import", "noble-server-cloudimg-amd64.qcow2", SUMME))
        self.assertTrue(laden_["url"].startswith("https://cloud-images.ubuntu.com/"))
        self.assertEqual((scheibe["content"], scheibe["filename"]), ("iso", "homie-start-102.iso"))
        self.assertEqual({k: vm[k] for k in ("vmid", "name", "cores", "memory", "pool", "net0", "scsi0", "ide2")}, {
            "vmid": "102", "name": "dokumente", "cores": "2", "memory": "4096", "pool": "homie", "net0": "virtio,bridge=vmbr0",
            "scsi0": "tank:0,import-from=local:import/noble-server-cloudimg-amd64.qcow2", "ide2": "local:iso/homie-start-102.iso,media=cdrom"})
        self.assertNotIn("cipassword", vm)
        self.assertEqual(platte, {"disk": "scsi0", "size": "32G"})
        # Startscheibe: richtiges Format, beide öffentlichen Schlüssel, kein Passwort, kein privater Schlüssel
        self.assertEqual(self.r.hochgeladen[32769:32774], b"CD001")
        geheim = self.app[K_ABLAGE].lesen("plan:1:ssh")
        self.assertTrue(geheim.startswith("-----BEGIN OPENSSH") and "PRIVATE" in geheim[:40])
        for erwartet in (eigener.encode(), b"homie-plan-1", b"lock_passwd: true", b"ssh_pwauth: false", b"docker-ce", b"qemu-guest-agent"):
            self.assertIn(erwartet, self.r.hochgeladen)
        self.assertNotIn(b"PRIVATE KEY", self.r.hochgeladen)
        seite = await (await self.c.get("/plan/1")).text()
        for erwartet in ("Der Plan wurde ausgeführt", "Prüfsumme stimmt", "VM angelegt: 2 Kerne", "unter 192.0.2.77 im Heimnetz"):
            self.assertIn(erwartet, seite)
        for pfad in ("/plan/1", "/onboarding", "/api/dienste"):
            text = await (await self.c.get(pfad)).text()
            self.assertNotIn("PRIVATE KEY", text)
            self.assertNotIn(GEHEIM, text)
        # ein ausgeführter Plan lässt sich nicht noch einmal starten
        vorher = len(self.r.geschrieben)
        await self.lauf(gelesen="ja")
        self.assertEqual(len(self.r.geschrieben), vorher)

    async def test_lauf_haelt_an_wenn_sich_etwas_geaendert_hat_oder_proxmox_ablehnt(self):
        self.r.rechte = ALLES
        await self.plan(name="eins")
        self.r.frei_gb = 5                               # seit dem Plan ist der Arbeitsspeicher knapp geworden
        await self.lauf(1, gelesen="ja")
        plan = plaene.einer(self.app[K_DB], 1)
        self.assertEqual(plan["zustand"], "fehler")
        self.assertIn("Zu wenig Arbeitsspeicher", " ".join(z["text"] for z in plan["protokoll"]))
        self.assertEqual(self.r.geschrieben, [], "vor dem ersten Schreiben wird neu geprüft")
        self.r.frei_gb = 10
        self.r.inhalt = self.r.inhalt + [{"volid": "local:import/noble-server-cloudimg-amd64.qcow2"}]
        await self.plan(name="zwei")
        self.r.verweigert = "/qemu"                      # Proxmox lehnt das Anlegen ab
        await self.lauf(2, gelesen="ja")
        plan = plaene.einer(self.app[K_DB], 2)
        text = " ".join(z["text"] for z in plan["protokoll"])
        self.assertEqual(plan["zustand"], "fehler")
        for erwartet in ("Das Ubuntu-Image liegt bereit", "fehlt dafür ein Recht", "nichts gelöscht"):
            self.assertIn(erwartet, text)
        self.assertEqual([p for _, p, _ in self.r.geschrieben], ["/nodes/knoten1/storage/local/upload", "/nodes/knoten1/qemu"])   # kein Laden, kein Start
        self.assertIn("angehalten", await (await self.c.get("/onboarding")).text())

    async def test_agent_darf_lesen_und_vorschlagen_sonst_nichts(self):
        self.r.rechte = ALLES
        self.assertEqual((await self.c.get("/agent/zustand")).status, 401)      # die Sitzung des Menschen gilt hier nicht
        seite = await (await self.c.post("/helfer/neu", data={"csrf": self.csrf, "name": "Testhelfer"})).text()
        schluessel = re.search(r"hm_[A-Za-z0-9_-]{40,}", seite).group(0)
        self.assertNotIn(schluessel, await (await self.c.get("/onboarding")).text())    # nur einmal sichtbar
        self.c.session.cookie_jar.clear()
        kopf = {"Authorization": f"Bearer {schluessel}"}
        for falsch in ({}, {"Authorization": "Bearer hm_falsch"}, {"Authorization": f"Bearer {GEHEIM}"}):
            self.assertEqual((await self.c.get("/agent/zustand", headers=falsch)).status, 401)
        self.assertEqual((await (await self.c.get("/agent", headers=kopf)).json())["agent"], "Testhelfer")
        zustand = await self.c.get("/agent/zustand", headers=kopf)
        text = await zustand.text()
        self.assertEqual(zustand.status, 200)
        self.assertIn("Proxmox VE", text)
        self.assertNotIn(GEHEIM, text)
        self.assertNotIn(KENNUNG, text)
        self.assertEqual((await (await self.c.get("/agent/rezepte", headers=kopf)).json())[0]["id"], "docker-vm")
        r = await self.c.post("/agent/plaene", headers=kopf, json={"rezept": "docker-vm", "parameter": {"name": "notizen", "ram_gb": 2}})
        plan = await r.json()
        self.assertEqual((r.status, plan["zustand"], plan["von"], plan["machbar"]), (201, "entwurf", "Agent Testhelfer", True))
        self.assertEqual((await self.c.post("/agent/plaene", headers=kopf, json={"rezept": "docker-vm", "parameter": {"name": "x", "ram_gb": 99}})).status, 400)
        self.assertEqual((await self.c.post("/agent/plaene", headers=kopf, data="kein json")).status, 400)
        # alles andere bleibt dem Agenten verschlossen – vor allem das Bestätigen
        for pfad in ("/api/dienste", "/api/netzplan"):
            self.assertEqual((await self.c.get(pfad, headers=kopf)).status, 401, pfad)
        for pfad in ("/onboarding", "/plan/1", "/m/netzplan"):
            self.assertEqual((await self.c.get(pfad, headers=kopf, allow_redirects=False)).status, 303, pfad)
        for pfad in ("/plan/1/bestaetigen", "/plan/1/verwerfen", "/dienst/1/trennen", "/erkundung/start", "/helfer/neu", "/agent/plaene/1/bestaetigen"):
            r = await self.c.post(pfad, headers=kopf, data={"csrf": self.csrf, "gelesen": "ja"}, allow_redirects=False)
            self.assertIn(r.status, (303, 404, 405), pfad)
        self.assertEqual(plaene.einer(self.app[K_DB], 1)["zustand"], "entwurf")
        self.assertEqual(self.r.geschrieben, [])
        self.assertEqual(len(await (await self.c.get("/agent/plaene", headers=kopf)).json()), 1)
        await self.c.post("/login", data={"passwort": PW}, allow_redirects=False)
        marke = (await (await self.c.get("/onboarding")).text()).split('name="csrf" value="')[1].split('"')[0]
        self.assertEqual((await self.c.post("/helfer/1/entziehen", data={"csrf": marke}, allow_redirects=False)).status, 303)
        self.assertEqual((await self.c.get("/agent/zustand", headers=kopf)).status, 401)


class Bausteine(unittest.TestCase):
    def test_unterbrochener_lauf_wird_nach_neustart_gekennzeichnet(self):
        with tempfile.TemporaryDirectory() as t:
            db = Datenbank(Datenbank.__module__ and __import__("pathlib").Path(t) / "homie.sqlite")
            inhalt = json.dumps({"schritte": [], "pruefung": [], "grenzen": [], "technik": {}})
            db.ausfuehren("INSERT INTO plan (rezept, titel, parameter, inhalt, zustand, von, angelegt, geaendert) VALUES ('docker-vm','x','{}',?,'laeuft','dir',0,0)", (inhalt,))
            plaene.unterbrochene_markieren(db)
            plan = plaene.einer(db, 1)
            self.assertEqual(plan["zustand"], "fehler")
            self.assertIn("neu gestartet", plan["protokoll"][-1]["text"])
            db.schliessen()

    def test_rechte_werden_vererbt_gelesen(self):
        technik = {"vmid": "102", "speicher": "tank", "lager": "local", "scheiben": "local", "bruecke": "vmbr0", "image_vorhanden": True}
        self.assertEqual(plaene.rechte_fehlen(ALLES, technik), [])
        self.assertEqual(plaene.rechte_fehlen({"/": {r: 1 for r in (*plaene.VM_RECHTE, "Datastore.AllocateSpace", "Datastore.AllocateTemplate", "SDN.Use")}}, technik), [])
        self.assertEqual(len(plaene.rechte_fehlen(NUR_LESEN, technik)), 4)
        self.assertIn("aus dem Internet laden", " ".join(plaene.rechte_fehlen(NUR_LESEN, {**technik, "image_vorhanden": False})))


if __name__ == "__main__":
    unittest.main()
