"""Etappe 1: Erkundung, Verbinden und Netzplan – gegen nachgestellte Dienste auf dem eigenen Rechner.

Es wird nur 127.0.0.1 abgefragt; kein echtes Netz, keine echten Dienste.
"""
import ipaddress
import secrets
import tempfile
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from homie import erkundung, katalog, module
from homie.config import laden
from homie.server import K_ABLAGE, K_DB, K_ERK, app_bauen

PW = secrets.token_urlsafe(18)
GUT = secrets.token_urlsafe(16)


def _dienst(antworten: dict) -> web.Application:
    app = web.Application()
    for pfad, antwort in antworten.items():
        app.router.add_get(pfad, antwort)
    return app


async def _ha_start(request):
    return web.Response(text="<html><head><title>Home Assistant</title></head></html>", content_type="text/html")


async def _ha_api(request):
    gut = request.headers.get("Authorization") == f"Bearer {GUT}"
    return web.json_response({"message": "API running."} if gut else {"message": "nein"}, status=200 if gut else 401)


async def _ollama(request):
    return web.Response(text="Ollama is running")


async def _hinaus(request):
    raise web.HTTPFound("http://nach-draussen.invalid/")


async def _ping(request):
    return web.Response(text="OK")


async def _container(request):
    return web.json_response([
        {"Names": ["/homie"], "Image": "homie", "State": "running", "Ports": [], "Labels": {"com.docker.compose.project": "homie"}},
        {"Names": ["/archiv"], "Image": "beispiel/archiv:1", "State": "exited", "Ports": [{"PublicPort": 8000}, {"PrivatePort": 5432}], "Labels": {}},
    ])


