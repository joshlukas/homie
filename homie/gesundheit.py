"""Modul „Gesundheit“: Werte, die das Handy über die Home-Assistant-App meldet (Schritte, Puls, Schlaf …).

Erkannt werden die üblichen Sensoren der Home-Assistant-App am Namensende, egal wie das Gerät heißt.
Es wird nur gelesen und nichts gespeichert; der Verlauf kommt aus Home Assistant selbst.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import aiohttp

from .tag import zone


@dataclass(frozen=True)
class Wert:
    endung: str               # Ende des Sensornamens
    titel: str
    einheit: str
    faktor: float = 1.0       # Umrechnung des gemeldeten Werts
    stellen: int = 0
    taeglich: bool = False    # Tageszähler: bekommt einen Wochenverlauf


WERTE: tuple[Wert, ...] = (
    Wert("daily_steps", "Schritte", "", taeglich=True),
    Wert("daily_distance", "Strecke", "km", 0.001, 1, taeglich=True),
    Wert("active_calories_burned", "Aktive Kalorien", "kcal", taeglich=True),
    Wert("daily_floors", "Stockwerke", "", taeglich=True),
    Wert("sleep_duration", "Schlaf", "Std.", 1 / 60, 1),
    Wert("resting_heart_rate", "Ruhepuls", "bpm"),
    Wert("heart_rate", "Puls", "bpm"),
    Wert("heart_rate_variability", "Herzfrequenz-Variabilität", "ms"),
    Wert("oxygen_saturation", "Sauerstoffsättigung", "%"),
    Wert("weight", "Gewicht", "kg", 1, 1),
    Wert("body_fat", "Körperfett", "%", 1, 1),
    Wert("systolic_blood_pressure", "Blutdruck oben", "mmHg"),
    Wert("diastolic_blood_pressure", "Blutdruck unten", "mmHg"),
    Wert("vo2_max", "VO₂max", "", 1, 1),
)
KURZ = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


class GesundheitFehler(Exception):
    """Meldung, die dem Nutzer gezeigt werden kann."""


def _zahl(wert) -> float | None:
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def deutsch(wert: float, stellen: int) -> str:
    text = f"{wert:,.{stellen}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def _stand(zeit: str, jetzt: dt.datetime) -> str:
    try:
        t = dt.datetime.fromisoformat(zeit).astimezone(jetzt.tzinfo)
    except (ValueError, TypeError):
        return ""
    if t.date() == jetzt.date():
        return f"heute {t.strftime('%H:%M')}"
    if t.date() == jetzt.date() - dt.timedelta(days=1):
        return f"gestern {t.strftime('%H:%M')}"
    return f"{t.day}.{t.month}."


async def uebersicht(basis: str, token: str, tage: int = 7, jetzt: dt.datetime | None = None) -> dict:
    basis, tz = basis.rstrip("/"), zone()
    jetzt = jetzt or dt.datetime.now(tz)
    kopf = {"Authorization": f"Bearer {token}"}
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=15), headers=kopf) as s:
            async with s.get(basis + "/api/states", allow_redirects=False) as r:
                if r.status in (401, 403):
                    raise GesundheitFehler("Home Assistant lehnt den Schlüssel ab. Bitte im Onboarding trennen und neu verbinden.")
                if r.status != 200:
                    raise GesundheitFehler(f"Home Assistant antwortet mit Fehler {r.status}.")
                zustaende = await r.json()

            # Je Wert der zuletzt aktualisierte Sensor mit einer Zahl (falls mehrere Geräte melden).
            gefunden: dict[str, dict] = {}
            for z in zustaende:
                kennung = z.get("entity_id", "")
                if not kennung.startswith("sensor."):
                    continue
                for w in WERTE:
                    if kennung.endswith("_" + w.endung) and _zahl(z.get("state")) is not None:
                        alt = gefunden.get(w.endung)
                        if alt is None or z.get("last_updated", "") > alt.get("last_updated", ""):
                            gefunden[w.endung] = z
                        break

            verlauf_roh = []
            taeglich = [w for w in WERTE if w.taeglich and w.endung in gefunden]
            if taeglich:
                start = (jetzt - dt.timedelta(days=tage - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
                frage = urlencode({"filter_entity_id": ",".join(gefunden[w.endung]["entity_id"] for w in taeglich),
                                   "end_time": jetzt.isoformat()}) + "&minimal_response&no_attributes"
                async with s.get(f"{basis}/api/history/period/{quote(start.isoformat())}?{frage}", allow_redirects=False) as r:
                    verlauf_roh = await r.json() if r.status == 200 else []
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as e:
        raise GesundheitFehler("Home Assistant ist gerade nicht erreichbar.") from e

    werte = [{
        "titel": w.titel, "einheit": w.einheit, "wert": deutsch(_zahl(gefunden[w.endung]["state"]) * w.faktor, w.stellen),
        "stand": _stand(gefunden[w.endung].get("last_updated", ""), jetzt),
    } for w in WERTE if w.endung in gefunden]

    verlauf = []
    for w in [w for w in WERTE if w.taeglich and w.endung in gefunden]:
        kennung = gefunden[w.endung]["entity_id"]
        reihe = next((r for r in verlauf_roh if r and r[0].get("entity_id") == kennung), [])
        je_tag: dict[dt.date, float] = {}
        for punkt in reihe:
            zahl = _zahl(punkt.get("state"))
            try:
                tag = dt.datetime.fromisoformat(punkt.get("last_changed", "")).astimezone(tz).date()
            except (ValueError, TypeError):
                continue
            if zahl is not None:
                je_tag[tag] = max(je_tag.get(tag, 0.0), zahl * w.faktor)   # Tageszähler: der höchste Stand des Tages zählt
        liste = [(jetzt.date() - dt.timedelta(days=tage - 1 - i)) for i in range(tage)]
        hoch = max(je_tag.values(), default=0.0)
        mit = [je_tag[t] for t in liste if t in je_tag]
        verlauf.append({
            "titel": w.titel, "einheit": w.einheit,
            "schnitt": deutsch(sum(mit) / len(mit), w.stellen) if mit else "–",
            "tage": [{"name": KURZ[t.weekday()], "heute": t == jetzt.date(),
                      "wert": deutsch(je_tag[t], w.stellen) if t in je_tag else "–",
                      "anteil": int(100 * je_tag[t] / hoch) if t in je_tag and hoch else 0} for t in liste],
        })
    return {"werte": werte, "verlauf": verlauf, "tage": tage}
