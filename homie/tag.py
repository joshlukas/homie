"""Modul „Mein Tag“: Termine, Aufgaben und Wetter aus Home Assistant.

Home Assistant kennt die Kalender (egal ob CalDAV, Google oder lokal), die Aufgabenlisten und das Wetter –
ein Schlüssel genügt für alles. Es wird nur gelesen und nichts gespeichert; jede Ansicht fragt neu.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import aiohttp

WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
WETTER = {
    "clear-night": "klare Nacht", "cloudy": "bewölkt", "fog": "Nebel", "hail": "Hagel", "lightning": "Gewitter",
    "lightning-rainy": "Gewitter mit Regen", "partlycloudy": "teils bewölkt", "pouring": "starker Regen", "rainy": "Regen",
    "snowy": "Schnee", "snowy-rainy": "Schneeregen", "sunny": "sonnig", "windy": "windig", "windy-variant": "windig",
    "exceptional": "Unwetter",
}


class TagFehler(Exception):
    """Meldung, die dem Nutzer gezeigt werden kann."""


def zone() -> dt.tzinfo:
    try:
        return ZoneInfo(os.environ.get("TZ") or "Europe/Berlin")
    except Exception:
        return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc


def _zeit(wert: dict, tz: dt.tzinfo) -> tuple[dt.datetime | None, bool]:
    """(Zeitpunkt, ganztägig?) aus {"dateTime": …} oder {"date": …}."""
    try:
        if wert.get("dateTime"):
            return dt.datetime.fromisoformat(wert["dateTime"]).astimezone(tz), False
        if wert.get("date"):
            return dt.datetime.fromisoformat(wert["date"]).replace(tzinfo=tz), True
    except (ValueError, TypeError):
        pass
    return None, False


def _tagesname(tag: dt.date, heute: dt.date) -> str:
    if tag == heute:
        return "Heute"
    if tag == heute + dt.timedelta(days=1):
        return "Morgen"
    return f"{WOCHENTAGE[tag.weekday()]}, {tag.day}.{tag.month}."


async def uebersicht(basis: str, token: str, tage: int = 7, jetzt: dt.datetime | None = None) -> dict:
    basis, tz = basis.rstrip("/"), zone()
    jetzt = jetzt or dt.datetime.now(tz)
    start = jetzt.replace(hour=0, minute=0, second=0, microsecond=0)
    ende = start + dt.timedelta(days=tage)
    kopf = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=12), headers=kopf) as s:
        async def holen(pfad: str, pflicht: bool = True, sende: dict | None = None):
            try:
                anfrage = s.post(basis + pfad, json=sende, allow_redirects=False) if sende is not None else s.get(basis + pfad, allow_redirects=False)
                async with anfrage as r:
                    if r.status in (401, 403):
                        raise TagFehler("Home Assistant lehnt den Schlüssel ab. Bitte im Onboarding trennen und neu verbinden.")
                    if r.status != 200:
                        if pflicht:
                            raise TagFehler(f"Home Assistant antwortet mit Fehler {r.status}.")
                        return None
                    return await r.json()
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as e:
                if pflicht:
                    raise TagFehler("Home Assistant ist gerade nicht erreichbar.") from e
                return None

        zustaende, kalender = await asyncio.gather(holen("/api/states"), holen("/api/calendars", pflicht=False))
        spanne = urlencode({"start": start.isoformat(), "end": ende.isoformat()})
        listen = [z for z in zustaende if z["entity_id"].startswith("todo.")]
        termine_roh, aufgaben_roh = await asyncio.gather(
            asyncio.gather(*(holen(f"/api/calendars/{quote(k['entity_id'])}?{spanne}", pflicht=False) for k in kalender or [])),
            # Aufgaben gibt Home Assistant nur über diesen einen Dienstaufruf heraus; er liest, er ändert nichts.
            asyncio.gather(*(holen("/api/services/todo/get_items?return_response", pflicht=False,
                                   sende={"entity_id": z["entity_id"], "status": "needs_action"}) for z in listen)),
        )

    heute = jetzt.date()
    je_tag: dict[dt.date, list[dict]] = {}
    for k, liste in zip(kalender or [], termine_roh):
        for t in liste or []:
            beginn, ganztags = _zeit(t.get("start", {}), tz)
            schluss, _ = _zeit(t.get("end", {}), tz)
            if beginn is None:
                continue
            tag = max(beginn.date(), heute)      # läuft ein Termin schon, zählt er zu heute
            je_tag.setdefault(tag, []).append({
                "titel": t.get("summary") or "(ohne Titel)", "ort": t.get("location") or "", "kalender": k.get("name", ""),
                "ganztags": ganztags, "sortierung": beginn.isoformat(),
                "zeit": "ganztägig" if ganztags else beginn.strftime("%H:%M") + (f"–{schluss.strftime('%H:%M')}" if schluss and schluss.date() == beginn.date() else ""),
                "vorbei": bool(schluss and schluss < jetzt and not ganztags),
            })
    tage_liste = [{"name": _tagesname(tag, heute), "heute": tag == heute,
                   "termine": sorted(je_tag[tag], key=lambda t: (not t["ganztags"], t["sortierung"]))}
                  for tag in sorted(je_tag) if heute <= tag < ende.date()]

    aufgaben = []
    for z, antwort in zip(listen, aufgaben_roh):
        punkte = ((antwort or {}).get("service_response") or {}).get(z["entity_id"], {}).get("items", [])
        aufgaben.append({
            "name": z.get("attributes", {}).get("friendly_name", z["entity_id"]),
            "offen": int(z["state"]) if str(z.get("state", "")).isdigit() else len(punkte),
            "punkte": [{"titel": p.get("summary", ""), "faellig": _faellig(p.get("due"), heute)} for p in punkte[:12]],
        })

    wetter = None
    w = next((z for z in zustaende if z["entity_id"].startswith("weather.")), None)
    if w and w.get("state") not in (None, "unavailable", "unknown"):
        a = w.get("attributes", {})
        wetter = {"lage": WETTER.get(w["state"], w["state"]), "grad": a.get("temperature"), "einheit": a.get("temperature_unit", "°C"),
                  "feuchte": a.get("humidity")}

    stunde = jetzt.hour
    return {
        "gruss": "Guten Morgen" if 5 <= stunde < 11 else "Guten Tag" if stunde < 18 else "Guten Abend" if stunde < 23 else "Gute Nacht",
        "datum": f"{WOCHENTAGE[jetzt.weekday()]}, {jetzt.day}.{jetzt.month}.{jetzt.year}",
        "tage": tage_liste, "heute_anzahl": sum(len(t["termine"]) for t in tage_liste if t["heute"]),
        "kalender": [k.get("name", "") for k in kalender or []], "spanne": tage,
        "aufgaben": aufgaben, "aufgaben_offen": sum(a["offen"] for a in aufgaben), "wetter": wetter,
    }


def _faellig(wert: str | None, heute: dt.date) -> str:
    try:
        tag = dt.date.fromisoformat((wert or "")[:10])
    except ValueError:
        return ""
    if tag < heute:
        return "überfällig"
    return _tagesname(tag, heute).lower() if tag <= heute + dt.timedelta(days=1) else f"bis {tag.day}.{tag.month}."
