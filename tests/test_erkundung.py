"""Etappe 1: Erkundung, Verbinden und Netzplan – gegen nachgestellte Dienste auf dem eigenen Rechner.

Es wird nur 127.0.0.1 abgefragt; kein echtes Netz, keine echten Dienste.
"""
import datetime as dt
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
        if pfad.startswith("POST "):
            app.router.add_post(pfad[5:], antwort)
        else:
            app.router.add_get(pfad, antwort)
    return app


async def _ha_start(request):
    return web.Response(text="<html><head><title>Home Assistant</title></head></html>", content_type="text/html")


async def _ha_api(request):
    gut = request.headers.get("Authorization") == f"Bearer {GUT}"
    return web.json_response({"message": "API running."} if gut else {"message": "nein"}, status=200 if gut else 401)


def _ha(antwort):
    async def f(request):
        if request.headers.get("Authorization") != f"Bearer {GUT}":
            return web.json_response({"message": "nein"}, status=401)
        return web.json_response(antwort(request))
    return f


def _ha_termine(request):
    heute = dt.datetime.fromisoformat(request.query["start"])
    return [
        {"summary": "Zahnarzt", "location": "Praxis am Markt", "start": {"dateTime": (heute + dt.timedelta(hours=23, minutes=30)).isoformat()},
         "end": {"dateTime": (heute + dt.timedelta(hours=23, minutes=50)).isoformat()}},
        {"summary": "Geburtstag Oma", "start": {"date": (heute + dt.timedelta(days=1)).date().isoformat()}, "end": {"date": (heute + dt.timedelta(days=2)).date().isoformat()}},
    ]


HA = {
    "/": _ha_start, "/api/": _ha_api,
    "/api/calendars": _ha(lambda r: [{"entity_id": "calendar.privat", "name": "Privat"}]),
    "/api/calendars/calendar.privat": _ha(_ha_termine),
    "/api/states": _ha(lambda r: [
        {"entity_id": "todo.einkauf", "state": "2", "attributes": {"friendly_name": "Einkauf"}},
        {"entity_id": "weather.zuhause", "state": "partlycloudy", "attributes": {"temperature": 7.4, "temperature_unit": "°C", "humidity": 81}},
        {"entity_id": "sensor.irgendwas", "state": "1", "attributes": {}},
        {"entity_id": "sensor.handy_daily_steps", "state": "8432", "last_updated": dt.datetime.now(dt.timezone.utc).isoformat()},
        {"entity_id": "sensor.altes_handy_daily_steps", "state": "12", "last_updated": "2020-01-01T10:00:00+00:00"},
        {"entity_id": "sensor.handy_daily_distance", "state": "6240", "last_updated": "2020-01-01T10:00:00+00:00"},
        {"entity_id": "sensor.handy_heart_rate", "state": "61", "last_updated": "2020-01-01T10:00:00+00:00"},
        {"entity_id": "sensor.handy_resting_heart_rate", "state": "unknown"},
    ]),
    "/api/history/period/{start}": _ha(lambda r: [
        [{"entity_id": "sensor.handy_daily_steps", "state": "3000", "last_changed": dt.datetime.now(dt.timezone.utc).isoformat()},
         {"state": "8432", "last_changed": dt.datetime.now(dt.timezone.utc).isoformat()},
         {"state": "unavailable", "last_changed": dt.datetime.now(dt.timezone.utc).isoformat()}],
    ]),
    "POST /api/services/todo/get_items": _ha(lambda r: {"service_response": {"todo.einkauf": {"items": [
        {"summary": "Milch", "status": "needs_action"}, {"summary": "Paket abholen", "status": "needs_action", "due": "2020-01-01"}]}}}),
}


async def _ollama(request):
    return web.Response(text="Ollama is running")


async def _hinaus(request):
    raise web.HTTPFound("http://nach-draussen.invalid/")


DOKUMENTE = [{"id": n, "title": f"Beleg {n}", "correspondent": 1, "document_type": 2, "tags": [3], "created": "2026-03-0%d" % n, "page_count": 2}
             for n in range(1, 4)]


async def _pl_start(request):
    return web.Response(text="<title>Paperless-ngx sign in</title>", content_type="text/html")


def _pl(antwort):
    async def f(request):
        if request.headers.get("Authorization") != f"Token {GUT}":
            return web.json_response({"detail": "nein"}, status=401)
        return await antwort(request)
    return f


async def _pl_dokumente(request):
    q = request.query.get("query", "")
    treffer = [d for d in DOKUMENTE if q.lower() in d["title"].lower()]
    return web.json_response({"count": len(treffer), "results": treffer})


async def _pl_namen(request):
    return web.json_response({"results": [{"id": 1, "name": "Stadtwerke"}, {"id": 2, "name": "Rechnung"}, {"id": 3, "name": "Wohnung"}]})


async def _pl_zahlen(request):
    return web.json_response({"documents_total": 3, "documents_inbox": 1})


async def _pl_bild(request):
    return web.Response(body=b"RIFF....WEBP", content_type="image/webp")


