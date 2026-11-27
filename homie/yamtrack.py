"""Gesehenes in Yamtrack eintragen – für Sprachnotizen wie „zwei Folgen von … geschaut“.

Yamtrack hat keine Schnittstelle für „Folge X als gesehen markieren“. Deshalb werden im Yamtrack-Container dessen
eigene Funktionen aufgerufen (dieselben, die ein Jellyfin-Webhook am Ende benutzt). So legt Yamtrack Serie, Staffel
und Folge selbst an. Geprüft mit Yamtrack 0.26.3; ändert ein Update die internen Namen, scheitert der Aufruf mit
einer Meldung und es wird nichts geschrieben.

Dafür braucht es schreibenden Zugriff auf Docker. Den bekommt nicht Homie selbst, sondern ein eigener kleiner
Helfer (`python -m homie yamtrack-helfer`, in der Stackdatei der Dienst „yamtrack-helfer“, von Haus aus aus).
Er lauscht nur auf diesem Rechner, kennt genau zwei Aufträge (Titel suchen, Gesehenes eintragen), prüft sie
streng und führt ausschließlich das feste Programm unten im Container mit dem eingestellten Namen aus.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re

import aiohttp
from aiohttp import web

from .tag import zone

SOCKET = os.environ.get("HOMIE_DOCKER_SOCKET", "/var/run/docker.sock")
CONTAINER = os.environ.get("HOMIE_YAMTRACK_CONTAINER", "yamtrack")
MAX_AUFTRAG = 20_000

# Läuft im Yamtrack-Container. Der Auftrag kommt als JSON in der Umgebungsvariablen YT_AUFTRAG.
IM_CONTAINER = r'''
import difflib, json, os, re
from django.contrib.auth import get_user_model
from app import models
from app.models import MediaTypes, Sources, Status
from app.providers import tmdb
from integrations.webhooks.jellyfin import JellyfinWebhookProcessor

A = json.loads(os.environ["YT_AUFTRAG"])

def gesehen_am():
    """Der Tag, den der Auftrag nennt, als Zeitpunkt (20 Uhr Ortszeit) – oder None: dann gilt der Augenblick des Eintragens."""
    if not A.get("datum"):
        return None
    import datetime
    from django.utils import timezone
    j, m, t = (int(x) for x in A["datum"].split("-"))
    return timezone.make_aware(datetime.datetime(j, m, t, 20, 0))
user = get_user_model().objects.order_by("id").first()
norm = lambda s: re.sub(r"[^a-z0-9äöüß ]", " ", (s or "").lower()).split()

def aehnlich(a, b):
    a, b = " ".join(norm(a)), " ".join(norm(b))
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()

def stand_tv(media_id):
    """Zuletzt gesehene Folge und die nächsten sechs, laut Yamtrack und TMDB."""
    gesehen = sorted({(e.item.season_number, e.item.episode_number) for e in models.Episode.objects.filter(
        related_season__user=user, item__media_id=str(media_id), item__source=Sources.TMDB.value).select_related("item")
        if e.item.season_number})
    letzte = gesehen[-1] if gesehen else None
    naechste = []
    try:
        meta = tmdb.tv(str(media_id))
        staffeln = sorted(s["season_number"] for s in meta.get("related", {}).get("seasons", []) if s.get("season_number"))
        start = letzte[0] if letzte else (staffeln[0] if staffeln else 1)
        for s in [x for x in staffeln if x >= start][:2]:
            sm = tmdb.tv_with_seasons(str(media_id), [s])[f"season/{s}"]
            for ep in sm.get("episodes", []):
                n = ep.get("episode_number")
                if n and (not letzte or (s, n) > letzte) and len(naechste) < 6:
                    naechste.append([s, n])
    except Exception as e:
        naechste = []
    return {"zuletzt": list(letzte) if letzte else None, "naechste": naechste}

def kandidaten():
    titel = A["titel"]
    out, schon = [], set()
    for art, model, mt in (("serie", models.TV, MediaTypes.TV.value), ("film", models.Movie, MediaTypes.MOVIE.value)):
        for m in model.objects.filter(user=user, item__source=Sources.TMDB.value).select_related("item"):
            a = aehnlich(titel, m.item.title)
            if a >= 0.6 and (art, m.item.media_id) not in schon:
                schon.add((art, m.item.media_id))
                out.append({"art": art, "media_id": m.item.media_id, "titel": m.item.title, "in_yamtrack": True,
                            "status": str(m.status), "aehnlichkeit": round(a, 2)})
    for art, mt in (("serie", "tv"), ("film", "movie")):
        try:
            for r in tmdb.search(mt, titel, 1)["results"][:4]:
                if (art, str(r["media_id"])) not in schon:
                    schon.add((art, str(r["media_id"])))
                    out.append({"art": art, "media_id": str(r["media_id"]), "titel": r["title"], "in_yamtrack": False,
                                "status": "", "aehnlichkeit": round(aehnlich(titel, r["title"]), 2)})
        except Exception as e:
            pass
    out.sort(key=lambda k: (-k["in_yamtrack"], -k["aehnlichkeit"]))
    out = out[:8]
    for k in out:
        if k["art"] == "serie" and (k["in_yamtrack"] or k["aehnlichkeit"] >= 0.9):
            k.update(stand_tv(k["media_id"]))
    return {"kandidaten": out}

def verbuchen():
    p = JellyfinWebhookProcessor()
    gespielt = {"Event": "MarkPlayed"}
    mid = str(A["media_id"])
    if A["art"] == "film":
        vorher = models.Movie.objects.filter(user=user, item__media_id=mid, item__source=Sources.TMDB.value).order_by("-created_at").first()
        if vorher and vorher.status == Status.COMPLETED.value and not A.get("nochmal"):
            return {"ok": True, "verbucht": [], "titel": vorher.item.title, "hinweis": "war schon als gesehen eingetragen"}
        p._handle_movie(mid, gespielt, user)
        m = models.Movie.objects.filter(user=user, item__media_id=mid, item__source=Sources.TMDB.value).order_by("-created_at").first()
        if gesehen_am():
            models.Movie.objects.filter(pk=m.pk).update(end_date=gesehen_am())
        return {"ok": True, "verbucht": ["Film"], "titel": m.item.title, "datum": A.get("datum") or ""}
    neu, schon = [], []
    for s, e in A["folgen"][:12]:
        da = models.Episode.objects.filter(related_season__user=user, item__media_id=mid, item__source=Sources.TMDB.value,
                                           item__season_number=s, item__episode_number=e).exists()
        if da and not A.get("nochmal"):
            schon.append(f"S{s:02d}E{e:02d}")
            continue
        p._handle_tv_episode(mid, int(s), int(e), gespielt, user)
        if gesehen_am():
            models.Episode.objects.filter(related_season__user=user, item__media_id=mid, item__source=Sources.TMDB.value,
                                          item__season_number=s, item__episode_number=e).update(end_date=gesehen_am())
        neu.append(f"S{s:02d}E{e:02d}")
    t = models.Item.objects.filter(media_id=mid, source=Sources.TMDB.value, media_type=MediaTypes.TV.value).first()
    return {"ok": True, "verbucht": neu, "schon_da": schon, "titel": t.title if t else "", "datum": A.get("datum") or ""}

try:
    erg = {"kandidaten": kandidaten, "verbuchen": verbuchen}[A["aktion"]]()
except Exception as e:
    erg = {"ok": False, "fehler": f"{type(e).__name__}: {e}"[:300]}
print("YT_ERGEBNIS " + json.dumps(erg, ensure_ascii=False))
'''


def pruefen(a) -> tuple[dict | None, str]:
    """Lässt nur die zwei bekannten Aufträge in genau bekannter Form durch: (bereinigter Auftrag, Fehlermeldung)."""
    if not isinstance(a, dict):
        return None, "kein Auftrag"
    try:
        if a.get("aktion") == "kandidaten":
            titel = str(a.get("titel", ""))[:120].strip()
            return ({"aktion": "kandidaten", "titel": titel}, "") if titel else (None, "kein Titel")
        if a.get("aktion") == "verbuchen":
            if a.get("art") not in ("serie", "film") or not re.fullmatch(r"[0-9]{1,12}", str(a.get("media_id", ""))):
                return None, "art oder media_id fehlt"
            folgen = [[int(s), int(e)] for s, e in a.get("folgen") or []]
            if a["art"] == "serie" and not 0 < len(folgen) <= 12:
                return None, "keine oder zu viele Folgen"
            if any(not (0 <= s <= 200 and 0 < e <= 5000) for s, e in folgen):
                return None, "Staffel oder Folge außerhalb des Möglichen"
            sauber = {"aktion": "verbuchen", "art": a["art"], "media_id": str(a["media_id"]), "folgen": folgen, "nochmal": bool(a.get("nochmal"))}
            if a.get("datum"):      # freiwillig: der Tag, an dem es gesehen wurde – nie in der Zukunft
                tag = dt.date.fromisoformat(str(a["datum"]))
                # „Heute“ nach der Uhr der Installation, nicht nach der des Containers (dort gilt oft UTC):
                # sonst wäre kurz nach Mitternacht der heutige Tag noch „in der Zukunft“.
                heute = dt.datetime.now(zone()).date()
                if not dt.date(2000, 1, 1) <= tag <= heute or str(a["datum"]) != tag.isoformat():
                    return None, "Datum außerhalb des Möglichen"
                sauber["datum"] = tag.isoformat()
            return sauber, ""
    except (TypeError, ValueError):
        return None, "Auftrag nicht lesbar"
    return None, "unbekannte Aktion"


async def _im_container(auftrag: dict) -> dict:
    """Führt das feste Programm im Yamtrack-Container aus (nur der Helfer ruft das auf)."""
    try:
        async with aiohttp.ClientSession(connector=aiohttp.UnixConnector(path=SOCKET), timeout=aiohttp.ClientTimeout(total=120)) as s:
            async with s.post(f"http://docker/containers/{CONTAINER}/exec", json={
                    "Cmd": ["python", "manage.py", "shell", "-c", IM_CONTAINER], "Env": ["YT_AUFTRAG=" + json.dumps(auftrag)],
                    "AttachStdout": True, "AttachStderr": True, "Tty": True}) as r:
                if r.status != 201:
                    return {"ok": False, "fehler": f"Yamtrack-Container nicht ansprechbar (HTTP {r.status})"}
                kennung = (await r.json())["Id"]
            async with s.post(f"http://docker/exec/{kennung}/start", json={"Detach": False, "Tty": True}) as r:
                aus = (await r.read()).decode("utf-8", "replace")
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, KeyError, ValueError) as e:
        return {"ok": False, "fehler": f"Docker nicht erreichbar: {type(e).__name__}"}
    for zeile in reversed(aus.splitlines()):
        if "YT_ERGEBNIS " in zeile:      # davor können Farbcodes der Django-Konsole stehen
            try:
                return json.loads(zeile.split("YT_ERGEBNIS ", 1)[1])
            except ValueError:
                break
    return {"ok": False, "fehler": "Yamtrack hat nicht geantwortet: " + aus[-200:]}


def helfer_app(ausfuehren=_im_container) -> web.Application:
    async def annehmen(request: web.Request) -> web.Response:
        try:
            roh = await request.json()
        except ValueError:
            return web.json_response({"ok": False, "fehler": "kein JSON"}, status=400)
        auftrag, fehler = pruefen(roh)
        if auftrag is None:
            return web.json_response({"ok": False, "fehler": fehler}, status=400)
        return web.json_response(await ausfuehren(auftrag), dumps=lambda o: json.dumps(o, ensure_ascii=False))

    app = web.Application(client_max_size=MAX_AUFTRAG)
    app.add_routes([web.post("/auftrag", annehmen), web.get("/", lambda r: web.json_response({"ok": True, "container": CONTAINER}))])
    return app


async def auftrag(helfer: str, a) -> dict:
    """Homies Seite: prüft den Auftrag und reicht ihn an den Helfer weiter."""
    sauber, fehler = pruefen(a)
    if sauber is None:
        return {"ok": False, "fehler": fehler}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=130)) as s:
            async with s.post(helfer.rstrip("/") + "/auftrag", json=sauber) as r:
                return await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
        return {"ok": False, "fehler": "Der Yamtrack-Helfer ist nicht erreichbar."}
