#!/usr/bin/env python3
"""Homie zum Ansehen – mit erfundenen Daten, ohne eigene Dienste.

    python scripts/demo.py            →  http://127.0.0.1:8095   (Passwort: homie-demo-homie)

Startet Homie in einem leeren, vorübergehenden Datenordner und daneben drei nachgestellte Dienste (Notiz-Assistent,
Home Assistant, Paperless-ngx), die erfundene Daten liefern. Alles lauscht nur auf diesem Rechner. Aus dieser Demo
stammen die Bilder in der README. Nichts davon ist echt: Namen, Beträge, Dokumente und Geräte sind ausgedacht.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import pathlib
import random
import sqlite3
import sys
import tempfile
import time

from aiohttp import web

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from homie import module, server  # noqa: E402
from homie.config import laden  # noqa: E402

KENNWORT = "homie-demo-homie"     # nur für diese Demo, die nur auf dem eigenen Rechner lauscht
PORT = 8095
Z = random.Random(7)
HEUTE = dt.date.today()
JETZT = dt.datetime.now().astimezone()
tag = lambda n: (HEUTE - dt.timedelta(days=n)).isoformat()                      # vor n Tagen
zeit = lambda n, h, m=0: f"{tag(n)}T{h:02d}:{m:02d}+01:00"


def _bilder(ordner: pathlib.Path) -> pathlib.Path:
    """Drei gezeichnete Landschaften für das „Bild des Tages“ – errechnet, nicht fotografiert."""
    import math
    import struct
    import zlib
    ordner.mkdir(parents=True, exist_ok=True)
    b, h = 640, 400
    for nr, (oben, unten, berg) in enumerate((((255, 170, 120), (120, 70, 160), (40, 30, 80)), ((120, 190, 255), (230, 240, 255), (40, 90, 80)),
                                              ((30, 30, 80), (200, 90, 150), (15, 15, 40)))):
        zeilen = bytearray()
        for y in range(h):
            zeilen.append(0)
            for x in range(b):
                kamm = h * 0.62 + 46 * math.sin(x / 71 + nr) + 22 * math.sin(x / 23 + nr * 2) + 10 * math.sin(x / 9)
                sonne = math.hypot(x - b * (0.3 + 0.2 * nr), y - h * 0.38) < 34
                t = y / h
                farbe = berg if y > kamm else (255, 240, 200) if sonne else tuple(int(o + (u - o) * t) for o, u in zip(oben, unten))
                zeilen += bytes(farbe)
        teil = lambda art, inhalt: struct.pack(">I", len(inhalt)) + art + inhalt + struct.pack(">I", zlib.crc32(art + inhalt))
        (ordner / f"landschaft-{nr + 1}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + teil(b"IHDR", struct.pack(">IIBBBBB", b, h, 8, 2, 0, 0, 0))
                                                       + teil(b"IDAT", zlib.compress(bytes(zeilen), 9)) + teil(b"IEND", b""))
    return ordner


# ---------- Notiz-Assistent ----------
def _eintraege():
    roh = [
        (0, 7, 40, "essen", "Beim Bäcker zwei Brötchen und einen Kaffee geholt.", {"titel": "Bäcker", "betrag_eur": 4.3, "cospend": "eingetragen: Bäcker 4,30 €, Lebensmittel"}),
        (0, 12, 15, "aufgabe", "Winterreifen-Termin in der Werkstatt ausmachen", {"faellig": tag(-4)}),
        (0, 12, 15, "erinnerung", "Geschenk für Mias Geburtstag besorgen", {"titel": ""}),
        (0, 18, 5, "sport", "45 Minuten auf dem Crosstrainer", {"titel": "Crosstrainer", "dauer_min": 45, "training_tag": tag(0)}),
        (1, 20, 30, "medien", "Zwei Folgen von „Nordlicht“ geschaut.", {"titel": "Nordlicht", "yamtrack": "verbucht: Nordlicht S01E05, S01E06"}),
        (1, 13, 10, "einkauf", "Wocheneinkauf im Supermarkt", {"titel": "Supermarkt", "betrag_eur": 62.4, "cospend": "eingetragen: Supermarkt 62,40 €, Lebensmittel"}),
        (1, 8, 0, "befinden", "Gut geschlafen, etwas Muskelkater in den Beinen.", {"titel": ""}),
        (2, 19, 0, "ueberlegung", "Den Balkon im Frühjahr mit Hochbeet statt Kübeln planen.", {"titel": ""}),
        (2, 9, 30, "notiz", "Die Heizung im Bad braucht nach dem Entlüften etwa zehn Minuten.", {"titel": ""}),
        (3, 21, 0, "fuer_claude", "Vergleiche drei leise NAS-Festplatten mit 8 TB.", {"grund": "Recherche", "status": "beantwortet", "modell": "Sonnet",
                                   "antwort": "Drei passende Modelle mit Lautstärke und Preis stehen in der Tagesnotiz; am leisesten ist die mit 5400 Umdrehungen."}),
        (3, 12, 40, "essen", "Mittag beim Italiener, Pasta und Wasser.", {"titel": "Trattoria", "betrag_eur": 14.5, "cospend": "eingetragen: Trattoria 14,50 €, Restaurant"}),
        (4, 17, 20, "sport", "Eine Stunde Schwimmen", {"titel": "Schwimmen", "dauer_min": 60, "training_tag": tag(4)}),
        (5, 10, 0, "frage", "Wie lange hält sich gekochter Reis im Kühlschrank?", {"antwort": "Etwa ein bis zwei Tage, luftdicht verschlossen."}),
    ]
    aus, n = [], 0
    for vor, h, m, typ, text, daten in roh:
        n += 1
        aus.append({"id": n, "zeit": zeit(vor, h, m), "tag": tag(vor), "aufnahme": f"Aufnahme_{tag(vor)}_{h:02d}-{m:02d}.webm", "typ": typ, "text": text, "daten": daten})
    for vor, h, m, text, sek, foto in ((0, 18, 5, "Training und der Plan fürs Wochenende.", 41, False), (0, 12, 15, "Werkstatt anrufen, Geschenk für Mia.", 23, False),
                                      (1, 13, 12, "Kassenbon vom Supermarkt, 62,40 €, mit Karte bezahlt.", 0, True), (1, 20, 30, "Zwei Folgen Nordlicht geschaut.", 9, False)):
        n += 1
        wortlaut = ("Das ist ein Kassenbon. Geschäft: Supermarkt am Ring. Gesamtbetrag 62,40 Euro, Zahlart Karte. Posten: Obst, Gemüse, Käse, Brot, Spülmittel."
                    if foto else text + " Das war es auch schon.")
        aus.append({"id": n, "zeit": zeit(vor, h, m), "tag": tag(vor), "aufnahme": f"{'Foto' if foto else 'Aufnahme'}_{tag(vor)}_{h:02d}-{m:02d}", "typ": "aufnahme", "text": text,
                    "daten": {"wortlaut": wortlaut, "sekunden": sek, "privat": False, "modell": "lokales Modell", **({"foto": True} if foto else {})}})
    return aus


async def nd_eintraege(request):
    spanne = int(request.query.get("tage", 7))
    return web.json_response({"seit": tag(spanne - 1), "eintraege": [e for e in _eintraege() if e["tag"] >= tag(spanne - 1)], "kategorien": {
        "erinnerung": "Erinnerungen", "ueberlegung": "Überlegungen", "notiz": "Notizen", "essen": "Essen und Trinken", "einkauf": "Einkäufe und Ausgaben",
        "sport": "Sport und Bewegung", "medien": "Gesehen, gelesen, gehört", "befinden": "Befinden"}})


def _monat(n):  # Kennung des Monats vor n Monaten
    j, m = HEUTE.year, HEUTE.month - n
    while m < 1:
        j, m = j - 1, m + 12
    return f"{j}-{m:02d}"


async def nd_finanzen(request):
    tage = (dt.date(HEUTE.year + HEUTE.month // 12, HEUTE.month % 12 + 1, 1) - dt.timedelta(days=1)).day
    ueblich = [round(1450 * (i + 1) / tage + 40 * (i % 5 == 0), 2) for i in range(tage)]
    ist, summe = [], 0.0
    for i in range(HEUTE.day):
        summe += Z.choice((0, 8, 14, 22, 35, 61, 18, 0, 95))
        ist.append(round(summe, 2))
    einnahmen, fix, aus = 3120.0, 1385.0, ist[-1]
    raum = einnahmen - fix
    prog = round(aus + (ueblich[-1] - ueblich[HEUTE.day - 1]), 2)
    return web.json_response({
        "konten": [{"name": "Girokonto", "bank": "Beispielbank", "art": "giro", "saldo": 2841.37, "stand": tag(1)},
                   {"name": "Kreditkarte", "bank": "Kartenbank", "art": "karte", "saldo": -412.80, "stand": tag(1)},
                   {"name": "Tagesgeld", "bank": "Beispielbank", "art": "sparen", "saldo": 9200.00, "stand": tag(1)}],
        "seit": tag(300), "monat": _monat(0), "monate": {_monat(n): {"ein": 3120, "aus": -2700 - 90 * n} for n in range(5, -1, -1)},
        "budget": {"einnahmen": einnahmen, "fix": fix, "spielraum": raum, "ausgegeben": aus, "frei": round(raum - aus, 2), "je_tag": round((raum - aus) / max(1, tage - HEUTE.day), 2),
                   "rest_tage": tage - HEUTE.day, "ampel": "gruen", "karte_geschaetzt": None, "sonder": 180.0, "sonder_liste": [{"wer": "Steuererstattung", "betrag": 180.0}],
                   "grundlage": ["Gehalt", "Miete", "Strom", "Versicherungen"]},
        "regel": [{"wer": "Gehalt", "betrag": 3120.0}, {"wer": "Miete", "betrag": -890.0}, {"wer": "Stadtwerke", "betrag": -95.0}],
        "karte": {"vorhanden": True, "monat": 412.8, "ueblich": 520.0, "kategorien": [
            {"name": "Lebensmittel", "monat": 186.4, "schnitt": 210.0, "kaeufe_je_monat": 11}, {"name": "Essen gehen", "monat": 92.5, "schnitt": 70.0, "kaeufe_je_monat": 4},
            {"name": "Tanken", "monat": 58.0, "schnitt": 95.0, "kaeufe_je_monat": 2}, {"name": "Abos", "monat": 31.9, "schnitt": 31.9, "kaeufe_je_monat": 3},
            {"name": "Drogerie", "monat": 24.0, "schnitt": 38.0, "kaeufe_je_monat": 2}, {"name": "Online-Einkauf", "monat": 20.0, "schnitt": 75.0, "kaeufe_je_monat": 2}]},
        "tipps": [{"name": "Essen gehen", "schnitt": 70.0, "kaeufe": 4, "anteil": 25, "ersparnis": 18}, {"name": "Online-Einkauf", "schnitt": 75.0, "kaeufe": 2, "anteil": 20, "ersparnis": 15}],
        "abos": [{"wer": "Musikdienst", "je_monat": 10.99}, {"wer": "Filmdienst", "je_monat": 13.99}, {"wer": "Cloud-Speicher", "je_monat": 6.92}],
        "verlauf": {"ist": ist, "ueblich": ueblich, "tage": tage, "heute": HEUTE.day},
        "prognose": {"ausgaben": prog, "frei": round(raum - prog, 2), "ueblich_gesamt": ueblich[-1], "offen_fix": 185.0, "offen_ein": 0.0, "giro_ende": 2210.0, "posten": [
            {"wer": "Miete", "betrag": -890.0, "gebucht": 1, "offen": 0, "tag": 1}, {"wer": "Stadtwerke", "betrag": -95.0, "gebucht": 1, "offen": 0, "tag": 5},
            {"wer": "Haftpflicht und Hausrat", "betrag": -42.0, "gebucht": 0, "offen": -42.0, "tag": 27}, {"wer": "Mobilfunk und Internet", "betrag": -58.0, "gebucht": 0, "offen": -58.0, "tag": 28},
            {"wer": "Sparplan", "betrag": -85.0, "gebucht": 0, "offen": -85.0, "tag": 30}, {"wer": "Gehalt", "betrag": 3120.0, "gebucht": 1, "offen": 0, "tag": 28}]},
        "bilanz": {_monat(n): {"ein": 3120 + (180 if n == 0 else 0), "aus": -2600 - 70 * (n % 3) - (0 if n else -900), "netto": 3120 - 2600 - 70 * (n % 3) + (1080 if n == 0 else 0)} for n in range(5, -1, -1)},
        "letzte": [{"tag": tag(n), "wer": w, "zweck": "Kartenzahlung" if k == "Kreditkarte" else "Lastschrift", "betrag": b, "konto": k} for n, w, b, k in (
            (1, "Supermarkt am Ring", -62.40, "Kreditkarte"), (1, "Bäckerei Sonnenschein", -4.30, "Kreditkarte"), (2, "Stadtwerke", -95.00, "Girokonto"), (3, "Trattoria Da Mare", -14.50, "Kreditkarte"),
            (4, "Tankstelle Nord", -58.00, "Kreditkarte"), (5, "Steuererstattung", 180.00, "Girokonto"), (6, "Drogerie am Markt", -24.00, "Kreditkarte"), (8, "Musikdienst", -10.99, "Kreditkarte"))],
        "hinweis": None,
        "cospend_offen": {"anzahl": 1, "summe": 24.0, "liste": [{"id": "u1", "tag": tag(6), "wer": "DROGERIE AM MARKT", "betrag": 24.0, "name": "Drogerie"}]}})


async def nd_cospend(request):
    return web.json_response({"projekt": "Haushaltskasse", "seit": tag(6), "saldo": {"Alex": 37.6, "Sam": -37.6},
                              "zeitraum": {"summe": 163.7, "anzahl": 6, "nach_kategorie": {"Lebensmittel": 97.2, "Restaurant": 29.0, "Haushalt": 24.0, "Freizeit": 13.5}},
                              "monat": {"monat": _monat(0), "summe": 486.3},
                              "betrag_fragen": [{"id": 4, "zeit": tag(0) + "T08:10+01:00", "titel": "Nusshörnchen", "gesagt": 22.0, "ueblich": 2.2}], "monate": {_monat(n): 520 + 35 * (n % 4) for n in range(5, -1, -1)},
                              "letzte": [{"tag": tag(n), "was": w, "betrag": b, "zahler": z, "kategorie": k, "sprachnotiz": s} for n, w, b, z, k, s in (
                                  (0, "Bäcker", 4.3, "Alex", "Lebensmittel", True), (1, "Supermarkt", 62.4, "Alex", "Lebensmittel", True), (3, "Trattoria", 14.5, "Alex", "Restaurant", True),
                                  (4, "Kino", 13.5, "Sam", "Freizeit", False), (5, "Wochenmarkt", 30.5, "Sam", "Lebensmittel", False), (6, "Putzmittel", 24.0, "Alex", "Haushalt", False))]})


async def nd_ki(request):
    return web.json_response({"aktiv": True, "tageslimit": 1.0, "heute": {"tag": tag(0), "usd": 0.07, "aufrufe": 3},
                              "tage": [{"tag": tag(n), "usd": round(Z.choice((0, 0.02, 0.05, 0.11, 0.0, 0.07)), 2), "aufrufe": Z.randint(0, 6)} for n in range(13, -1, -1)],
                              "modelle_30_tage": {"Sonnet": {"usd": 0.84, "aufrufe": 31}, "Haiku": {"usd": 0.09, "aufrufe": 12}}, "gesamt": {"usd": 2.41, "aufrufe": 96},
                              "anker": {"guthaben": 20.0, "gesamt": 0.0, "stand": tag(40) + "T10:00"}, "guthaben": 17.59})


async def nd_profil(request):
    return web.json_response({"profil": "## Alltag\nArbeitet meist von zu Hause.\nTrainiert drei Mal pro Woche.\n\n## Essen\nTrinkt morgens Kaffee, isst mittags warm.\n\n## Technik\nBetreibt einen kleinen Heimserver.",
                              "vorschlaege": [{"id": 3, "erstellt": tag(1), "abschnitt": "Essen", "art": "ergaenzen", "alt": "", "neu": "Samstags Einkauf auf dem Wochenmarkt.",
                                               "begruendung": "Du hast es in vier Notizen der letzten Wochen erwähnt."}]})


def _trainings():
    aus, arten = [], ("Crosstrainer", "Schwimmen", "Laufen", "Krafttraining", "Yoga")
    for n in range(0, 300):
        if Z.random() < 0.38:
            t = tag(n)
            aus.append({"id": f"t{n}", "tag": t, "beginn": f"{t}T{Z.choice((7, 12, 17, 18, 19)):02d}:{Z.choice((0, 15, 30)):02d}+01:00", "dauer_min": Z.choice((30, 40, 45, 50, 60)),
                        "art": Z.choice(arten), "titel": "", "distanz_m": None, "quelle": "uhr"})
    return aus


TRAININGS = _trainings()
SCHRITTE = {n: Z.randint(3800, 11500) for n in range(0, 120)}


async def nd_gesundheit(request):
    spanne = int(request.query.get("tage", 7))
    return web.json_response({
        "stand": tag(0), "daten_ab": tag(299), "training_alle": TRAININGS, "training": [t for t in TRAININGS if t["tag"] >= tag(spanne - 1)],
        "tage": [{"tag": tag(n), "schritte": SCHRITTE[n], "distanz_m": SCHRITTE[n] * 0.72, "kalorien_aktiv": 180 + SCHRITTE[n] // 30, "kalorien_gesamt": 2100 + SCHRITTE[n] // 25,
                  "schlaf_min": 390 + (SCHRITTE[n] % 90)} for n in range(spanne - 1, 0, -1)],
        "training_vorschlaege": [{"id": zeit(1, 17, 5)[:16], "tag": tag(1), "von": "17:05", "bis": "17:42", "dauer_min": 37, "schritte": 4300, "tempo": 116}]})


async def nd_annehmen(request):
    await request.read()
    return web.json_response({"ok": True, "name": "Aufnahme_demo", "konto": "Girokonto", "zeilen": 48, "neu": 12})


NOTIZDIENST = [web.get("/api/eintraege", nd_eintraege), web.get("/api/finanzen", nd_finanzen), web.get("/api/cospend", nd_cospend), web.get("/api/claude", nd_ki),
               web.get("/api/profil", nd_profil), web.get("/api/gesundheit", nd_gesundheit), web.post("/api/aufnahme", nd_annehmen), web.post("/api/finanzen/import", nd_annehmen),
               web.post("/api/{art}/entscheid", nd_annehmen)]


# ---------- Home Assistant ----------
SENSOREN = {"daily_steps": (6420, ""), "daily_distance": (4620, "m"), "active_calories_burned": (318, "kcal"), "daily_floors": (9, ""), "sleep_duration": (432, "min"),
            "resting_heart_rate": (58, "bpm"), "heart_rate": (71, "bpm"), "heart_rate_variability": (46, "ms"), "oxygen_saturation": (97, "%"), "weight": (74.2, "kg"), "vo2_max": (44.5, "")}


async def ha_zustaende(request):
    return web.json_response([{"entity_id": f"sensor.handy_{k}", "state": str(w), "last_updated": JETZT.isoformat(), "attributes": {"unit_of_measurement": e}} for k, (w, e) in SENSOREN.items()])


async def ha_verlauf(request):
    aus = []
    for kennung in request.query.get("filter_entity_id", "").split(","):
        k = kennung.removeprefix("sensor.handy_")
        if k not in SENSOREN:
            continue
        f = {"daily_steps": 1, "daily_distance": 0.72, "active_calories_burned": 0.045, "daily_floors": 0.0012}.get(k, 1)
        aus.append([{"entity_id": kennung, "state": str(round((SENSOREN[k][0] if n == 0 else SCHRITTE[n] * f), 1)), "last_changed": f"{tag(n)}T{'%02d' % min(JETZT.hour, 21)}:00:00+01:00"} for n in range(9, -1, -1)])
    return web.json_response(aus)


async def ha_kalender(request):
    return web.json_response([{"entity_id": "calendar.familie", "name": "Familie"}])


async def ha_termine(request):
    t = lambda n, h, m, dauer, titel, ort="": {"summary": titel, "location": ort, "start": {"dateTime": f"{tag(-n)}T{h:02d}:{m:02d}:00+01:00"},
                                             "end": {"dateTime": f"{tag(-n)}T{(h + dauer):02d}:{m:02d}:00+01:00"}}
    return web.json_response([t(0, 19, 0, 2, "Kochabend mit Sam"), t(1, 8, 30, 1, "Zahnarzt", "Praxis am Markt"), t(3, 18, 0, 3, "Mias Geburtstag", "Gartenlokal"),
                              {"summary": "Wochenendausflug", "start": {"date": tag(-6)}, "end": {"date": tag(-8)}}])


async def ha_start(request):
    return web.Response(text="<html><head><title>Home Assistant</title></head></html>", content_type="text/html")


HOMEASSISTANT = [web.get("/", ha_start), web.get("/api/", lambda r: web.json_response({"message": "API running."})), web.get("/api/states", ha_zustaende),
                 web.get("/api/history/period/{ab}", ha_verlauf), web.get("/api/calendars", ha_kalender), web.get("/api/calendars/{k}", ha_termine)]


# ---------- Paperless-ngx ----------
ABSENDER = ["Stadtwerke", "Krankenkasse", "Finanzamt", "Hausverwaltung", "Versicherung", "Arbeitgeber", "Werkstatt", "Zahnarztpraxis"]
ARTEN = ["Rechnung", "Bescheid", "Vertrag", "Brief", "Abrechnung"]
MARKEN = ["Wohnung", "Steuer", "Auto", "Gesundheit", "Posteingang"]
TITEL = ["Jahresabrechnung Strom", "Beitragsanpassung", "Einkommensteuerbescheid", "Nebenkostenabrechnung", "Versicherungsschein Hausrat", "Gehaltsabrechnung", "Rechnung Inspektion",
         "Heil- und Kostenplan", "Abschlagsplan Gas", "Bonusprogramm", "Vorauszahlungsbescheid", "Protokoll Eigentümerversammlung", "Beitragsrechnung Haftpflicht", "Arbeitszeugnis",
         "Rechnung Reifenwechsel", "Rechnung Zahnreinigung"]
DOKUMENTE = []
for nr in range(1, 61):
    a = Z.randrange(len(ABSENDER))
    alt = int(nr ** 1.75) + Z.randint(0, 6)
    DOKUMENTE.append({"id": 100 + nr, "title": TITEL[(a * 2 + nr % 2) % len(TITEL)] + (f" {HEUTE.year - alt // 365}" if nr % 3 == 0 else ""), "created": tag(alt) + "T00:00:00+01:00", "added": tag(max(0, alt - 2)) + "T09:00:00+01:00",
                      "correspondent": a + 1, "document_type": Z.randrange(len(ARTEN)) + 1, "tags": sorted({(a % 4) + 1} | ({5} if nr <= 2 else set())), "page_count": Z.choice((1, 1, 2, 3, 6))})
DOKUMENTE.sort(key=lambda d: d["created"], reverse=True)


async def pl_liste(request):
    q = request.query.get("query", "").lower()
    treffer = [d for d in DOKUMENTE if q in d["title"].lower()] if q else DOKUMENTE
    if q:
        treffer = [{"id": d["id"], "__search_hit__": {"highlights": f"… Ihre {d['title']} – zahlbar bis zum Monatsende ohne Abzug …"}} for d in treffer]
    seite, groesse = int(request.query.get("page", 1)), int(request.query.get("page_size", 250))
    stueck = treffer[(seite - 1) * groesse: seite * groesse]
    return web.json_response({"count": len(treffer), "results": stueck, "next": "weiter" if seite * groesse < len(treffer) else None})


def _namen(liste, eingang=""):
    async def f(request):
        return web.json_response({"results": [{"id": i + 1, "name": n, "is_inbox_tag": n == eingang} for i, n in enumerate(liste)], "next": None})
    return f


async def pl_bild(request):
    """Vorschaubild als gezeichnete Seite: Briefkopf, Betreff, Zeilen – erkennbar erfunden."""
    d = next((d for d in DOKUMENTE if d["id"] == int(request.match_info["nr"])), DOKUMENTE[0])
    z = random.Random(d["id"])
    farbe = ("#6d5efc", "#ff5fa2", "#2fd4c4", "#f5a524", "#4aa3ff")[d["correspondent"] % 5]
    zeilen = "".join(f'<rect x="60" y="{300 + i * 26}" width="{z.randint(260, 480)}" height="9" rx="4" fill="#c9cbd6"/>' for i in range(z.randint(9, 17)) if i % 6 != 5)
    tabelle = "".join(f'<rect x="60" y="{720 + i * 30}" width="330" height="9" rx="4" fill="#d9dbe4"/><rect x="450" y="{720 + i * 30}" width="{z.randint(50, 90)}" height="9" rx="4" fill="#b9bccb"/>' for i in range(3))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 848"><rect width="600" height="848" fill="#fbfbfd"/><rect x="60" y="56" width="74" height="74" rx="14" fill="{farbe}"/>'
           f'<text x="152" y="88" font-family="sans-serif" font-size="24" font-weight="700" fill="#22243a">{ABSENDER[d["correspondent"] - 1]}</text>'
           f'<text x="152" y="116" font-family="sans-serif" font-size="14" fill="#7a7d92">Musterstraße 1 · 12345 Musterstadt</text>'
           f'<rect x="60" y="176" width="190" height="8" rx="4" fill="#d9dbe4"/><rect x="60" y="196" width="150" height="8" rx="4" fill="#d9dbe4"/>'
           f'<text x="60" y="262" font-family="sans-serif" font-size="21" font-weight="700" fill="#22243a">{d["title"]}</text>{zeilen}{tabelle}'
           f'<rect x="60" y="800" width="480" height="2" fill="#e3e5ee"/></svg>')
    return web.Response(text=svg, content_type="image/svg+xml")


def _pdf(titel: str) -> bytes:
    inhalt = f"BT /F1 20 Tf 72 760 Td ({titel.encode('latin-1', 'replace').decode('latin-1')}) Tj 0 -32 Td /F1 12 Tf (Erfundenes Beispieldokument der Homie-Demo.) Tj ET".encode("latin-1")
    teile = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
             b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
             b"<< /Length %d >>\nstream\n" % len(inhalt) + inhalt + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    aus, stellen = b"%PDF-1.4\n", []
    for i, t in enumerate(teile):
        stellen.append(len(aus))
        aus += b"%d 0 obj\n" % (i + 1) + t + b"\nendobj\n"
    x = len(aus)
    aus += b"xref\n0 %d\n0000000000 65535 f \n" % (len(teile) + 1) + b"".join(b"%010d 00000 n \n" % s for s in stellen)
    return aus + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(teile) + 1, x)


async def pl_pdf(request):
    d = next((d for d in DOKUMENTE if d["id"] == int(request.match_info["nr"])), DOKUMENTE[0])
    return web.Response(body=_pdf(d["title"]), content_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="dokument-{d["id"]}.pdf"'})


PAPERLESS = [web.get("/", lambda r: web.Response(text="<title>Paperless-ngx sign in</title>", content_type="text/html")), web.get("/api/documents/", pl_liste),
             web.get("/api/statistics/", lambda r: web.json_response({"documents_total": len(DOKUMENTE), "documents_inbox": 2})),
             web.get("/api/correspondents/", _namen(ABSENDER)), web.get("/api/document_types/", _namen(ARTEN)), web.get("/api/tags/", _namen(MARKEN, "Posteingang")),
             web.get("/api/documents/{nr}/thumb/", pl_bild), web.get("/api/documents/{nr}/preview/", pl_pdf), web.get("/api/documents/{nr}/download/", pl_pdf)]

WEITERE = {"Jellyfin": ("medien", "jellyfin", "<title>Jellyfin</title>"), "Pi-hole": ("netz", "pihole", "<title>Pi-hole</title>"), "Ollama": ("ki-lokal", "ollama", "Ollama is running")}

PLAN = """<!doctype html><html lang="de"><meta charset="utf-8"><title>Mein Heimnetz</title><style>
body{margin:0;padding:34px 40px;background:#12142b;color:#e9eaf6;font:16px/1.55 system-ui,sans-serif}h1{font-size:30px;margin:0 0 6px}p{color:#a9acc8;margin:0 0 26px}
.reihe{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:18px}.k{flex:1 1 210px;background:#1c1f42;border:1px solid #33376a;border-radius:16px;padding:16px 18px}
.k b{display:block;font-size:17px}.k small{color:#a9acc8}.k i{display:inline-block;width:10px;height:10px;border-radius:50%;background:#3ddc97;margin-right:8px}
h2{font-size:14px;letter-spacing:.12em;text-transform:uppercase;color:#8f93ff;margin:26px 0 12px}</style>
<h1>Mein Heimnetz</h1><p>Eine eigene, handgeschriebene Seite: Sie liegt als Datei im Datenordner und erscheint hier als „Plan“.</p>
<h2>Eingang</h2><div class="reihe"><div class="k"><b><i></i>Router</b><small>Glasfaser, WLAN für Gäste getrennt</small></div><div class="k"><b><i></i>Switch im Flur</b><small>acht Anschlüsse, zwei frei</small></div></div>
<h2>Server</h2><div class="reihe"><div class="k"><b><i></i>Mini-PC „keller“</b><small>Docker: Homie, Dokumentenarchiv, Medien</small></div><div class="k"><b><i></i>Rechner „ki“</b><small>Grafikkarte, lokale Sprachmodelle</small></div><div class="k"><b><i></i>NAS</b><small>Datensicherung jede Nacht</small></div></div>
<h2>Geplant</h2><div class="reihe"><div class="k"><b>Zweite Sicherung außer Haus</b><small>verschlüsselt, einmal pro Woche</small></div><div class="k"><b>Wetterstation</b><small>Werte in Home Assistant</small></div></div></html>"""


async def _starten(wege, port=0):
    app = web.Application()
    app.add_routes(wege)
    r = web.AppRunner(app, access_log=None)
    await r.setup()
    s = web.TCPSite(r, "127.0.0.1", port)
    await s.start()
    return s._server.sockets[0].getsockname()[1]


def _yamtrack(pfad: pathlib.Path):
    con = sqlite3.connect(pfad)
    con.executescript("""create table app_item (id integer primary key, title text, media_type text, image text, season_number integer, episode_number integer);
        create table app_tv (id integer primary key, item_id integer, status text); create table app_episode (id integer primary key, item_id integer, end_date text);
        create table app_movie (id integer primary key, item_id integer, end_date text, score real);""")
    n = 0
    for i, t in enumerate(("Nordlicht", "Die Werft", "Kanal 7")):
        n += 1
        con.execute("insert into app_item values (?,?,?,?,?,?)", (n, t, "tv", "", None, None))
        con.execute("insert into app_tv values (?,?,?)", (i + 1, n, "In progress"))
    for i, (t, s, f, vor) in enumerate((("Nordlicht", 1, 6, 1), ("Nordlicht", 1, 5, 1), ("Die Werft", 2, 3, 3), ("Kanal 7", 1, 9, 5), ("Die Werft", 2, 2, 6))):
        n += 1
        con.execute("insert into app_item values (?,?,?,?,?,?)", (n, t, "episode", "", s, f))
        con.execute("insert into app_episode values (?,?,?)", (i + 1, n, f"{tag(vor)} 19:{30 + i}:00"))
    for i, (t, vor) in enumerate((("Der lange Sommer", 4), ("Zwei Brücken", 12))):
        n += 1
        con.execute("insert into app_item values (?,?,?,?,?,?)", (n, t, "movie", "", None, None))
        con.execute("insert into app_movie values (?,?,?,?)", (i + 1, n, f"{tag(vor)} 20:15:00", 8))
    con.commit()
    con.close()


async def main():
    daten = pathlib.Path(tempfile.mkdtemp(prefix="homie-demo-"))
    (daten / "seiten").mkdir()
    (daten / "seiten" / "blueprint.html").write_text(PLAN, encoding="utf-8")
    _yamtrack(daten / "yamtrack.sqlite3")
    nd, ha, pl = await _starten(NOTIZDIENST), await _starten(HOMEASSISTANT), await _starten(PAPERLESS)
    app = server.app_bauen(laden({"HOMIE_DATA": str(daten), "HOMIE_DOCKER_LESEN": "0", "HOMIE_BIND": "127.0.0.1", "HOMIE_PORT": str(PORT), "HOMIE_YAMTRACK_DB": str(daten / "yamtrack.sqlite3"), "HOMIE_BILDER": str(_bilder(daten / "bilder"))}),
                           erkundung_ziele=[])
    db, ablage = app[server.K_DB], app[server.K_ABLAGE]
    app[server.K_ANM].konto_anlegen(KENNWORT)
    db.ausfuehren("INSERT INTO merk (name, wert) VALUES ('ich', 'Alex')")
    for art, name, kennung, port in (("assistent", "Notiz-Assistent", "notizdienst", nd), ("homeassistant", "Home Assistant", "homeassistant", ha), ("dokumente", "Paperless-ngx", "paperless", pl)):
        c = db.ausfuehren("INSERT INTO dienst (art,name,adresse,zustand,gefunden,details) VALUES (?,?,?,'verbunden',?,?)",
                          (art, name, f"http://127.0.0.1:{port}", int(time.time()), json.dumps({"kennung": kennung, "quelle": "erkundung"})))
        ablage.setzen(module.schluesselname(c.lastrowid, "token"), "demo-kein-echter-schluessel")
    for name, (art, kennung, seite) in WEITERE.items():
        port = await _starten([web.get("/", (lambda s: lambda r: web.Response(text=s, content_type="text/html"))(seite))])
        db.ausfuehren("INSERT INTO dienst (art,name,adresse,zustand,gefunden,details) VALUES (?,?,?,'gefunden',?,?)",
                      (art, name, f"http://127.0.0.1:{port}", int(time.time()), json.dumps({"kennung": kennung, "quelle": "erkundung"})))
    for ip, name, ports in (("192.0.2.1", "router", [80, 443]), ("192.0.2.10", "keller", [8090, 8096, 9000]), ("192.0.2.11", "ki", [11434]), ("192.0.2.20", "nas", [443, 5000]),
                            ("192.0.2.31", "drucker", [80, 631]), ("192.0.2.40", "fernseher", [])):
        db.ausfuehren("INSERT INTO geraet (ip,name,mac,ports,sonstiges,gesehen) VALUES (?,?,'',?,'[]',?)", (ip, name, json.dumps(ports), int(time.time())))
    r = web.AppRunner(app, access_log=None)
    await r.setup()
    await web.TCPSite(r, "127.0.0.1", PORT).start()
    print(f"Homie-Demo läuft: http://127.0.0.1:{PORT}   Passwort: {KENNWORT}   (Strg+C beendet; Datenordner {daten})", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