class Erkunden(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = []
        for antworten in ({"/": _ha_start, "/api/": _ha_api}, {"/": _ollama}, {"/": _hinaus}, {"/_ping": _ping, "/containers/json": _container}):
            s = TestServer(_dienst(antworten), host="127.0.0.1")
            await s.start_server()
            self.server.append(s)
        ha, ollama, hinaus, docker = (s.port for s in self.server)
        self.tmp = tempfile.TemporaryDirectory()
        einst = laden({"HOMIE_DATA": self.tmp.name, "HOMIE_DOCKER_URL": f"http://127.0.0.1:{docker}"})
        self.app = app_bauen(einst, erkundung_ziele=["127.0.0.1"], erkundung_ports=(ha, ollama, hinaus, 1))
        self.c = TestClient(TestServer(self.app))
        await self.c.start_server()
        r = await self.c.post("/einrichten", data={"passwort": PW, "wiederholung": PW}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        text = await (await self.c.get("/onboarding")).text()
        self.csrf = text.split('name="csrf" value="')[1].split('"')[0]

    async def asyncTearDown(self):
        await self.c.close()
        for s in self.server:
            await s.close()
        self.tmp.cleanup()

    async def erkunden(self):
        r = await self.c.post("/erkundung/start", data={"csrf": self.csrf}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        await self.app[K_ERK].warten()
        self.assertEqual(self.app[K_ERK].fehler, "")

    def aktiv(self):
        return {s.modul.id for s in module.stand(self.app[K_DB], self.app[K_ABLAGE]) if s.aktiv}

    async def test_erkundung_findet_dienste_und_container(self):
        self.assertEqual((await self.c.post("/erkundung/start", allow_redirects=False)).status, 403)  # ohne Sicherheitsmarke
        self.assertNotIn("netzplan", self.aktiv())
        await self.erkunden()
        dienste = await (await self.c.get("/api/dienste")).json()
        self.assertEqual(sorted(d["name"] for d in dienste), ["Home Assistant", "Ollama"])
        self.assertTrue(all(d["zustand"] == "gefunden" for d in dienste))
        stand = (await (await self.c.get("/api/erkundung")).json())["letzte"]
        self.assertEqual((stand["geraete"], stand["dienste"], stand["container"], stand["docker"]), (1, 2, 2, "bereit"))
        text = await (await self.c.get("/onboarding")).text()
        for erwartet in ("1 Geräte, 2 bekannte Dienste, 2 Container", "Home Assistant", "Ollama", "Erneut erkunden", "Langlebige Zugriffstoken"):
            self.assertIn(erwartet, text)
        # Netzplan ist jetzt freigeschaltet und zeigt Gerät, Dienste und Container
        self.assertIn("netzplan", self.aktiv())
        plan = await (await self.c.get("/m/netzplan")).text()
        for erwartet in ("127.0.0.1", "Home Assistant", "Ollama", "archiv", "2 Container"):
            self.assertIn(erwartet, plan)
        self.assertEqual((await self.c.get("/api/netzplan")).status, 200)

    async def test_verbinden_prueft_schluessel_und_schaltet_modul_frei(self):
        await self.erkunden()
        nr = {d["name"]: d["id"] for d in await (await self.c.get("/api/dienste")).json()}
        ha, ollama = nr["Home Assistant"], nr["Ollama"]
        # falscher Schlüssel: abgelehnt, nichts gespeichert
        r = await self.c.post(f"/dienst/{ha}/verbinden", data={"csrf": self.csrf, "token": "falsch"})
        self.assertEqual(r.status, 400)
        self.assertIn("lehnt den Schlüssel ab", await r.text())
        self.assertEqual(self.app[K_ABLAGE].namen(), [])
        self.assertNotIn("gesundheit", self.aktiv())
        # leeres Feld
        self.assertEqual((await self.c.post(f"/dienst/{ha}/verbinden", data={"csrf": self.csrf, "token": " "})).status, 400)
        # richtiger Schlüssel: geprüft, verschlüsselt abgelegt, Modul erscheint
        r = await self.c.post(f"/dienst/{ha}/verbinden", data={"csrf": self.csrf, "token": GUT}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        self.assertEqual(self.app[K_ABLAGE].lesen(module.schluesselname(ha, "token")), GUT)
        self.assertIn("gesundheit", self.aktiv())
        for pfad in ("/onboarding", "/api/dienste", "/api/netzplan", "/m/netzplan"):
            self.assertNotIn(GUT, await (await self.c.get(pfad)).text(), pfad)
        # Dienst ohne Schlüssel
        r = await self.c.post(f"/dienst/{ollama}/verbinden", data={"csrf": self.csrf}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        self.assertIn("aufnahme", self.aktiv())
        # erneute Erkundung behält den Zustand und legt nichts doppelt an
        await self.erkunden()
        dienste = await (await self.c.get("/api/dienste")).json()
        self.assertEqual(sorted((d["name"], d["zustand"]) for d in dienste), [("Home Assistant", "verbunden"), ("Ollama", "verbunden")])
        # trennen löscht den Schlüssel, ignorieren blendet aus
        await self.c.post(f"/dienst/{ha}/trennen", data={"csrf": self.csrf}, allow_redirects=False)
        self.assertEqual(self.app[K_ABLAGE].namen(), [])
        self.assertNotIn("gesundheit", self.aktiv())
        await self.c.post(f"/dienst/{ollama}/ignorieren", data={"csrf": self.csrf}, allow_redirects=False)
        self.assertNotIn("aufnahme", self.aktiv())
        self.assertIn("Ausgeblendet: 1", await (await self.c.get("/onboarding")).text())

    async def test_ohne_anmeldung_gesperrt(self):
        await self.erkunden()
        self.c.session.cookie_jar.clear()
        for pfad in ("/api/erkundung", "/api/netzplan"):
            self.assertEqual((await self.c.get(pfad)).status, 401)
        for pfad in ("/erkundung/start", "/dienst/1/verbinden", "/dienst/1/trennen"):
            r = await self.c.post(pfad, data={"csrf": self.csrf}, allow_redirects=False)
            self.assertEqual((r.status, r.headers["Location"]), (303, "/login"), pfad)
        self.assertEqual((await self.c.get("/m/netzplan", allow_redirects=False)).status, 303)


class Regeln(unittest.TestCase):
    def test_nur_private_netze_und_hoechstens_254_adressen(self):
        netz = ipaddress.IPv4Interface("198.51.100.40/16")
        adressen = erkundung.ziele([netz])
        self.assertEqual(len(adressen), 254)
        self.assertTrue(all(a.startswith("198.51.100.") for a in adressen))
        self.assertEqual(len(erkundung.ziele([ipaddress.IPv4Interface("192.0.2.5/28")])), 14)
        for n in erkundung.eigene_netze():
            self.assertTrue(n.ip.is_private)

    def test_katalog_ist_stimmig(self):
        self.assertEqual(len({e.id for e in katalog.KATALOG}), len(katalog.KATALOG))
        self.assertNotIn(9100, katalog.alle_ports())   # Druckerport: würde Papier bedrucken
        self.assertNotIn(22, katalog.alle_ports())
        arten = {e.art: {f.name for f in e.felder} for e in katalog.KATALOG}
        for m in module.MODULE:
            for b in m.braucht:
                if b.art != "*":
                    self.assertIn(b.art, arten, m.id)
                    self.assertTrue(set(b.schluessel) <= arten[b.art], m.id)


if __name__ == "__main__":
    unittest.main()
