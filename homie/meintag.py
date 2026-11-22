"""„Mein Tag“: trägt für die große Tagesseite alles in einer Antwort zusammen.

Quellen sind die verbundenen Dienste: der Notiz-Assistent (Einträge, Gesundheitsverlauf, Finanzen, geteilte
Ausgaben, KI-Kosten, Profil), Home Assistant (heutige Werte vom Handy, Kalender) und – falls seine Datenbank
eingehängt ist – Yamtrack (Gesehenes). Fällt eine Quelle aus, bleibt ihr Teil leer und die Seite nennt den Grund.
Es wird nur gelesen; die Antwort wird 20 Sekunden lang wiederverwendet, damit die Seite die Dienste nicht belastet.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sqlite3
import time
from urllib.parse import quote, urlencode

import aiohttp

from .tag import zone

# Werte der Home-Assistant-App (Health Connect): Name auf der Seite → Ende des Sensornamens
JETZT = {"schritte": "daily_steps", "distanz_m": "daily_distance", "kalorien_aktiv": "active_calories_burned", "puls": "heart_rate",
         "ruhepuls": "resting_heart_rate", "sauerstoff": "oxygen_saturation", "vo2max": "vo2_max", "hrv": "heart_rate_variability"}
TAGESZAEHLER = ("schritte", "distanz_m", "kalorien_aktiv")
_merker: dict[tuple, tuple[float, dict]] = {}


def _zahl(wert) -> float | None:
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


class _Quelle:
    def __init__(self, zugang, kopf):
        self.basis = zugang[0].rstrip("/") if zugang else ""
        self.kopf = kopf
        self.da = bool(zugang)

    async def holen(self, s: aiohttp.ClientSession, pfad: str, warten: float = 12):
        async with s.get(self.basis + pfad, headers=self.kopf, allow_redirects=False, timeout=aiohttp.ClientTimeout(total=warten)) as r:
            if r.status == 404:
                return None
            if r.status != 200:
                raise RuntimeError(f"Fehler {r.status}")
            return await r.json()


async def _gesundheit(s, helfer: _Quelle, ha: _Quelle, tage: int, tz) -> dict | None:
    spanne = max(2, min(tage, 400))
    start = dt.datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=spanne - 1)
    je_tag, training, stand, alle, daten_ab, vorschlaege = {}, [], None, [], None, []
    if helfer.da:
        daten = await helfer.holen(s, f"/api/gesundheit?tage={spanne}") or {}
        je_tag = {t["tag"]: {k: v for k, v in t.items() if k != "tag"} for t in daten.get("tage", [])}
        training, stand = daten.get("training", []), daten.get("stand")
        alle, daten_ab, vorschlaege = daten.get("training_alle", []), daten.get("daten_ab"), daten.get("training_vorschlaege", [])
    aktuell = {}
    if ha.da:
        sensoren: dict[str, dict] = {}
        for z in await ha.holen(s, "/api/states", 15) or []:
            kennung = z.get("entity_id", "")
            if not kennung.startswith("sensor."):
                continue
            # längste Endung zuerst: „…_resting_heart_rate“ ist der Ruhepuls, nicht der Puls
            for name, endung in sorted(JETZT.items(), key=lambda x: -len(x[1])):
                if kennung.endswith("_" + endung):
                    if name not in sensoren or z.get("last_updated", "") > sensoren[name].get("last_updated", ""):
                        sensoren[name] = z
                    break
        for name, z in sensoren.items():
            wert = _zahl(z.get("state"))
            if wert is not None:
                aktuell[name] = {"wert": wert, "einheit": z.get("attributes", {}).get("unit_of_measurement", ""), "stand": z.get("last_updated", "")}
        zaehler = {name: sensoren[name]["entity_id"] for name in TAGESZAEHLER if name in sensoren}
        if zaehler:
            # Home Assistant kennt nur die letzten Tage; dort zählt der höhere Stand (der Verlauf des Assistenten kann älter sein).
            ab = max(start, dt.datetime.now(tz) - dt.timedelta(days=10))
            frage = urlencode({"filter_entity_id": ",".join(zaehler.values()), "end_time": dt.datetime.now(tz).isoformat()}) + "&minimal_response&no_attributes"
            for reihe in await ha.holen(s, f"/api/history/period/{quote(ab.isoformat())}?{frage}", 20) or []:
                name = next((n for n, k in zaehler.items() if reihe and reihe[0].get("entity_id") == k), None)
                for punkt in reihe if name else []:
                    wert = _zahl(punkt.get("state"))
                    try:
                        tag = dt.datetime.fromisoformat(punkt["last_changed"]).astimezone(tz).strftime("%Y-%m-%d")
                    except (KeyError, ValueError, TypeError):
                        continue
                    if wert is not None:
                        je_tag.setdefault(tag, {})[name] = max(je_tag.get(tag, {}).get(name, 0), wert)
    if not je_tag and not aktuell:
        return None
    reihe = [(start + dt.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(spanne)]
    return {"aktuell": aktuell, "tage": [{"tag": t, **je_tag.get(t, {})} for t in reihe], "training": training, "export_stand": stand,
            "training_alle": alle, "daten_ab": daten_ab, "training_vorschlaege": vorschlaege}


async def _kalender(s, ha: _Quelle, tz, voraus: int = 14) -> dict | None:
    if not ha.da:
        return None
    start = dt.datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    spanne = urlencode({"start": start.isoformat(), "end": (start + dt.timedelta(days=voraus)).isoformat()})
    termine, namen = [], []
    for k in await ha.holen(s, "/api/calendars") or []:
        namen.append(k.get("name", k["entity_id"]))
        for t in await ha.holen(s, f"/api/calendars/{quote(k['entity_id'])}?{spanne}") or []:
            a, e = t.get("start", {}), t.get("end", {})
            termine.append({"titel": t.get("summary") or "(ohne Titel)", "ort": t.get("location") or "", "kalender": k.get("name", ""),
                            "ganztags": "date" in a, "beginn": a.get("dateTime") or a.get("date"), "ende": e.get("dateTime") or e.get("date")})
    termine.sort(key=lambda t: t["beginn"] or "")
    return {"kalender": namen, "termine": termine, "tage": voraus}


def _yamtrack(datei: str) -> dict:
    # immutable=1: Die Datenbank ist nur lesbar eingehängt; SQLite soll keine Hilfsdateien anlegen.
    con = sqlite3.connect(f"file:{datei}?mode=ro&immutable=1", uri=True, timeout=3)
    try:
        laufend = [{"titel": t, "art": a, "bild": b} for t, a, b in con.execute(
            "select i.title, i.media_type, i.image from app_tv t join app_item i on i.id = t.item_id where t.status = 'In progress' order by t.id desc")]
        folgen = [{"titel": t, "staffel": s, "folge": f, "zeit": z, "bild": b} for t, s, f, z, b in con.execute(
            "select i.title, i.season_number, i.episode_number, e.end_date, i.image from app_episode e join app_item i on i.id = e.item_id "
            "where e.end_date is not null order by e.end_date desc limit 12")]
        filme = [{"titel": t, "zeit": z, "bild": b, "wertung": w} for t, z, b, w in con.execute(
            "select i.title, m.end_date, i.image, m.score from app_movie m join app_item i on i.id = m.item_id "
            "where m.end_date is not null order by m.end_date desc limit 6")]
        return {"laufend": laufend, "folgen": folgen, "filme": filme}
    finally:
        con.close()


async def schnappschuss(helfer_zugang, ha_zugang, tage: int = 7, ich: str = "", yamtrack_db: str = "") -> dict:
    tage = max(1, min(int(tage), 400))
    marke = (tage, helfer_zugang and helfer_zugang[0], ha_zugang and ha_zugang[0], ich)
    alt = _merker.get(marke)
    if alt and time.time() - alt[0] < 20:
        return alt[1]
    tz = zone()
    helfer = _Quelle(helfer_zugang, {"Authorization": f"Bearer {helfer_zugang[1]['token']}"} if helfer_zugang else {})
    ha = _Quelle(ha_zugang, {"Authorization": f"Bearer {ha_zugang[1]['token']}"} if ha_zugang else {})
    aus = {"tage": tage, "ich": ich, "fehler": [], "eintraege": [], "kategorien": {}, "yamtrack": None, "gesundheit": None, "kalender": None,
           "finanzen": None, "cospend": None, "claude": None, "profil": None}

    async def versuch(feld: str, was: str, aufgabe):
        try:
            aus[feld] = await aufgabe
        except Exception as e:      # eine ausgefallene Quelle darf die Seite nicht mitreißen
            aus["fehler"].append(f"{was}: {type(e).__name__ if not str(e) else str(e)[:120]}")

    async def eintraege():
        daten = await helfer.holen(s, f"/api/eintraege?tage={tage}") or {}
        aus["eintraege"], aus["kategorien"], aus["seit"] = daten.get("eintraege", []), daten.get("kategorien", {}), daten.get("seit")
        return daten.get("eintraege", [])

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False, limit=8)) as s:
        aufgaben = [versuch("gesundheit", "Gesundheitsdaten nicht lesbar", _gesundheit(s, helfer, ha, tage, tz)),
                    versuch("kalender", "Kalender aus Home Assistant nicht lesbar", _kalender(s, ha, tz))]
        if helfer.da:
            aufgaben += [versuch("eintraege", "Notiz-Assistent nicht erreichbar", eintraege()),
                         versuch("finanzen", "Finanzen nicht lesbar", helfer.holen(s, "/api/finanzen", 30)),
                         versuch("cospend", "Geteilte Ausgaben nicht lesbar", helfer.holen(s, f"/api/cospend?tage={tage}", 25)),
                         versuch("claude", "KI-Kosten nicht lesbar", helfer.holen(s, "/api/claude")),
                         versuch("profil", "Profil nicht lesbar", helfer.holen(s, "/api/profil"))]
        else:
            aus["fehler"].append("Der Notiz-Assistent ist nicht verbunden – Notizen, Finanzen und Trainings fehlen.")
        if yamtrack_db and os.path.exists(yamtrack_db):
            aufgaben.append(versuch("yamtrack", "Yamtrack nicht lesbar", asyncio.get_running_loop().run_in_executor(None, _yamtrack, yamtrack_db)))
        await asyncio.gather(*aufgaben)
    _merker[marke] = (time.time(), aus)
    if len(_merker) > 50:
        _merker.clear()
    return aus
