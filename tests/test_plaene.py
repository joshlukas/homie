"""Etappe 3, Teil 1: Proxmox lesen, Pläne entwerfen, Agenten-Schnittstelle – gegen ein nachgestelltes Proxmox.

Das nachgestellte Proxmox zählt jeden Aufruf, der kein Lesen ist. Am Ende muss diese Liste leer sein.
"""
import re
import secrets
import tempfile
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from homie.config import laden
from homie.server import app_bauen

PW = secrets.token_urlsafe(18)
GEHEIM = secrets.token_urlsafe(16)
TOKEN_ID = "homie@pam!lesen"
GIB = 1024 ** 3
GESCHRIEBEN = []


def _daten(pfad: str):
    if pfad == "/version":
        return {"version": "9.0"}
    if pfad == "/cluster/resources":
        return [
            {"type": "node", "node": "knoten1", "status": "online", "maxcpu": 16, "maxmem": 64 * GIB, "mem": 54 * GIB},
            {"type": "qemu", "node": "knoten1", "vmid": 100, "name": "medien", "status": "running", "maxcpu": 4, "maxmem": 8 * GIB, "maxdisk": 100 * GIB},
            {"type": "lxc", "node": "knoten1", "vmid": 101, "name": "werbefilter", "status": "stopped", "maxcpu": 1, "maxmem": 1 * GIB, "maxdisk": 8 * GIB},
            {"type": "qemu", "node": "knoten1", "vmid": 900, "name": "vorlage", "status": "stopped", "template": 1, "maxmem": GIB},
            {"type": "storage", "node": "knoten1", "storage": "local"},
        ]
    if pfad == "/cluster/nextid":
        return "102"
    if pfad == "/nodes/knoten1/storage":
        return [{"storage": "local", "content": "iso,import,backup", "active": 1, "avail": 20 * GIB},
                {"storage": "tank", "content": "images,rootdir", "active": 1, "avail": 500 * GIB}]
    if pfad == "/nodes/knoten1/network":
        return [{"iface": "vmbr0", "type": "bridge"}]
    if pfad == "/nodes/knoten1/storage/local/content":
        return [{"volid": "local:iso/noble-server-cloudimg-amd64.img"}]
    return None


async def _proxmox(request):
    if request.method != "GET":
        GESCHRIEBEN.append((request.method, request.path))
        return web.json_response({"data": None}, status=403)
    if request.path == "/":
        return web.Response(text="<title>knoten1 - Proxmox Virtual Environment</title>", content_type="text/html")
    if request.headers.get("Authorization") != f"PVEAPIToken={TOKEN_ID}={GEHEIM}":
        return web.json_response({"data": None}, status=401)
    daten = _daten(request.path.removeprefix("/api2/json"))
    return web.json_response({"data": daten}, status=200 if daten is not None else 404)