PAPERLESS = {"/": _pl_start, "/api/documents/": _pl(_pl_dokumente), "/api/statistics/": _pl(_pl_zahlen),
             "/api/correspondents/": _pl(_pl_namen), "/api/document_types/": _pl(_pl_namen), "/api/tags/": _pl(_pl_namen),
             "/api/documents/{nr}/thumb/": _pl(_pl_bild)}


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
        for antworten in (HA, {"/": _ollama}, {"/": _hinaus}, {"/_ping": _ping, "/containers/json": _container}, PAPERLESS):
            s = TestServer(_dienst(antworten), host="127.0.0.1")
            await s.start_server()
            self.server.append(s)
        ha, ollama, hinaus, docker, self.paperless = (s.port for s in self.server)
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


    async def test_mein_tag_aus_home_assistant(self):
        await self.erkunden()
        ha = next(d["id"] for d in await (await self.c.get("/api/dienste")).json() if d["name"] == "Home Assistant")
        self.assertEqual((await self.c.get("/m/tag")).status, 404)
        await self.c.post(f"/dienst/{ha}/verbinden", data={"csrf": self.csrf, "token": GUT}, allow_redirects=False)
        self.assertTrue({"tag", "gesundheit"} <= self.aktiv())
        r = await self.c.get("/m/tag")
        text = await r.text()
        self.assertEqual(r.status, 200)
        for erwartet in ("Heute", "Zahnarzt", "23:30–23:50", "Praxis am Markt", "Morgen", "Geburtstag Oma", "ganztägig",
                         "Einkauf", "2 offen", "Milch", "Paket abholen", "überfällig", "teils bewölkt", "7 °C", "81 % Luftfeuchte"):
            self.assertIn(erwartet, text)
        self.assertNotIn(GUT, text)
        self.assertLess(text.index("Zahnarzt"), text.index("Geburtstag Oma"))
        # Gesundheit: Werte der Handy-App, der neuere Sensor gewinnt, Unbekanntes fehlt
        r = await self.c.get("/m/gesundheit")
        text = await r.text()
        self.assertEqual(r.status, 200)
        for erwartet in ("Schritte", "8.432", "Strecke", "6,2", "Puls", "61", "Verlauf", "width: 100%"):
            self.assertIn(erwartet, text)
        self.assertNotIn("Ruhepuls", text)
        self.assertNotIn(GUT, text)
        # Schlüssel wird ungültig → verständliche Meldung statt Absturz
        self.app[K_ABLAGE].setzen(module.schluesselname(ha, "token"), "abgelaufen")
        r = await self.c.get("/m/tag")
        self.assertEqual(r.status, 502)
        self.assertIn("lehnt den Schlüssel ab", await r.text())

    async def test_von_hand_hinzufuegen_und_dokumente_lesen(self):
        self.assertNotIn("Dokumente</a>", await (await self.c.get("/onboarding")).text())
        # Unsinn und Unbekanntes werden abgelehnt
        for adresse, meldung in (("ftp://x", "keine gültige Adresse"), (f"127.0.0.1:{self.server[2].port}", "kein Dienst, den Homie kennt"), ("127.0.0.1:1", "antwortet nichts")):
            r = await self.c.post("/dienst/neu", data={"csrf": self.csrf, "adresse": adresse})
            self.assertEqual(r.status, 400, adresse)
            self.assertIn(meldung, await r.text())
        r = await self.c.post("/dienst/neu", data={"csrf": self.csrf, "adresse": f"127.0.0.1:{self.paperless}/"}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        r = await self.c.post("/dienst/neu", data={"csrf": self.csrf, "adresse": f"http://127.0.0.1:{self.paperless}"})
        self.assertIn("schon eingetragen", await r.text())
        d = (await (await self.c.get("/api/dienste")).json())[0]
        self.assertEqual((d["name"], d["art"], d["zustand"]), ("Paperless-ngx", "dokumente", "gefunden"))
        # Von Hand Hinzugefügtes übersteht eine Erkundung
        await self.erkunden()
        self.assertIn("Paperless-ngx", [x["name"] for x in await (await self.c.get("/api/dienste")).json()])
        # vor dem Verbinden: Modul und Vorschau gesperrt
        self.assertEqual((await self.c.get("/m/dokumente")).status, 404)
        self.assertEqual((await self.c.get("/m/dokumente/vorschau/1")).status, 404)
        r = await self.c.post(f"/dienst/{d['id']}/verbinden", data={"csrf": self.csrf, "token": GUT}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        r = await self.c.get("/m/dokumente")
        text = await r.text()
        self.assertEqual(r.status, 200)
        for erwartet in ("Beleg 1", "Beleg 3", "Stadtwerke · Rechnung · 03.03.2026", "Wohnung", "Neueste Dokumente", "/m/dokumente/vorschau/2",
                         f"http://127.0.0.1:{self.paperless}/documents/1/details"):
            self.assertIn(erwartet, text)
        self.assertNotIn(GUT, text)
        text = await (await self.c.get("/m/dokumente?q=beleg+2")).text()
        self.assertIn("Beleg 2", text)
        self.assertNotIn("Beleg 3", text)
        self.assertIn("Nichts gefunden", await (await self.c.get("/m/dokumente?q=gibtsnicht")).text())
        r = await self.c.get("/m/dokumente/vorschau/2")
        self.assertEqual((r.status, r.content_type), (200, "image/webp"))
        # ohne Anmeldung: nichts davon
        self.c.session.cookie_jar.clear()
        for pfad in ("/m/dokumente", "/m/dokumente/vorschau/2"):
            self.assertEqual((await self.c.get(pfad, allow_redirects=False)).status, 303, pfad)


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
