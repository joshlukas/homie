"""Etappe 1: Erkundung, Verbinden und Netzplan – gegen nachgestellte Dienste auf dem eigenen Rechner.

Es wird nur 127.0.0.1 abgefragt; kein echtes Netz, keine echten Dienste.
"""
import datetime as dt
import ipaddress
import json
import pathlib
import secrets
import tempfile
import unittest

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from homie import erkundung, katalog, meintag, module, yamtrack
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
        {"entity_id": "sensor.handy_resting_heart_rate", "state": "unknown", "last_updated": dt.datetime.now(dt.timezone.utc).isoformat()},
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


DOKUMENTE = [{"id": n, "title": f"Beleg {n}", "correspondent": 1, "document_type": 2, "tags": [3, 4], "added": "2026-03-10T08:00:00+01:00", "created": "2026-03-0%d" % n, "page_count": 2}
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
    treffer = [{**d, "__search_hit__": {"highlights": f"Zahlbar bis <span class=\"match\">{q}</span> ohne Abzug"}} if q else d
               for d in DOKUMENTE if q.lower() in d["title"].lower()]
    return web.json_response({"count": len(treffer), "results": treffer, "next": None})


async def _pl_namen(request):
    return web.json_response({"results": [{"id": 1, "name": "Stadtwerke"}, {"id": 2, "name": "Rechnung"}, {"id": 3, "name": "Wohnung", "is_inbox_tag": True},
                                          {"id": 4, "name": "ai-processed"}]})


async def _pl_pdf(request):
    return web.Response(body=b"%PDF-1.7 " + b"x" * 200_000, content_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="Beleg Nr. 2 (Kopie).pdf"'})


async def _pl_zahlen(request):
    return web.json_response({"documents_total": 3, "documents_inbox": 1})


async def _pl_bild(request):
    return web.Response(body=b"RIFF....WEBP", content_type="image/webp")


PAPERLESS = {"/": _pl_start, "/api/documents/": _pl(_pl_dokumente), "/api/statistics/": _pl(_pl_zahlen),
             "/api/correspondents/": _pl(_pl_namen), "/api/document_types/": _pl(_pl_namen), "/api/tags/": _pl(_pl_namen),
             "/api/documents/{nr}/thumb/": _pl(_pl_bild), "/api/documents/{nr}/preview/": _pl(_pl_pdf), "/api/documents/{nr}/download/": _pl(_pl_pdf)}


ABGEGEBEN = []


def _nd(antwort):
    async def f(request):
        if request.headers.get("Authorization") != f"Bearer {GUT}":
            return web.json_response({"fehler": "nicht angemeldet"}, status=401)
        return await antwort(request)
    return f


async def _nd_eintraege(request):
    heute = dt.date.today().isoformat()
    return web.json_response({"seit": heute, "kategorien": {"einkauf": "Einkäufe und Ausgaben", "notiz": "Notizen"}, "eintraege": [
        {"id": 1, "zeit": heute + "T08:15:00+01:00", "tag": heute, "aufnahme": "a.m4a", "typ": "aufnahme", "text": "Rohtext der Aufnahme", "daten": {}},
        {"id": 2, "zeit": heute + "T08:15:00+01:00", "tag": heute, "aufnahme": "a.m4a", "typ": "einkauf", "text": "Brot beim Bäcker", "daten": {"betrag_eur": 3.4}},
        {"id": 3, "zeit": "2020-01-01T10:00:00+01:00", "tag": "2020-01-01", "aufnahme": "b.m4a", "typ": "fuer_claude", "text": "Frage an die KI", "daten": {"antwort": "Antwort der KI"}},
    ]})


async def _nd_finanzen(request):
    return web.json_response({
        "konten": [{"name": "Girokonto", "bank": "Testbank", "art": "giro", "saldo": 1234.5, "stand": "2026-03-04"}, {"name": "Karte", "bank": "Testbank", "art": "karte", "saldo": -87.1, "stand": "2026-03-03"}],
        "budget": {"frei": 412.0, "je_tag": 31.7, "rest_tage": 13, "ausgegeben": 388.0, "spielraum": 800.0, "ampel": "gruen"},
        "bilanz": {"2026-02": {"ein": 2500, "aus": -2100, "netto": 400}, "2026-03": {"ein": 2500, "aus": -2750.4, "netto": -250.4}},
        "prognose": {"giro_ende": 950.0, "posten_alt": [], "posten": [{"wer": "Miete", "betrag": -700, "gebucht": 0, "offen": -700, "tag": 3}, {"wer": "Strom", "betrag": -60, "gebucht": -60, "offen": 0, "tag": 15}]},
        "abos": [{"wer": "Musikdienst", "je_monat": -10.99}],
        "letzte": [{"tag": "2026-03-04", "wer": "Supermarkt", "zweck": "Kartenzahlung", "betrag": -23.45, "konto": "Girokonto"}], "hinweis": None,
        "cospend_offen": {"anzahl": 1, "summe": 31.9, "liste": [{"id": "u55", "tag": "2026-03-02", "wer": "DROGERIE 123", "betrag": 31.9, "name": "Drogerie"}]}})


async def _nd_aufnahme(request):
    ABGEGEBEN.append((request.headers.get("Content-Type"), len(await request.read())))
    return web.json_response({"ok": True, "name": "Aufnahme_test.webm"})


async def _nd_auszug(request):
    inhalt = await request.read()
    if not inhalt.startswith(b"Buchung;"):
        return web.json_response({"ok": False, "fehler": "Format nicht erkannt"}, status=400)
    return web.json_response({"ok": True, "konto": "Girokonto", "zeilen": 12, "neu": 3, "stand": "2026-03-04"})


EINGETRAGEN = []


async def _yt_ausfuehren(auftrag):
    EINGETRAGEN.append(auftrag)
    return {"ok": True, "verbucht": ["S01E02"], "titel": "Beispielserie"} if auftrag["aktion"] == "verbuchen" else {"kandidaten": []}


ENTSCHIEDEN = []


async def _nd_gesundheit(request):
    heute = dt.date.today()
    return web.json_response({
        "stand": heute.isoformat(), "tage": [{"tag": (heute - dt.timedelta(days=n)).isoformat(), "schritte": 4000 + n * 1000} for n in range(3)],
        "training": [{"id": "t1", "tag": heute.isoformat(), "dauer_min": 42, "art": "Laufen", "titel": "Abendrunde", "distanz_m": 6200, "quelle": "uhr"},
                     {"id": "t2", "tag": "2020-01-01", "dauer_min": 30, "art": "Gehen", "titel": "", "distanz_m": None, "quelle": "erkannt"}],
        "training_vorschlaege": [{"id": "2026-03-01T17:05", "tag": "2026-03-01", "von": "17:05", "bis": "17:40", "dauer_min": 35, "schritte": 4100}]})


async def _nd_profil(request):
    return web.json_response({"profil": "Trinkt morgens Tee.\nMag kurze Antworten.", "vorschlaege": [
        {"id": 7, "erstellt": "2026-03-01", "abschnitt": "Essen", "art": "ergänzen", "alt": "", "neu": "Isst mittags meist warm.", "begruendung": "Kam in fünf Notizen vor."}]})


async def _nd_cospend(request):
    return web.json_response({"projekt": "Haushalt", "saldo": {"Person A": 12.5, "Person B": -12.5},
                              "zeitraum": {"summe": 310.0, "anzahl": 9, "nach_kategorie": {"Lebensmittel": 200.0, "Restaurant": 110.0}},
                              "letzte": [{"tag": "2026-03-03", "was": "Wocheneinkauf", "betrag": 84.2, "zahler": "Person A", "kategorie": "Lebensmittel"}]})


async def _nd_ki(request):
    return web.json_response({"aktiv": True, "tageslimit": 1.5, "heute": {"tag": "2026-03-04", "usd": 0.42, "aufrufe": 6}, "guthaben": 17.3,
                              "tage": [{"tag": "2026-03-03", "usd": 0.1, "aufrufe": 2}, {"tag": "2026-03-04", "usd": 0.42, "aufrufe": 6}],
                              "modelle_30_tage": {"Sonnet": {"usd": 3.2, "aufrufe": 40}}})


HANDY = "Bearer " + secrets.token_urlsafe(24)      # das Geheimnis der Handy-App; Homie kennt es nicht
GELIEFERT = []


async def _nd_lieferung(request):
    if request.headers.get("Authorization") != HANDY:
        return web.json_response({"fehler": "Signatur stimmt nicht"}, status=401)
    GELIEFERT.append(await request.read())
    return web.json_response({"ok": True, "tage": 1})


def _nd_entscheid(art):
    async def f(request):
        ENTSCHIEDEN.append((art, await request.json()))
        return web.json_response({"ok": True})
    return f


NOTIZDIENST = {"/api/eintraege": _nd(_nd_eintraege), "/api/finanzen": _nd(_nd_finanzen), "POST /api/aufnahme": _nd(_nd_aufnahme), "POST /api/finanzen/import": _nd(_nd_auszug),
               "/api/gesundheit": _nd(_nd_gesundheit), "/api/profil": _nd(_nd_profil), "/api/cospend": _nd(_nd_cospend), "/api/claude": _nd(_nd_ki),
               "POST /api/health-webhook": _nd_lieferung,
               **{f"POST /api/{art}/entscheid": _nd(_nd_entscheid(art)) for art in ("finanzen", "training", "profil", "betrag")}}


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
        for antworten in (HA, {"/": _ollama}, {"/": _hinaus}, {"/_ping": _ping, "/containers/json": _container}, PAPERLESS, NOTIZDIENST):
            s = TestServer(_dienst(antworten), host="127.0.0.1")
            await s.start_server()
            self.server.append(s)
        ha, ollama, hinaus, docker, self.paperless, self.notizdienst = (s.port for s in self.server)
        self.helfer = TestServer(yamtrack.helfer_app(_yt_ausfuehren), host="127.0.0.1")
        await self.helfer.start_server()
        self.server.append(self.helfer)
        self.tmp = tempfile.TemporaryDirectory()
        einst = laden({"HOMIE_DATA": self.tmp.name, "HOMIE_DOCKER_URL": f"http://127.0.0.1:{docker}",
                       "HOMIE_YAMTRACK_SCHREIBEN": "1", "HOMIE_YAMTRACK_URL": f"http://127.0.0.1:{self.helfer.port}"})
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
        plan = await (await self.c.get("/blueprint/netz")).text()
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
        for pfad in ("/onboarding", "/api/dienste", "/api/netzplan", "/blueprint/netz"):
            self.assertNotIn(GUT, await (await self.c.get(pfad)).text(), pfad)
        # Dienst ohne Schlüssel
        r = await self.c.post(f"/dienst/{ollama}/verbinden", data={"csrf": self.csrf}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        # erneute Erkundung behält den Zustand und legt nichts doppelt an
        await self.erkunden()
        dienste = await (await self.c.get("/api/dienste")).json()
        self.assertEqual(sorted((d["name"], d["zustand"]) for d in dienste), [("Home Assistant", "verbunden"), ("Ollama", "verbunden")])
        # trennen löscht den Schlüssel, ignorieren blendet aus
        await self.c.post(f"/dienst/{ha}/trennen", data={"csrf": self.csrf}, allow_redirects=False)
        self.assertEqual(self.app[K_ABLAGE].namen(), [])
        self.assertNotIn("gesundheit", self.aktiv())
        await self.c.post(f"/dienst/{ollama}/ignorieren", data={"csrf": self.csrf}, allow_redirects=False)
        self.assertIn("Ausgeblendet: 1", await (await self.c.get("/onboarding")).text())

    async def test_ohne_anmeldung_gesperrt(self):
        await self.erkunden()
        self.c.session.cookie_jar.clear()
        for pfad in ("/api/erkundung", "/api/netzplan"):
            self.assertEqual((await self.c.get(pfad)).status, 401)
        for pfad in ("/erkundung/start", "/dienst/1/verbinden", "/dienst/1/trennen"):
            r = await self.c.post(pfad, data={"csrf": self.csrf}, allow_redirects=False)
            self.assertEqual((r.status, r.headers["Location"]), (303, "/login"), pfad)
        self.assertEqual((await self.c.get("/blueprint/netz", allow_redirects=False)).headers["Location"], "/login")


    async def test_mein_tag_aus_home_assistant(self):
        await self.erkunden()
        ha = next(d["id"] for d in await (await self.c.get("/api/dienste")).json() if d["name"] == "Home Assistant")
        self.assertEqual((await self.c.get("/m/tag")).status, 404)
        await self.c.post(f"/dienst/{ha}/verbinden", data={"csrf": self.csrf, "token": GUT}, allow_redirects=False)
        self.assertTrue({"tag", "gesundheit"} <= self.aktiv())
        r = await self.c.get("/m/tag")
        text = await r.text()
        self.assertEqual(r.status, 200)
        for erwartet in ("/static/mein-tag.js", "/static/mein-tag.css", 'id="hinweise"', "data-csrf=", 'href="/m/tag" aria-current="page"', "Abmelden"):
            self.assertIn(erwartet, text)
        self.assertIn("img-src 'self' data: https:", r.headers["Content-Security-Policy"])
        self.assertNotIn(GUT, text)
        for datei in ("mein-tag.js", "mein-tag.css"):
            r = await self.c.get(f"/static/{datei}")
            self.assertEqual(r.status, 200)
            self.assertNotIn("googleapis", await r.text())          # nichts von außen
        # der eine Abruf, aus dem die Seite alles zeichnet
        d = await (await self.c.get("/api/tag?tage=7")).json()
        self.assertEqual([t["titel"] for t in d["kalender"]["termine"]], ["Zahnarzt", "Geburtstag Oma"])
        self.assertEqual((d["kalender"]["termine"][1]["ganztags"], d["kalender"]["kalender"]), (True, ["Privat"]))
        self.assertEqual(d["gesundheit"]["aktuell"]["schritte"]["wert"], 8432)          # der neuere von zwei Sensoren
        self.assertEqual(d["gesundheit"]["aktuell"]["puls"]["wert"], 61)
        self.assertNotIn("ruhepuls", d["gesundheit"]["aktuell"])                        # „unknown“ fehlt
        self.assertEqual((len(d["gesundheit"]["tage"]), d["gesundheit"]["tage"][-1]["schritte"]), (30, 8432))   # der Guide vergleicht mit einem Monat
        self.assertEqual(d["tage"], 7)
        self.assertEqual({"kopf", "hinweise", "agenda", "ampeln", "ruhig"} - set(d["guide"]), set())
        self.assertTrue(any("nicht verbunden" in f for f in d["fehler"]))               # Notiz-Assistent fehlt hier noch
        self.assertEqual((d["finanzen"], d["yamtrack"], d["eintraege"]), (None, None, []))
        self.assertNotIn(GUT, json.dumps(d))
        # Gesundheit: Werte der Handy-App, der neuere Sensor gewinnt, Unbekanntes fehlt
        r = await self.c.get("/m/gesundheit")
        text = await r.text()
        self.assertEqual(r.status, 200)
        for erwartet in ("Schritte", "8.432", "Strecke", "6,2", "Puls", "61", "Verlauf", "width: 100%"):
            self.assertIn(erwartet, text)
        self.assertNotIn("Ruhepuls", text)
        self.assertNotIn(GUT, text)
        # mit Notiz-Assistent: Einträge, Finanzen, geteilte Ausgaben, Profil, KI-Kosten und der lange Verlauf kommen dazu
        await self.c.post("/dienst/neu", data={"csrf": self.csrf, "adresse": f"127.0.0.1:{self.notizdienst}"}, allow_redirects=False)
        nd = next(x["id"] for x in await (await self.c.get("/api/dienste")).json() if x["name"] == "Notiz-Assistent")
        await self.c.post(f"/dienst/{nd}/verbinden", data={"csrf": self.csrf, "token": GUT}, allow_redirects=False)
        self.app[K_DB].ausfuehren("INSERT INTO merk (name, wert) VALUES ('ich', 'Person A')")
        d = await (await self.c.get("/api/tag?tage=30")).json()
        self.assertEqual(d["fehler"], [])
        self.assertEqual((d["ich"], len(d["eintraege"]), d["kategorien"]["notiz"], d["cospend"]["saldo"]["Person A"]), ("Person A", 3, "Notizen", 12.5))
        self.assertEqual((d["finanzen"]["budget"]["frei"], d["claude"]["heute"]["aufrufe"], d["profil"]["vorschlaege"][0]["id"]), (412.0, 6, 7))
        self.assertEqual((len(d["gesundheit"]["training"]), len(d["gesundheit"]["training_vorschlaege"]), len(d["gesundheit"]["tage"])), (2, 1, 30))
        # bestätigen direkt aus der Seite: nur mit Sicherheitsmarke
        ENTSCHIEDEN.clear()
        self.assertEqual((await self.c.post("/api/tag/entscheid/training", json={"id": "x", "annehmen": True})).status, 403)
        r = await self.c.post("/api/tag/entscheid/profil", json={"id": 7, "annehmen": False}, headers={"X-Homie-CSRF": self.csrf})
        self.assertEqual(await r.json(), {"ok": True})
        self.assertEqual(ENTSCHIEDEN, [("profil", {"id": 7, "annehmen": False})])
        # Rückfrage zu einem auffälligen Betrag: die Nummer geht als Zahl weiter
        r = await self.c.post("/api/tag/entscheid/betrag", json={"id": "4", "annehmen": True}, headers={"X-Homie-CSRF": self.csrf})
        self.assertEqual((await r.json(), ENTSCHIEDEN[-1]), ({"ok": True}, ("betrag", {"id": 4, "annehmen": True})))
        # ein Dienst fällt aus → die Seite bekommt den Rest und eine Meldung statt eines Absturzes
        self.app[K_ABLAGE].setzen(module.schluesselname(ha, "token"), "abgelaufen")
        meintag._merker.clear()
        d = await (await self.c.get("/api/tag")).json()
        self.assertEqual(len(d["eintraege"]), 3)
        self.assertTrue(any("Kalender" in f for f in d["fehler"]))
        self.c.session.cookie_jar.clear()
        self.assertEqual((await self.c.get("/api/tag")).status, 401)

    async def test_notiz_assistent_aufnahme_und_finanzen(self):
        ABGEGEBEN.clear()
        r = await self.c.post("/dienst/neu", data={"csrf": self.csrf, "adresse": f"127.0.0.1:{self.notizdienst}"}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        d = (await (await self.c.get("/api/dienste")).json())[0]
        self.assertEqual((d["name"], d["art"]), ("Notiz-Assistent", "assistent"))
        ton = b"\x1a\x45\xdf\xa3" + b"0" * 5000
        kopf = {"Content-Type": "audio/webm;codecs=opus", "X-Homie-CSRF": self.csrf}
        self.assertEqual((await self.c.post("/m/aufnahme/senden", data=ton, headers=kopf)).status, 404)   # noch nicht verbunden
        self.assertEqual((await self.c.post(f"/dienst/{d['id']}/verbinden", data={"csrf": self.csrf, "token": "falsch"})).status, 400)
        r = await self.c.post(f"/dienst/{d['id']}/verbinden", data={"csrf": self.csrf, "token": GUT}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        self.assertTrue({"aufnahme", "finanzen"} <= self.aktiv())
        # Aufnahme: der große Knopf wie im alten Dashboard; was daraus wurde, steht in „Mein Tag“
        r = await self.c.get("/m/aufnahme")
        text = await r.text()
        self.assertEqual(r.status, 200)
        for erwartet in ('id="knopf"', 'id="zeit"', 'id="nachsenden"', "Sprachnotiz", "/static/aufnahme.js", "/static/aufnahme.css", "data-csrf=", 'href="/m/aufnahme" aria-current="page"'):
            self.assertIn(erwartet, text)
        self.assertNotIn(GUT, text)
        skript = await (await self.c.get("/static/aufnahme.js")).text()
        for erwartet in ("/m/aufnahme/senden", "X-Homie-CSRF", "indexedDB", "wakeLock"):
            self.assertIn(erwartet, skript)
        self.assertNotIn("serviceWorker", skript)
        d = await (await self.c.get("/api/tag?tage=30")).json()                 # die Einträge selbst
        self.assertEqual([e["text"] for e in d["eintraege"]][:2], ["Rohtext der Aufnahme", "Brot beim Bäcker"])
        # Aufnahme abgeben: nur mit Sicherheitsmarke, nur Ton, wird an den Assistenten durchgereicht
        self.assertEqual((await self.c.post("/m/aufnahme/senden", data=ton, headers={"Content-Type": "audio/webm"})).status, 403)
        self.assertEqual((await self.c.post("/m/aufnahme/senden", data=b"x" * 3000, headers={"Content-Type": "text/plain", "X-Homie-CSRF": self.csrf})).status, 415)
        r = await self.c.post("/m/aufnahme/senden", data=ton, headers=kopf)
        self.assertEqual((r.status, await r.json()), (200, {"ok": True, "name": "Aufnahme_test.webm"}))
        self.assertEqual(ABGEGEBEN[-1], ("audio/webm;codecs=opus", len(ton)))
        self.assertEqual((await self.c.get("/static/aufnahme.js")).status, 200)
        # Finanzen
        text = await (await self.c.get("/m/finanzen")).text()
        for erwartet in ("412 €", "noch 13 Tage", "ausgegeben von 800 €", "950 €", "Girokonto", "1.234,50 €", "-87,10 €", "Stand 4.3.2026",
                         "Miete", "meist um den 3.", "Musikdienst", "10,99 € / Monat", "Supermarkt", "-23,45 €", "Mär", "-250 €", "ampel-gruen"):
            self.assertIn(erwartet, text)
        self.assertNotIn("Strom", text)      # schon gebucht, also nicht mehr offen
        self.assertNotIn(GUT, text)
        self.c.session.cookie_jar.clear()
        for pfad in ("/m/aufnahme", "/m/finanzen"):
            self.assertEqual((await self.c.get(pfad, allow_redirects=False)).status, 303)
        r = await self.c.post("/m/aufnahme/senden", data=ton, headers=kopf, allow_redirects=False)
        self.assertEqual(r.status, 303)
        self.assertEqual(len(ABGEGEBEN), 1)

    async def test_uebernommenes_aus_dem_alten_dashboard(self):
        ENTSCHIEDEN.clear()
        await self.erkunden()
        # Übersicht: Zustand in diesem Augenblick; ein Dienst, der nicht antwortet, fällt auf
        self.app[K_DB].ausfuehren("INSERT INTO dienst (art, name, adresse, zustand, gefunden, details) VALUES ('medien','Abgeschaltet','http://127.0.0.1:1','gefunden',0,'{\"quelle\": \"hand\"}')")
        r = await self.c.get("/", allow_redirects=False)
        self.assertEqual(r.headers["Location"], "/blueprint")          # „Mein Tag“ ist hier noch nicht freigeschaltet
        r = await self.c.get("/blueprint", allow_redirects=False)
        self.assertEqual(r.headers["Location"], "/blueprint/dienste")  # ohne eigenen Plan ist „Dienste“ der erste Bereich
        text = await (await self.c.get("/blueprint/dienste")).text()
        for erwartet in ("2 <small>von 3</small>", "Home Assistant", "erreichbar", "Abgeschaltet", "antwortet nicht", 'href="/blueprint" aria-current="page"',
                         '<a href="/blueprint/dienste" aria-current="page">Dienste</a>', '<a href="/blueprint/netz">Netz</a>'):
            self.assertIn(erwartet, text)
        self.assertNotIn(">Assistent</a>", text)                       # Bereich erscheint erst mit verbundenem Notiz-Assistenten
        for alt, neu in (("/uebersicht", "/blueprint/dienste"), ("/m/netzplan", "/blueprint/netz")):
            r = await self.c.get(alt, allow_redirects=False)
            self.assertEqual((r.status, r.headers["Location"]), (303, neu), alt)
        self.assertLess(text.index("Abgeschaltet"), text.index("Home Assistant"))      # Ausfälle zuerst
        # Notiz-Assistent und Home Assistant verbinden
        await self.c.post("/dienst/neu", data={"csrf": self.csrf, "adresse": f"127.0.0.1:{self.notizdienst}"}, allow_redirects=False)
        nr = {d["name"]: d["id"] for d in await (await self.c.get("/api/dienste")).json()}
        for name in ("Notiz-Assistent", "Home Assistant"):
            r = await self.c.post(f"/dienst/{nr[name]}/verbinden", data={"csrf": self.csrf, "token": GUT}, allow_redirects=False)
            self.assertEqual(r.status, 303)
        self.assertIn("assistent", self.aktiv())
        # Gesundheit: zusätzlich langer Verlauf, Trainings, Vorschlag
        text = await (await self.c.get("/m/gesundheit")).text()
        for erwartet in ("Schritte · 30 Tage", "Durchschnitt 5.000", "Abendrunde", "42 Min.", "6,2 km", "geschätzt", "War das ein Training?", "35 Minuten zügig gegangen", "/m/entscheid/training"):
            self.assertIn(erwartet, text)
        # Finanzen: geteilte Ausgaben und Vorschlag
        text = await (await self.c.get("/m/finanzen")).text()
        for erwartet in ("Geteilte Ausgaben", "Person A", "bekommt noch", "12,50 €", "Person B", "schuldet noch", "310 € in den letzten 30 Tagen", "Wocheneinkauf",
                         "Geteilte Ausgabe?", "Drogerie", "31,90 €", "/m/entscheid/finanzen"):
            self.assertIn(erwartet, text)
        # Assistent: KI-Nutzung, Profil, Vorschlag
        r = await self.c.get("/m/assistent", allow_redirects=False)
        self.assertEqual(r.headers["Location"], "/blueprint/assistent")
        text = await (await self.c.get("/blueprint/assistent")).text()
        self.assertIn('<a href="/blueprint/assistent" aria-current="page">Assistent</a>', text)
        self.assertNotIn('href="/m/assistent"', text)                  # kein eigener Menüpunkt mehr
        for erwartet in ("0,42 $", "6 Aufrufe", "Tagesgrenze 1,50 $", "17,30 $", "Sonnet 3,20 $", "Trinkt morgens Tee.", "Isst mittags meist warm.", "Kam in fünf Notizen vor.", "/m/entscheid/profil"):
            self.assertIn(erwartet, text)
        self.assertNotIn(GUT, text)
        # Entscheiden: nur mit Sicherheitsmarke; wird genau so an den Assistenten weitergegeben
        self.assertEqual((await self.c.post("/m/entscheid/profil", data={"id": "7", "annehmen": "ja"}, allow_redirects=False)).status, 403)
        self.assertEqual(ENTSCHIEDEN, [])
        for art, kennung, wahl in (("profil", "7", "ja"), ("training", "2026-03-01T17:05", "nein"), ("finanzen", "u55", "ja")):
            r = await self.c.post(f"/m/entscheid/{art}", data={"csrf": self.csrf, "id": kennung, "annehmen": wahl}, allow_redirects=False)
            self.assertEqual(r.status, 303, art)
        self.assertEqual(ENTSCHIEDEN, [("profil", {"id": 7, "annehmen": True}), ("training", {"id": "2026-03-01T17:05", "annehmen": False}),
                                       ("finanzen", {"id": "u55", "annehmen": True})])
        self.assertEqual((await self.c.post("/m/entscheid/loeschen", data={"csrf": self.csrf, "id": "1"})).status, 404)
        self.assertIn("Übernommen.", await (await self.c.get(r.headers["Location"])).text())
        # ohne Anmeldung: nichts davon
        self.c.session.cookie_jar.clear()
        for pfad in ("/blueprint", "/blueprint/dienste", "/blueprint/netz", "/blueprint/assistent", "/blueprint/plan"):
            r = await self.c.get(pfad, allow_redirects=False)
            self.assertEqual((r.status, r.headers["Location"]), (303, "/login"), pfad)
        r = await self.c.post("/m/entscheid/profil", data={"csrf": self.csrf, "id": "7", "annehmen": "ja"}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        self.assertEqual(len(ENTSCHIEDEN), 3)

    async def test_eigener_plan_im_blueprint_und_weitere_eigene_seiten(self):
        ordner = pathlib.Path(self.tmp.name) / "seiten"
        ordner.mkdir()
        (ordner / "blueprint.html").write_text(
            '<html><head><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit"><style>body{color:red}</style></head><body>'
            '<nav class="menue" aria-label="Hauptmenü"><a class="marke" href="/">Altes Menü</a></nav><script>parent.fetch("/api/dienste")</script>'
            '<nav class="nav"><a href="#a">Abschnitt</a></nav><h1>Mein Plan</h1><a href="http://192.0.2.9:8080/">Dienst</a><script src="/live.js" defer></script></body></html>',
            encoding="utf-8")
        (ordner / "notizen.html").write_text("<h1>Notizen</h1>", encoding="utf-8")
        (ordner / "Böse Datei!.html").write_text("x", encoding="utf-8")
        text = await (await self.c.get("/onboarding")).text()
        self.assertIn('<a href="/s/notizen">Notizen</a>', text)        # andere eigene Seiten bleiben eigene Tabs
        self.assertNotIn('href="/s/blueprint"', text)                  # der Plan gehört zum Menüpunkt Blueprint
        self.assertNotIn("Böse", text)
        r = await self.c.get("/blueprint", allow_redirects=False)
        self.assertEqual(r.headers["Location"], "/blueprint/plan")
        for alt in ("/s/blueprint", "/blueprint.html"):
            self.assertIn((await self.c.get(alt, allow_redirects=False)).headers["Location"], ("/blueprint/plan", "/blueprint"), alt)
        seite = await (await self.c.get("/blueprint/plan")).text()
        for erwartet in ('<nav class="menue" aria-label="Hauptmenü"><a class="marke" href="/"><i></i><span>Homie</span></a>', 'href="/blueprint" aria-current="page"',
                         '<a href="/blueprint/plan" aria-current="page">Plan</a>', 'sandbox="allow-popups allow-popups-to-escape-sandbox"'):
            self.assertIn(erwartet, seite)
        marke = seite.split("/blueprint/plan/inhalt?marke=")[1].split('"')[0]
        self.assertEqual((await self.c.get("/blueprint/plan/inhalt")).status, 404)                 # ohne Marke nichts, auch angemeldet
        self.assertEqual((await self.c.get("/blueprint/plan/inhalt?marke=erfunden")).status, 404)
        self.c.session.cookie_jar.clear()                                                          # der Rahmen schickt kein Cookie
        r = await self.c.get(f"/blueprint/plan/inhalt?marke={marke}")
        inhalt = await r.text()
        self.assertEqual(r.status, 200)
        for erwartet in ("Mein Plan", "Abschnitt", 'target="_blank" rel="noopener noreferrer" href="http://192.0.2.9:8080/"', "/static/schrift/outfit-latin.woff2"):
            self.assertIn(erwartet, inhalt)
        for weg in ("Altes Menü", "<script", "googleapis", "live.js"):                              # altes Menü, Skripte und Internet-Verweise sind entfernt
            self.assertNotIn(weg, inhalt)
        regel = r.headers["Content-Security-Policy"]
        self.assertTrue(regel.startswith("sandbox allow-popups"))
        self.assertNotIn("allow-scripts", regel)
        self.assertNotIn("allow-same-origin", regel)
        self.assertNotIn("X-Frame-Options", r.headers)
        self.assertEqual((await self.c.get(f"/api/dienste?marke={marke}")).status, 401)           # die Marke öffnet sonst nichts
        self.assertEqual((await self.c.get(f"/s/notizen?marke={marke}", allow_redirects=False)).status, 303)
        self.assertEqual((await self.c.get("/static/schrift/outfit-latin.woff2")).headers["Access-Control-Allow-Origin"], "*")
        await self.c.post("/login", data={"passwort": PW}, allow_redirects=False)
        r = await self.c.get("/s/notizen")                                                         # weitere eigene Seiten: wie bisher abgeschottet
        self.assertIn("Notizen", await r.text())
        self.assertTrue(r.headers["Content-Security-Policy"].startswith("sandbox allow-scripts"))
        for pfad in ("/s/gibtsnicht", "/s/..%2Fhomie.sqlite", "/s/B%C3%B6se%20Datei!"):
            self.assertEqual((await self.c.get(pfad)).status, 404, pfad)

    async def test_verbinden_ohne_browser(self):
        from homie.__main__ import dienst_verbinden
        db, ablage = self.app[K_DB], self.app[K_ABLAGE]
        ha = f"http://127.0.0.1:{self.server[0].port}"
        ziel = f"http://127.0.0.1:{self.notizdienst}"
        self.assertEqual((await dienst_verbinden(db, ablage, "Notiz-Assistent", ["token"], ["falsch"], ziel))[0], False)   # abgelehnt: nichts gespeichert
        self.assertEqual(ablage.namen(), [])
        self.assertEqual((await dienst_verbinden(db, ablage, "Notiz-Assistent", ["passwort"], [GUT], ziel))[0], False)   # falsches Feld
        self.assertEqual((await dienst_verbinden(db, ablage, "Notiz-Assistent", ["token"], [], ziel))[0], False)          # kein Wert
        self.assertEqual((await dienst_verbinden(db, ablage, "Gibtsnicht", ["token"], [GUT]))[0], False)
        in_ordnung, meldung = await dienst_verbinden(db, ablage, "notiz-assistent", ["token"], [GUT], ziel)
        self.assertTrue(in_ordnung, meldung)
        self.assertNotIn(GUT, meldung)
        in_ordnung, meldung = await dienst_verbinden(db, ablage, "Home Assistant", ["token"], [GUT], ha)
        self.assertTrue(in_ordnung, meldung)
        in_ordnung, _ = await dienst_verbinden(db, ablage, "Home Assistant", ["token"], [GUT], ha)                      # zweimal ist unschädlich
        self.assertTrue(in_ordnung)
        self.assertTrue({"aufnahme", "finanzen", "assistent", "tag", "gesundheit"} <= self.aktiv())
        self.assertEqual(len([d for d in await (await self.c.get("/api/dienste")).json()]), 2)


    async def test_foto_kontoauszug_und_gesehenes_eintragen(self):
        ABGEGEBEN.clear(); EINGETRAGEN.clear()
        kopf = {"X-Homie-CSRF": self.csrf}
        foto = b"\xff\xd8\xff\xe0" + b"0" * 5000
        yt = lambda ausweis, auftrag: self.c.post("/api/yamtrack", json=auftrag, headers={"Authorization": ausweis} if ausweis else {})
        buchen = {"aktion": "verbuchen", "art": "serie", "media_id": "123", "folgen": [[1, 2]]}
        self.assertEqual((await yt(f"Bearer {GUT}", buchen)).status, 401)          # Assistent noch nicht verbunden: niemand darf
        await self.c.post("/dienst/neu", data={"csrf": self.csrf, "adresse": f"127.0.0.1:{self.notizdienst}"}, allow_redirects=False)
        await self.c.post("/dienst/1/verbinden", data={"csrf": self.csrf, "token": GUT}, allow_redirects=False)
        # Foto: geht denselben Weg wie eine Aufnahme; anderes als Ton und Bild wird abgelehnt
        r = await self.c.post("/m/aufnahme/senden", data=foto, headers={**kopf, "Content-Type": "image/jpeg"})
        self.assertEqual((r.status, ABGEGEBEN[-1]), (200, ("image/jpeg", len(foto))))
        self.assertEqual((await self.c.post("/m/aufnahme/senden", data=foto, headers={**kopf, "Content-Type": "image/svg+xml"})).status, 415)
        self.assertEqual((await self.c.post("/m/aufnahme/senden", data=foto, headers={**kopf, "Content-Type": "application/pdf"})).status, 415)
        # Kontoauszug: wird durchgereicht, Homie nennt nur Konto und Zahl der Zeilen
        r = await self.c.post("/m/finanzen/import", data=b"Buchung;Valuta;Betrag\n" + b"x" * 200, headers=kopf)
        self.assertEqual((r.status, await r.json()), (200, {"ok": True, "konto": "Girokonto", "zeilen": 12, "neu": 3}))
        r = await self.c.post("/m/finanzen/import", data=b"irgendwas anderes, kein Auszug", headers=kopf)
        self.assertEqual(r.status, 502)
        self.assertIn("Format", (await r.json())["fehler"])
        self.assertEqual((await self.c.post("/m/finanzen/import", data=b"x" * 5_000_001, headers=kopf)).status, 413)
        self.assertEqual((await self.c.post("/m/finanzen/import", data=b"Buchung;" + b"x" * 200)).status, 403)       # ohne Sicherheitsmarke
        for seite, erwartet in (("/m/aufnahme", ('data-waehlen="foto"', 'data-waehlen="datei"', "/static/hochladen.js")), ("/m/finanzen", ('data-waehlen="datei"', "Beleg fotografieren"))):
            text = await (await self.c.get(seite)).text()
            for e in erwartet:
                self.assertIn(e, text)
        # Gesehenes eintragen: nur der Assistent mit seinem Schlüssel, ohne Anmeldung bei Homie; nur die zwei bekannten Aufträge
        self.c.session.cookie_jar.clear()
        self.assertEqual((await yt("", buchen)).status, 401)
        self.assertEqual((await yt("Bearer falsch", buchen)).status, 401)
        self.assertEqual(EINGETRAGEN, [])
        r = await yt(f"Bearer {GUT}", {**buchen, "unbekannt": "wird verworfen"})
        self.assertEqual((r.status, await r.json()), (200, {"ok": True, "verbucht": ["S01E02"], "titel": "Beispielserie"}))
        self.assertEqual(EINGETRAGEN, [{"aktion": "verbuchen", "art": "serie", "media_id": "123", "folgen": [[1, 2]], "nochmal": False}])
        for schlecht in ({"aktion": "loeschen"}, {"aktion": "verbuchen", "art": "serie", "media_id": "1; rm", "folgen": [[1, 1]]},
                         {"aktion": "verbuchen", "art": "serie", "media_id": "5", "folgen": [[1, i] for i in range(1, 14)]}, {"aktion": "kandidaten", "titel": " "}, [1]):
            self.assertFalse((await (await yt(f"Bearer {GUT}", schlecht)).json())["ok"])
        self.assertEqual(len(EINGETRAGEN), 1)
        # der Tag, an dem etwas gesehen wurde, darf mitkommen – aber nur ein echtes Datum, nie in der Zukunft
        await yt(f"Bearer {GUT}", {**buchen, "datum": "2026-03-01"})
        self.assertEqual(EINGETRAGEN[-1]["datum"], "2026-03-01")
        for falsch in ("morgen", "2999-01-01", "2026-3-1", "2026-03-01'); import os"):
            self.assertFalse((await (await yt(f"Bearer {GUT}", {**buchen, "datum": falsch})).json())["ok"])
        self.assertEqual(len(EINGETRAGEN), 2)
        self.assertEqual((await self.c.get("/api/yamtrack", allow_redirects=False)).status, 401)                    # lesen gibt es dort nicht
        self.assertEqual((await self.c.get("/api/tag", headers={"Authorization": f"Bearer {GUT}"})).status, 401)   # der Schlüssel öffnet sonst nichts
        # der Helfer selbst nimmt ebenfalls nur Geprüftes an
        async with aiohttp.ClientSession() as direkt:
            async with direkt.post(f"http://127.0.0.1:{self.helfer.port}/auftrag", json={"aktion": "sonstwas"}) as r:
                self.assertEqual(r.status, 400)

    async def test_briefkasten_fuer_die_gesundheits_app(self):
        GELIEFERT.clear()
        lieferung = json.dumps({"steps": [{"count": 4321}], "umlaut": "ä"}).encode() + b" " * 100_000      # größer als Homies übliche Grenze
        senden = lambda kopf, inhalt=lieferung: self.c.post("/api/health-webhook", data=inhalt, headers={"Content-Type": "application/json", **kopf})
        self.c.session.cookie_jar.clear()                              # das Handy ist bei Homie nicht angemeldet
        self.assertEqual((await senden({})).status, 401)               # ohne Unterschrift nimmt schon Homie nichts an
        self.assertEqual((await senden({"Authorization": "Bearer kurz"})).status, 401)
        self.assertEqual((await senden({"Authorization": HANDY})).status, 503)    # Assistent noch nicht verbunden
        await self.c.post("/login", data={"passwort": PW}, allow_redirects=False)
        marke = (await (await self.c.get("/onboarding")).text()).split('name="csrf" value="')[1].split('"')[0]
        await self.c.post("/dienst/neu", data={"csrf": marke, "adresse": f"127.0.0.1:{self.notizdienst}"}, allow_redirects=False)
        await self.c.post("/dienst/1/verbinden", data={"csrf": marke, "token": GUT}, allow_redirects=False)
        self.c.session.cookie_jar.clear()
        r = await senden({"Authorization": "Bearer " + "x" * 30})      # falsches Geheimnis: wird weitergereicht, der Assistent lehnt ab
        self.assertEqual((r.status, (await r.json())["fehler"]), (401, "Signatur stimmt nicht"))
        self.assertEqual(GELIEFERT, [])
        r = await senden({"Authorization": HANDY})
        self.assertEqual((r.status, await r.json()), (200, {"ok": True, "tage": 1}))
        self.assertEqual(GELIEFERT, [lieferung])                       # unverändert angekommen
        self.assertEqual((await senden({"X-Signature": "sha256=" + "0" * 64})).status, 401)      # Unterschrift in der zweiten Form: weitergereicht, hier falsch
        self.assertEqual((await senden({"Authorization": HANDY}, b"")).status, 400)
        self.assertEqual((await senden({"Authorization": HANDY}, b"x" * 12_000_001)).status, 413)
        # der Briefkasten öffnet sonst nichts: Lesen und andere Wege bleiben gesperrt, das Geheimnis der App ist kein Schlüssel für Homie
        self.assertEqual((await self.c.get("/api/health-webhook", allow_redirects=False)).status, 401)
        self.assertEqual((await self.c.get("/api/tag", headers={"Authorization": HANDY})).status, 401)
        for _ in range(30):
            await senden({"Authorization": HANDY}, b"{}")
        self.assertEqual((await senden({"Authorization": HANDY}, b"{}")).status, 429)             # Bremse gegen Überfluten


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
        self.assertEqual((await self.c.get("/api/dokumente")).status, 404)
        r = await self.c.post(f"/dienst/{d['id']}/verbinden", data={"csrf": self.csrf, "token": GUT}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        for pfad in ("/api/dokumente", "/m/dokumente/pdf/2"):
            self.assertEqual((await self.c.get(pfad)).status, 200, pfad)
        r = await self.c.get("/m/dokumente")
        text = await r.text()
        self.assertEqual(r.status, 200)
        for erwartet in ("/static/dokumente.js", "/static/dokumente.css", 'id="rolle"', 'id="lineal"', 'id="leser"', 'href="/m/dokumente" aria-current="page"'):
            self.assertIn(erwartet, text)
        self.assertNotIn(GUT, text)
        for datei in ("dokumente.js", "dokumente.css"):
            r = await self.c.get(f"/static/{datei}")
            self.assertEqual(r.status, 200)
            self.assertNotIn("http", (await r.text()).replace("https-", ""))    # nichts von außen, keine Bibliothek aus dem Netz
        # die Liste aller Dokumente: Namen aufgelöst, Arbeitsmarke ausgeblendet, Posteingang erkannt
        d = await (await self.c.get("/api/dokumente")).json()
        self.assertEqual((d["anzahl"], d["archiv"]), (3, f"http://127.0.0.1:{self.paperless}"))
        self.assertEqual(d["dokumente"][0], {"id": 1, "titel": "Beleg 1", "datum": "2026-03-01", "neu": "2026-03-10", "von": "Stadtwerke", "art": "Rechnung",
                                             "tags": ["Wohnung"], "seiten": 2, "eingang": True})
        self.assertNotIn(GUT, json.dumps(d))
        # Volltextsuche mit Auszug (ohne HTML aus dem Archiv)
        t = await (await self.c.get("/api/dokumente/suche?q=beleg+2")).json()
        self.assertEqual(t, {"anzahl": 1, "treffer": [{"id": 2, "auszug": "Zahlbar bis beleg 2 ohne Abzug"}]})
        self.assertEqual((await (await self.c.get("/api/dokumente/suche?q=x")).json())["treffer"], [])
        # Vorschaubild, PDF im Leser (nur in Homies eigenem Rahmen) und Herunterladen mit bereinigtem Namen
        r = await self.c.get("/m/dokumente/vorschau/2")
        self.assertEqual((r.status, r.content_type), (200, "image/webp"))
        r = await self.c.get("/m/dokumente/pdf/2")
        self.assertEqual((r.status, r.content_type, len(await r.read())), (200, "application/pdf", 200_009))
        self.assertTrue(r.headers["Content-Disposition"].startswith("inline"))
        self.assertEqual((r.headers["Content-Security-Policy"], r.headers["X-Frame-Options"]), ("frame-ancestors 'self'", "SAMEORIGIN"))
        r = await self.c.get("/m/dokumente/pdf/2?laden=1")
        self.assertEqual(r.headers["Content-Disposition"], "attachment; filename*=UTF-8''Beleg%20Nr.%202%20(Kopie).pdf")
        self.assertEqual((await self.c.get("/m/dokumente/pdf/abc")).status, 404)
        # ohne Anmeldung: nichts davon
        self.c.session.cookie_jar.clear()
        for pfad in ("/m/dokumente", "/m/dokumente/vorschau/2", "/m/dokumente/pdf/2"):
            self.assertEqual((await self.c.get(pfad, allow_redirects=False)).status, 303, pfad)
        for pfad in ("/api/dokumente", "/api/dokumente/suche?q=beleg"):
            self.assertEqual((await self.c.get(pfad)).status, 401, pfad)


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