class Plaene(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        GESCHRIEBEN.clear()
        fake = web.Application()
        fake.router.add_route("*", "/{pfad:.*}", _proxmox)
        self.rechner = TestServer(fake, host="127.0.0.1")
        await self.rechner.start_server()
        self.tmp = tempfile.TemporaryDirectory()
        self.app = app_bauen(laden({"HOMIE_DATA": self.tmp.name, "HOMIE_DOCKER_LESEN": "0"}), erkundung_ziele=[])
        self.c = TestClient(TestServer(self.app))
        await self.c.start_server()
        await self.c.post("/einrichten", data={"passwort": PW, "wiederholung": PW}, allow_redirects=False)
        text = await (await self.c.get("/onboarding")).text()
        self.csrf = text.split('name="csrf" value="')[1].split('"')[0]
        self.assertNotIn("Neue VM planen", text)        # ohne Proxmox kein Planformular
        r = await self.c.post("/dienst/neu", data={"csrf": self.csrf, "adresse": f"http://127.0.0.1:{self.rechner.port}"}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        r = await self.c.post("/dienst/1/verbinden", data={"csrf": self.csrf, "token-id": TOKEN_ID, "token": GEHEIM}, allow_redirects=False)
        self.assertEqual(r.status, 303)

    async def asyncTearDown(self):
        self.assertEqual(GESCHRIEBEN, [], "Homie darf an Proxmox nichts schreiben")
        await self.c.close()
        await self.rechner.close()
        self.tmp.cleanup()

    async def plan(self, **werte):
        return await self.c.post("/plan/neu", data={"csrf": self.csrf, "rezept": "docker-vm", **werte}, allow_redirects=False)

    async def test_netzplan_zeigt_vms(self):
        r = await self.c.get("/m/netzplan")
        text = await r.text()
        self.assertEqual(r.status, 200)
        for erwartet in ("Virtuelle Maschinen", "knoten1", "10 von 64 GB Arbeitsspeicher frei", "medien", "VM 100", "werbefilter", "Container 101"):
            self.assertIn(erwartet, text)
        self.assertNotIn("vorlage", text)
        self.assertNotIn(GEHEIM, text)

    async def test_plan_entwerfen_pruefen_verwerfen(self):
        for werte in ({"name": "Böser Name"}, {"name": "ok", "ram_gb": "64"}, {"name": "ok", "kerne": "viele"}):
            r = await self.plan(**werte)
            self.assertEqual(r.status, 400, werte)
        r = await self.c.post("/plan/neu", data={"csrf": self.csrf, "rezept": "gibtsnicht", "name": "x"})
        self.assertEqual(r.status, 400)
        r = await self.plan(name="dokumente", kerne="2", ram_gb="4", platte_gb="32")
        self.assertEqual((r.status, r.headers["Location"]), (303, "/plan/1"))
        text = await (await self.c.get("/plan/1")).text()
        for erwartet in ("Neue VM mit Docker: dokumente", "liegt schon auf dem Rechner", "Neue VM Nr. 102", "2 Kerne, 4 GB Arbeitsspeicher", "32 GB Platte auf „tank“",
                         "im Netz „vmbr0“", "10 GB sind frei; nach dem Anlegen blieben 6 GB", "kein Passwort", "Keine bestehende VM", "Bis jetzt wurde nichts angelegt",
                         "Bestätigen und ausführen (folgt)"):
            self.assertIn(erwartet, text)
        self.assertIn("Entwurf, machbar", await (await self.c.get("/onboarding")).text())
        # zu groß für den freien Arbeitsspeicher, Name schon vergeben → Plan entsteht, ist aber als nicht machbar markiert
        r = await self.plan(name="medien", ram_gb="8")
        text = await (await self.c.get(r.headers["Location"])).text()
        for erwartet in ("Das ist zu knapp", "Den Namen „medien“ gibt es schon", "So ist der Plan nicht machbar"):
            self.assertIn(erwartet, text)
        r = await self.c.post("/plan/2/verwerfen", data={"csrf": self.csrf}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        self.assertEqual((await self.c.get("/plan/2")).status, 404)
        self.assertEqual((await self.c.get("/plan/99")).status, 404)

    async def test_agent_darf_lesen_und_vorschlagen_sonst_nichts(self):
        self.assertEqual((await self.c.get("/agent/zustand")).status, 401)      # die Sitzung des Menschen gilt hier nicht
        seite = await (await self.c.post("/helfer/neu", data={"csrf": self.csrf, "name": "Testhelfer"})).text()
        schluessel = re.search(r"hm_[A-Za-z0-9_-]{40,}", seite).group(0)
        self.assertNotIn(schluessel, await (await self.c.get("/onboarding")).text())    # nur einmal sichtbar
        self.c.session.cookie_jar.clear()
        kopf = {"Authorization": f"Bearer {schluessel}"}
        for falsch in ({}, {"Authorization": "Bearer hm_falsch"}, {"Authorization": f"Bearer {GEHEIM}"}):
            self.assertEqual((await self.c.get("/agent/zustand", headers=falsch)).status, 401)
        start = await (await self.c.get("/agent", headers=kopf)).json()
        self.assertEqual(start["agent"], "Testhelfer")
        zustand = await self.c.get("/agent/zustand", headers=kopf)
        text = await zustand.text()
        self.assertEqual(zustand.status, 200)
        self.assertIn("Proxmox VE", text)
        self.assertNotIn(GEHEIM, text)
        self.assertNotIn(TOKEN_ID, text)
        self.assertEqual((await (await self.c.get("/agent/rezepte", headers=kopf)).json())[0]["id"], "docker-vm")
        # vorschlagen: geht, landet als Entwurf mit Absender
        r = await self.c.post("/agent/plaene", headers=kopf, json={"rezept": "docker-vm", "parameter": {"name": "notizen", "ram_gb": 2}})
        plan = await r.json()
        self.assertEqual((r.status, plan["zustand"], plan["von"], plan["machbar"]), (201, "entwurf", "Agent Testhelfer", True))
        self.assertEqual((await self.c.post("/agent/plaene", headers=kopf, json={"rezept": "docker-vm", "parameter": {"name": "x", "ram_gb": 99}})).status, 400)
        self.assertEqual((await self.c.post("/agent/plaene", headers=kopf, data="kein json")).status, 400)
        # alles andere bleibt dem Agenten verschlossen
        for pfad in ("/api/dienste", "/api/netzplan"):
            self.assertEqual((await self.c.get(pfad, headers=kopf)).status, 401, pfad)
        for pfad in ("/onboarding", "/plan/1", "/m/netzplan"):
            self.assertEqual((await self.c.get(pfad, headers=kopf, allow_redirects=False)).status, 303, pfad)
        for pfad in ("/plan/1/verwerfen", "/dienst/1/trennen", "/erkundung/start", "/helfer/neu", "/agent/plaene/1/bestaetigen"):
            r = await self.c.post(pfad, headers=kopf, data={"csrf": self.csrf}, allow_redirects=False)
            self.assertIn(r.status, (303, 404, 405), pfad)
        self.assertEqual(len(await (await self.c.get("/agent/plaene", headers=kopf)).json()), 1)
        # Schlüssel entziehen
        await self.c.post("/login", data={"passwort": PW}, allow_redirects=False)
        r = await self.c.post("/helfer/1/entziehen", data={"csrf": (await (await self.c.get("/onboarding")).text()).split('name="csrf" value="')[1].split('"')[0]}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        self.assertEqual((await self.c.get("/agent/zustand", headers=kopf)).status, 401)


if __name__ == "__main__":
    unittest.main()
