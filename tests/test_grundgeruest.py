"""Prüft das Grundgerüst: Einrichtung, Anmeldung, Sperre ohne Anmeldung, Modul-Register, Ablage.

Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import secrets
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from homie import module
from homie.ablage import Ablage, AblageFehler
from homie.anmeldung import COOKIE, passwort_hashen, passwort_pruefen
from homie.config import laden
from homie.db import Datenbank
from homie.server import K_ABLAGE, K_DB, app_bauen

PW = secrets.token_urlsafe(18)  # jedes Mal neu, steht nirgends


class Web(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.einst = laden({"HOMIE_DATA": self.tmp.name, "HOMIE_DOCKER_LESEN": "0"})
        self.app = app_bauen(self.einst)
        self.c = TestClient(TestServer(self.app))
        await self.c.start_server()

    async def asyncTearDown(self):
        await self.c.close()
        self.tmp.cleanup()

    async def einrichten(self):
        r = await self.c.post("/einrichten", data={"passwort": PW, "wiederholung": PW}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        return r

    async def test_erster_aufruf_fuehrt_zur_einrichtung(self):
        for pfad in ("/", "/onboarding", "/m/tag", "/gibtsnicht", "/login"):
            r = await self.c.get(pfad, allow_redirects=False)
            self.assertEqual((r.status, r.headers["Location"]), (303, "/einrichten"), pfad)
        r = await self.c.get("/einrichten")
        self.assertEqual(r.status, 200)
        self.assertIn("Passwort anlegen", await r.text())

    async def test_ohne_anmeldung_keine_seite_und_keine_api(self):
        await self.einrichten()
        self.c.session.cookie_jar.clear()
        for pfad in ("/", "/onboarding", "/onboarding?beispiel=1", "/m/tag", "/gibtsnicht", "/einrichten", "/aufnahme", "/blueprint"):
            r = await self.c.get(pfad, allow_redirects=False)
            self.assertEqual((r.status, r.headers["Location"]), (303, "/login"), pfad)
        for pfad in ("/api/zustand", "/api/module", "/api/dienste", "/api/gibtsnicht"):
            r = await self.c.get(pfad, allow_redirects=False)
            self.assertEqual(r.status, 401, pfad)
            self.assertEqual(await r.json(), {"fehler": "nicht angemeldet"})
        r = await self.c.post("/logout", allow_redirects=False)
        self.assertEqual(r.status, 303)
        r = await self.c.get("/api/zustand", cookies={COOKIE: "erfunden"})
        self.assertEqual(r.status, 401)

    async def test_einrichtung_nur_einmal_und_passwortregeln(self):
        r = await self.c.post("/einrichten", data={"passwort": "kurz", "wiederholung": "kurz"})
        self.assertEqual(r.status, 400)
        r = await self.c.post("/einrichten", data={"passwort": PW, "wiederholung": PW + "x"})
        self.assertEqual(r.status, 400)
        await self.einrichten()
        self.c.session.cookie_jar.clear()
        r = await self.c.post("/einrichten", data={"passwort": PW + "2", "wiederholung": PW + "2"}, allow_redirects=False)
        self.assertEqual(r.headers["Location"], "/login")
        r = await self.c.post("/login", data={"passwort": PW + "2"})
        self.assertEqual(r.status, 401)

    async def test_anmelden_onboarding_abmelden(self):
        r = await self.einrichten()
        keks = r.cookies[COOKIE]
        self.assertTrue(keks["httponly"])
        self.assertEqual(keks["samesite"], "Lax")
        r = await self.c.get("/onboarding")
        text = await r.text()
        self.assertEqual(r.status, 200)
        self.assertIn("Noch nichts gefunden", text)
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        # Menü: nur Onboarding, kein Modul ohne erfüllten Bedarf
        self.assertIn('href="/onboarding" aria-current="page"', text)
        self.assertNotIn('href="/m/', text)
        self.assertEqual((await self.c.get("/m/tag")).status, 404)
        self.assertIn("Beispielansicht", await (await self.c.get("/onboarding?beispiel=1")).text())
        z = await (await self.c.get("/api/zustand")).json()
        self.assertEqual(z["module_aktiv"], ["blueprint", "onboarding"])
        self.assertEqual(z["erkundung"], {"docker": "aus"})
        # ein Menüband für alle Seiten: gleiche Vorlage, gleiches Aussehen, zuletzt geladen
        self.assertIn('<nav class="menue" aria-label="Hauptmenü"><a class="marke" href="/"><i></i><span>Homie</span></a>', text)
        self.assertLess(text.index("/static/homie.css"), text.index("/static/menue.css"))
        self.assertEqual((await self.c.get("/static/menue.css")).status, 200)
        self.assertNotIn(".menue", await (await self.c.get("/static/homie.css")).text())
        # Schriften liefert Homie selbst aus – keine Anfrage ins Internet
        self.assertIn('href="/static/schrift/schrift.css"', text)
        r = await self.c.get("/static/schrift/schrift.css")
        regeln = await r.text()
        self.assertEqual((r.status, regeln.count("@font-face"), "http" in regeln), (200, 4, False))
        for datei in ("outfit-latin.woff2", "plus-jakarta-sans-latin.woff2"):
            r = await self.c.get(f"/static/schrift/{datei}")
            self.assertEqual((r.status, (await r.read())[:4]), (200, b"wOF2"))
        # frühere Adressen (Lesezeichen, App-Symbol) führen zur heutigen Seite – auch sie nur mit Anmeldung
        for alt, neu in (("/aufnahme", "/m/aufnahme"), ("/dokumente/", "/m/dokumente"), ("/blueprint.html", "/blueprint"), ("/mein-tag", "/m/tag")):
            r = await self.c.get(alt, allow_redirects=False)
            self.assertEqual((r.status, r.headers["Location"]), (303, neu), alt)
        # Abmelden ohne Sicherheitsmarke wird abgelehnt, mit Marke klappt es
        self.assertEqual((await self.c.post("/logout", allow_redirects=False)).status, 403)
        marke = text.split('name="csrf" value="')[1].split('"')[0]
        r = await self.c.post("/logout", data={"csrf": marke}, allow_redirects=False)
        self.assertEqual((r.status, r.headers["Location"]), (303, "/login"))
        self.assertEqual((await self.c.get("/api/zustand")).status, 401)
        # Neu anmelden
        self.assertEqual((await self.c.post("/login", data={"passwort": "f" * 13})).status, 401)
        r = await self.c.post("/login", data={"passwort": PW}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        self.assertEqual((await self.c.get("/api/module")).status, 200)

    async def test_fremde_seite_darf_nichts_abschicken(self):
        r = await self.c.post("/einrichten", data={"passwort": PW, "wiederholung": PW}, headers={"Origin": "http://boese.example"})
        self.assertEqual(r.status, 403)

    async def test_bremse_nach_fehlversuchen(self):
        await self.einrichten()
        self.c.session.cookie_jar.clear()
        for _ in range(5):
            self.assertEqual((await self.c.post("/login", data={"passwort": "x" * 12})).status, 401)
        self.assertEqual((await self.c.post("/login", data={"passwort": PW})).status, 429)

    async def test_modul_erscheint_erst_mit_dienst_und_schluessel(self):
        await self.einrichten()
        db, ablage = self.app[K_DB], self.app[K_ABLAGE]
        db.ausfuehren("INSERT INTO dienst (art, name, zustand, gefunden) VALUES ('dokumente','Archiv','gefunden',0)")
        aktiv = lambda: {s.modul.id for s in module.stand(db, ablage) if s.aktiv}
        self.assertEqual(aktiv(), {"blueprint", "onboarding", "netzplan"})       # Netzplan braucht nur einen gefundenen Dienst
        db.ausfuehren("UPDATE dienst SET zustand='verbunden'")
        self.assertNotIn("dokumente", aktiv())                       # verbunden, aber Schlüssel fehlt
        ablage.setzen(module.schluesselname(1, "token"), "geheim-123")
        self.assertIn("dokumente", aktiv())
        text = await (await self.c.get("/onboarding")).text()
        self.assertIn('href="/m/dokumente"', text)
        self.assertEqual((await self.c.get("/m/dokumente")).status, 200)     # freigeschaltet; das Gerüst der Seite
        r = await self.c.get("/api/dokumente")                                # … aber hier gibt es kein echtes Archiv
        self.assertEqual(r.status, 502)
        self.assertIn("nicht erreichbar", (await r.json())["fehler"])
        self.assertNotIn("geheim-123", await (await self.c.get("/api/dienste")).text())



class BildDesTages(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bilder = Path(self.tmp.name) / "bilder"
        self.bilder.mkdir()
        self.einst = laden({"HOMIE_DATA": str(Path(self.tmp.name) / "daten"), "HOMIE_DOCKER_LESEN": "0", "HOMIE_BILDER": str(self.bilder)})
        self.c = TestClient(TestServer(app_bauen(self.einst)))
        await self.c.start_server()

    async def asyncTearDown(self):
        await self.c.close()
        self.tmp.cleanup()

    async def test_bild_nur_angemeldet_und_nur_bilder(self):
        self.assertEqual((await self.c.get("/api/bild-des-tages", allow_redirects=False)).status, 401)
        r = await self.c.post("/einrichten", data={"passwort": PW, "wiederholung": PW}, allow_redirects=False)
        self.assertEqual(r.status, 303)
        # leerer Ordner: kein Bild, die Seite bekommt eine leere Marke
        self.assertEqual((await self.c.get("/api/bild-des-tages")).status, 404)
        self.assertEqual((await (await self.c.get("/api/tag?tage=1")).json())["bild"], "")
        # was kein Bild ist oder versteckt liegt, zählt nicht
        (self.bilder / "seite.html").write_text("<script>1</script>")
        (self.bilder / "zeichnung.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
        (self.bilder / ".versteckt.jpg").write_bytes(b"x")
        (self.bilder / "leer.png").write_bytes(b"")
        self.assertEqual((await self.c.get("/api/bild-des-tages")).status, 404)
        (self.bilder / "urlaub").mkdir()
        (self.bilder / "urlaub" / "Strand.JPG").write_bytes(b"\xff\xd8\xff\xe0bild")
        r = await self.c.get("/api/bild-des-tages")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Content-Type"], "image/jpeg")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(await r.read(), b"\xff\xd8\xff\xe0bild")
        self.assertRegex((await (await self.c.get("/api/tag?tage=1")).json())["bild"], "^[0-9a-f]{16}$")

    def test_jeden_tag_ein_anderes_bis_alle_dran_waren(self):
        import datetime as dt
        from homie import bildtag
        for i in range(7):
            (self.bilder / f"b{i}.png").write_bytes(b"p")
        start = dt.date(2026, 11, 24)
        start -= dt.timedelta(days=start.toordinal() % 7)          # Beginn einer Runde
        runde = [bildtag.heute(self.bilder, start + dt.timedelta(days=i)).name for i in range(7)]
        self.assertEqual(len(set(runde)), 7)
        self.assertEqual(bildtag.heute(self.bilder, start).name, runde[0])   # am selben Tag immer dasselbe
        self.assertIsNone(bildtag.heute(self.bilder / "gibtsnicht", start))


class Bausteine(unittest.TestCase):
    def test_passwort_hash(self):
        h = passwort_hashen(PW)
        self.assertTrue(h.startswith("scrypt$"))
        self.assertNotIn(PW, h)
        self.assertTrue(passwort_pruefen(PW, h))
        self.assertFalse(passwort_pruefen(PW + "x", h))
        self.assertNotEqual(h, passwort_hashen(PW))

    def test_ablage_verschluesselt(self):
        with tempfile.TemporaryDirectory() as t:
            daten = Path(t)
            db = Datenbank(daten / "homie.sqlite")
            a = Ablage(db, daten)
            a.setzen("dienst:1:token", "streng-geheim-äöü")
            self.assertEqual(a.lesen("dienst:1:token"), "streng-geheim-äöü")
            self.assertEqual(a.namen(), ["dienst:1:token"])
            self.assertEqual((daten / "hauptschluessel.key").stat().st_mode & 0o777, 0o600)
            db.ausfuehren("PRAGMA wal_checkpoint(TRUNCATE)")
            for datei in daten.iterdir():
                self.assertNotIn(b"streng-geheim", datei.read_bytes(), datei.name)
            # anderer Hauptschlüssel → lässt sich nicht öffnen
            with self.assertRaises(AblageFehler):
                Ablage(db, daten, von_aussen="anderer").lesen("dienst:1:token")
            # Eintrag unter anderem Namen unterschieben → fällt auf
            db.ausfuehren("UPDATE ablage SET name='dienst:2:token'")
            with self.assertRaises(AblageFehler):
                a.lesen("dienst:2:token")
            a.loeschen("dienst:2:token")
            self.assertFalse(a.hat("dienst:2:token"))
            db.schliessen()


if __name__ == "__main__":
    unittest.main()
