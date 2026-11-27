"""Sonderfälle, die früher zu Fehlern führten (Durchsicht vom 27.11.2026).

Aufruf im Projektordner:  python -m unittest discover -s tests -v
"""
import asyncio
import datetime as dt
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from homie import assistent, config, server, yamtrack
from homie.tag import zone


class YamtrackDatum(unittest.TestCase):
    def test_heute_gilt_nach_der_uhr_der_installation(self):
        # Kurz nach Mitternacht in Berlin ist es in UTC noch gestern; der heutige Tag darf trotzdem nicht „Zukunft“ sein.
        heute = dt.datetime.now(zone()).date().isoformat()
        auftrag, fehler = yamtrack.pruefen({"aktion": "verbuchen", "art": "film", "media_id": "603", "datum": heute})
        self.assertEqual(fehler, "")
        self.assertEqual(auftrag["datum"], heute)
        morgen = (dt.datetime.now(zone()).date() + dt.timedelta(days=1)).isoformat()
        self.assertIsNone(yamtrack.pruefen({"aktion": "verbuchen", "art": "film", "media_id": "603", "datum": morgen})[0])
        # Eine Installation weit östlich: dort ist oft schon „morgen“, während die Uhr des Containers noch heute zeigt.
        osten = dt.timezone(dt.timedelta(hours=14))
        with mock.patch.object(yamtrack, "zone", return_value=osten):
            dort = dt.datetime.now(osten).date().isoformat()
            self.assertEqual(yamtrack.pruefen({"aktion": "verbuchen", "art": "film", "media_id": "603", "datum": dort})[1], "")

    def test_kennung_nur_aus_ziffern_0_bis_9(self):
        for falsch in ("²", "12a", "", "1" * 13):
            self.assertIsNone(yamtrack.pruefen({"aktion": "verbuchen", "art": "film", "media_id": falsch})[0], falsch)


class ProxyAdresse(unittest.TestCase):
    def anfrage(self, fern, xff, proxy=""):
        einst = SimpleNamespace(proxys=config._proxys(proxy))
        return SimpleNamespace(remote=fern, headers={"X-Forwarded-For": xff} if xff else {}, app={server.K_EINST: einst})

    def test_ohne_proxy_wird_der_kopfzeile_nicht_geglaubt(self):
        self.assertEqual(server._adresse(self.anfrage("192.0.2.7", "198.51.100.1")), "192.0.2.7")

    def test_vom_proxy_zaehlt_der_letzte_eintrag(self):
        r = self.anfrage("192.0.2.7", "203.0.113.9, 198.51.100.1", proxy="192.0.2.0/24")
        self.assertEqual(server._adresse(r), "198.51.100.1")

    def test_fremde_quelle_und_unsinn_bleiben_bei_der_eigenen_adresse(self):
        self.assertEqual(server._adresse(self.anfrage("198.51.100.5", "203.0.113.9", proxy="192.0.2.0/24")), "198.51.100.5")
        self.assertEqual(server._adresse(self.anfrage("192.0.2.7", "kein-ip", proxy="192.0.2.0/24")), "192.0.2.7")
        self.assertEqual(config._proxys("falsch, 192.0.2.1"), config._proxys("192.0.2.1"))


class AssistentAntworten(unittest.TestCase):
    def test_finanzen_mit_leeren_monatswerten(self):
        roh = {"bilanz": {"2026-10": {"ein": None, "aus": -812, "netto": None}, "2026-11": {"ein": 2400, "aus": None}, "kaputt": None},
               "abos": [{"wer": "Dienst", "je_monat": None}], "budget": {}}
        with mock.patch.object(assistent, "_holen", mock.AsyncMock(return_value=roh)), \
                mock.patch.object(assistent, "geteilt", mock.AsyncMock(return_value=None)):
            daten = asyncio.run(assistent.finanzen("http://x", "t"))
        self.assertEqual([m["name"] for m in daten["monate"]], ["Okt", "Nov"])
        self.assertEqual(daten["monate"][0]["anteil_aus"], 33)
        self.assertEqual(daten["abos"][0]["betrag"], "–")

    def test_antwort_ohne_objekt(self):
        self.assertEqual(assistent._objekt(None), {})
        self.assertEqual(assistent._objekt([1, 2]), {})
        self.assertEqual(assistent._objekt({"ok": True}), {"ok": True})


class Netzplan(unittest.TestCase):
    def test_sortierung_uebersteht_ungewoehnliche_adressen(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = server.app_bauen(config.laden({"HOMIE_DATA": tmp, "HOMIE_DOCKER_LESEN": "0"}))
            for ip in ("192.0.2.10", "192.0.2.2", "2001:db8::1", "unbekannt"):
                app[server.K_DB].ausfuehren("INSERT INTO geraet (ip, gesehen) VALUES (?, 0)", (ip,))
            self.assertEqual([g["ip"] for g in server._netzplan(app)["geraete"]], ["192.0.2.2", "192.0.2.10", "2001:db8::1", "unbekannt"])
            app[server.K_DB].schliessen()


if __name__ == "__main__":
    unittest.main()
