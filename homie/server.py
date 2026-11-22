"""Webserver: Anmeldung, Onboarding, Modul-Menü und eine kleine API. Ohne Anmeldung gibt es nur Login/Einrichtung."""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import re
import time
from urllib.parse import urlsplit

import aiohttp
import jinja2
from aiohttp import web
from yarl import URL

from . import agenten, assistent, ausfuehren, dokumente, gesundheit, katalog, meintag, module, plaene, proxmox, tag, verbinden
from .ablage import Ablage
from .anmeldung import COOKIE, MIN_LAENGE, Anmeldung, passwort_maengel
from .config import PAKET, VERSION, Einstellungen
from .db import Datenbank
from .erkundung import Erkundung, letzte, von_hand

OEFFENTLICH = ("/login", "/einrichten")
KOPFZEILEN = {
    "Content-Security-Policy": "default-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=(self)",
}
K_EINST = web.AppKey("einst", Einstellungen)
K_DB = web.AppKey("db", Datenbank)
K_ANM = web.AppKey("anmeldung", Anmeldung)
K_ABLAGE = web.AppKey("ablage", Ablage)
K_JINJA = web.AppKey("jinja", jinja2.Environment)
K_ERK = web.AppKey("erkundung", Erkundung)
K_SITZUNG = web.RequestKey("sitzung", object)
K_AGENT = web.RequestKey("agent", str)
K_LAUF = web.AppKey("lauf", dict)
K_BRIEFE = web.AppKey("briefe", dict)       # Bremse für den Briefkasten der Gesundheits-App: Absender → Zeitpunkte
BRIEFKASTEN = "/api/health-webhook"


def _ist_api(request: web.Request) -> bool:
    return request.path.startswith("/api/")


def _adresse(request: web.Request) -> str:
    return request.remote or "?"


def _https(request: web.Request) -> bool:
    return request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"


@web.middleware
async def kopfzeilen(request: web.Request, handler):
    try:
        antwort = await handler(request)
    except web.HTTPException as e:
        antwort = e
    for k, v in KOPFZEILEN.items():
        antwort.headers.setdefault(k, v)
    if not request.path.startswith("/static/") and "Cache-Control" not in antwort.headers:
        antwort.headers["Cache-Control"] = "no-store"
    if isinstance(antwort, web.HTTPException):
        raise antwort
    return antwort


@web.middleware
async def herkunft(request: web.Request, handler):
    """Schreibende Aufrufe nur von der eigenen Seite (Schutz vor fremden Webseiten, die Formulare abschicken)."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin is not None:
            if urlsplit(origin).netloc != request.host:
                raise web.HTTPForbidden(text="Aufruf von fremder Seite abgelehnt.")
        elif request.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            raise web.HTTPForbidden(text="Aufruf von fremder Seite abgelehnt.")
    return await handler(request)


@web.middleware
async def torwaechter(request: web.Request, handler):
    """Ohne Sitzung ist nichts erreichbar außer Login, Einrichtung und dem Aussehen dieser beiden Seiten."""
    if request.path.startswith("/static/"):
        return await handler(request)
    if request.path == "/agent" or request.path.startswith("/agent/"):
        # Helfende Agenten: eigener Schlüssel, eigene, enge Wege – keine Sitzung, kein Zugriff auf den Rest.
        name = agenten.finden(request.app[K_DB], request.headers.get("Authorization"))
        if name is None:
            return web.json_response({"fehler": "kein gültiger Agenten-Schlüssel"}, status=401)
        request[K_AGENT] = name
        return await handler(request)
    if request.path == BRIEFKASTEN and request.method == "POST":
        # Die Gesundheits-App am Handy hat keine Anmeldung bei Homie. Sie weist sich mit ihrer Unterschrift aus,
        # die der Notiz-Assistent prüft – ohne Unterschrift nimmt schon Homie nichts an.
        return await handler(request)
    anm = request.app[K_ANM]
    sitzung = anm.sitzung_finden(request.cookies.get(COOKIE))
    request[K_SITZUNG] = sitzung
    if request.path in OEFFENTLICH:
        return await handler(request)
    if sitzung is None:
        if _ist_api(request):
            return web.json_response({"fehler": "nicht angemeldet"}, status=401)
        raise web.HTTPSeeOther("/login" if anm.eingerichtet() else "/einrichten")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        marke = request.headers.get("X-Homie-CSRF")
        if marke is None and request.content_type in ("application/x-www-form-urlencoded", "multipart/form-data"):
            marke = (await request.post()).get("csrf")
        if not isinstance(marke, str) or not hmac.compare_digest(marke, sitzung.csrf):
            raise web.HTTPForbidden(text="Sicherheitsmarke fehlt oder ist abgelaufen. Seite neu laden.")
    return await handler(request)


def _eigene_seiten(app: web.Application) -> list[dict]:
    """HTML-Dateien im Ordner „seiten“ des Datenordners werden zu zusätzlichen Tabs (z. B. ein eigener Blueprint)."""
    try:
        dateien = sorted(app[K_EINST].seiten.glob("*.html"))
    except OSError:
        return []
    return [{"id": d.stem, "titel": d.stem.replace("-", " ").replace("_", " ").title(), "datei": d}
            for d in dateien[:8] if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,30}", d.stem)]


def _seite(request: web.Request, vorlage: str, status: int = 200, **werte) -> web.Response:
    app = request.app
    sitzung = request.get(K_SITZUNG)
    menue = []
    if sitzung is not None:
        menue = [s.modul for s in module.stand(app[K_DB], app[K_ABLAGE]) if s.aktiv]
    html = app[K_JINJA].get_template(vorlage).render(
        version=VERSION, pfad=request.path, menue=menue, csrf=sitzung.csrf if sitzung else "",
        eigene_seiten=_eigene_seiten(app) if sitzung is not None else [], **werte
    )
    return web.Response(text=html, content_type="text/html", status=status)


def _cookie_setzen(request: web.Request, antwort: web.StreamResponse, wert: str) -> None:
    antwort.set_cookie(
        COOKIE, wert, max_age=request.app[K_ANM].dauer, httponly=True, samesite="Lax", secure=_https(request), path="/"
    )


async def _rechnen(funktion, *werte):
    """Passwort-Hashes sind absichtlich langsam – nicht im Hauptablauf rechnen."""
    return await asyncio.get_running_loop().run_in_executor(None, funktion, *werte)


# ---------- Einrichtung und Anmeldung ----------

async def einrichten_zeigen(request: web.Request) -> web.Response:
    if request.app[K_ANM].eingerichtet():
        raise web.HTTPSeeOther("/" if request.get(K_SITZUNG) else "/login")
    return _seite(request, "einrichten.html", min_laenge=MIN_LAENGE, fehler=None)


async def einrichten(request: web.Request) -> web.Response:
    anm = request.app[K_ANM]
    if anm.eingerichtet():
        raise web.HTTPSeeOther("/login")
    daten = await request.post()
    passwort, wiederholung = str(daten.get("passwort", "")), str(daten.get("wiederholung", ""))
    fehler = passwort_maengel(passwort, wiederholung)
    if fehler:
        return _seite(request, "einrichten.html", status=400, min_laenge=MIN_LAENGE, fehler=fehler)
    if not await _rechnen(anm.konto_anlegen, passwort):
        raise web.HTTPSeeOther("/login")
    antwort = web.HTTPSeeOther("/onboarding")
    _cookie_setzen(request, antwort, anm.sitzung_anlegen(request.headers.get("User-Agent", "")))
    raise antwort


async def login_zeigen(request: web.Request) -> web.Response:
    if not request.app[K_ANM].eingerichtet():
        raise web.HTTPSeeOther("/einrichten")
    if request.get(K_SITZUNG):
        raise web.HTTPSeeOther("/")
    return _seite(request, "login.html", fehler=None)


async def login(request: web.Request) -> web.Response:
    anm = request.app[K_ANM]
    if not anm.eingerichtet():
        raise web.HTTPSeeOther("/einrichten")
    wer = _adresse(request)
    warten = anm.gesperrt_sekunden(wer)
    if warten:
        return _seite(request, "login.html", status=429, fehler=f"Zu viele Fehlversuche. Bitte {warten} Sekunden warten.")
    passwort = str((await request.post()).get("passwort", ""))
    if not await _rechnen(anm.passwort_stimmt, passwort):
        anm.fehlversuch(wer)
        return _seite(request, "login.html", status=401, fehler="Das Passwort stimmt nicht.")
    anm.erfolg(wer)
    antwort = web.HTTPSeeOther("/")
    _cookie_setzen(request, antwort, anm.sitzung_anlegen(request.headers.get("User-Agent", "")))
    raise antwort


async def logout(request: web.Request) -> web.Response:
    request.app[K_ANM].sitzung_beenden(request[K_SITZUNG].kennung)
    antwort = web.HTTPSeeOther("/login")
    antwort.del_cookie(COOKIE, path="/")
    raise antwort


# ---------- Seiten ----------

async def start(request: web.Request) -> web.Response:
    raise web.HTTPSeeOther("/uebersicht" if _dienste(request.app) else "/onboarding")


# Adressen, unter denen Seiten früher erreichbar waren (Lesezeichen, App-Symbol auf dem Handy) → heutige Seite
FRUEHER = {"/mein-tag": "/m/tag", "/index.html": "/m/tag", "/dokumente": "/m/dokumente", "/aufnahme": "/m/aufnahme", "/blueprint": "/s/blueprint",
           "/blueprint.html": "/s/blueprint"}


async def frueher(request: web.Request) -> web.Response:
    raise web.HTTPSeeOther(FRUEHER[request.path.rstrip("/") or "/"])


async def _erreichbar(sitzung: aiohttp.ClientSession, adresse: str) -> tuple[bool, int]:
    beginn = time.monotonic()
    try:
        async with sitzung.get(adresse, allow_redirects=False):
            return True, int((time.monotonic() - beginn) * 1000)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
        return False, 0


async def uebersicht(request: web.Request) -> web.Response:
    """Startseite: alle Dienste mit ihrem Zustand in diesem Augenblick (ein lesender Abruf je Dienst)."""
    app = request.app
    karten = [k for k in _karten(app) if k["zustand"] != "ignoriert" and k["adresse"]]
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False, limit=30), timeout=aiohttp.ClientTimeout(total=3)) as s:
        antworten = await asyncio.gather(*(_erreichbar(s, k["adresse"]) for k in karten))
    for k, (da, ms) in zip(karten, antworten):
        k["da"], k["ms"] = da, ms
    karten.sort(key=lambda k: (k["da"], k["zustand"] != "verbunden", k["name"].lower()))
    return _seite(request, "uebersicht.html", dienste=karten, da=sum(1 for k in karten if k["da"]),
                  module=[s for s in module.stand(app[K_DB], app[K_ABLAGE]) if s.aktiv and not s.modul.kern], letzte=letzte(app[K_DB]))


ZURUECK = ('<a href="/" style="position:fixed;z-index:2147483647;left:12px;bottom:12px;padding:9px 16px;border-radius:999px;'
           'background:#252952;color:#eef0ff;font:600 13px system-ui,sans-serif;text-decoration:none;box-shadow:0 6px 18px rgba(0,0,0,.45)">'
           '← Zurück zu Homie</a>')


async def eigene_seite(request: web.Request) -> web.Response:
    """Eigene Seite aus dem Datenordner. Sie läuft abgeschottet: Skripte dürfen laufen, kommen aber weder an Homies
    Sitzung noch an seine Schnittstellen, und laden nichts aus dem Internet nach (außer Bildern)."""
    seite = next((s for s in _eigene_seiten(request.app) if s["id"] == request.match_info["name"]), None)
    if seite is None:
        raise web.HTTPNotFound()
    try:
        inhalt = seite["datei"].read_text(encoding="utf-8", errors="replace")[:5_000_000]
    except OSError:
        raise web.HTTPNotFound()
    stelle = re.search(r"<body[^>]*>", inhalt, re.I)
    inhalt = inhalt[:stelle.end()] + ZURUECK + inhalt[stelle.end():] if stelle else ZURUECK + inhalt
    return web.Response(text=inhalt, content_type="text/html", headers={
        "Content-Security-Policy": "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; "
                                   "default-src 'unsafe-inline' data: blob:; img-src * data: blob:; frame-ancestors 'none'"})


async def _docker_stand(app: web.Application) -> dict:
    url = app[K_EINST].docker_url
    if not url:
        return {"zustand": "aus", "text": "ausgeschaltet"}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1.5)) as s:
            async with s.get(url + "/_ping") as r:
                if r.status == 200:
                    return {"zustand": "bereit", "text": "bereit (nur lesend)"}
                return {"zustand": "fehler", "text": f"antwortet mit Fehler {r.status}"}
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return {"zustand": "fehler", "text": "nicht erreichbar"}


def _dienste(app: web.Application) -> list[dict]:
    return [
        {**dict(z), "details": json.loads(z["details"] or "{}")}
        for z in app[K_DB].alle("SELECT id, art, name, adresse, zustand, gefunden, details FROM dienst ORDER BY name, adresse")
    ]


def _karten(app: web.Application) -> list[dict]:
    """Gefundene Dienste so aufbereitet, wie die Onboarding-Karten sie brauchen."""
    stand = letzte(app[K_DB]) or {}
    karten = []
    for d in _dienste(app):
        e = katalog.eintrag(d["details"].get("kennung", ""))
        karten.append({
            "id": d["id"], "name": d["name"], "zustand": d["zustand"], "adresse": d["adresse"],
            "geraet": d["details"].get("geraet", ""),
            "beschreibung": e.beschreibung if e else d["art"], "farbe": e.farbe if e else "#8b7cff",
            "felder": e.felder if e else (), "schaltet_frei": e.schaltet_frei if e else "",
            "von_hand": d["details"].get("quelle") == "hand",
            "vermisst": bool(stand) and d["details"].get("quelle") != "hand" and d["details"].get("gesehen", 0) < stand.get("zeit", 0),
        })
    return karten


def _beispiele(app: web.Application) -> list[dict]:
    try:
        roh = json.loads(app[K_EINST].beispiele.read_text(encoding="utf-8"))["dienste"]
    except (OSError, ValueError, KeyError):
        return []
    return [{
        "id": 0, "name": d["name"], "zustand": d["zustand"], "adresse": d["adresse"], "geraet": "", "farbe": d.get("farbe", "#8b7cff"),
        "beschreibung": d["details"].get("beschreibung", ""), "felder": (), "braucht": d["details"].get("braucht", ""),
        "schaltet_frei": d["details"].get("schaltet_frei", ""), "vermisst": False, "von_hand": False,
    } for d in roh]


async def onboarding(request: web.Request, status: int = 200, kartenfehler: dict | None = None, hand: str = "",
                     planfehler: str = "", neuer_schluessel: str = "") -> web.Response:
    app = request.app
    beispiel = request.query.get("beispiel") == "1"
    erk = app[K_ERK]
    karten = _beispiele(app) if beispiel else _karten(app)
    return _seite(
        request, "onboarding.html", status=status,
        beispiel=beispiel,
        dienste=[k for k in karten if k["zustand"] != "ignoriert"],
        ignoriert=[k for k in karten if k["zustand"] == "ignoriert"],
        kartenfehler=kartenfehler or {}, ok=request.query.get("ok", ""), hand=hand,
        proxmox_da=_zugang(app, "virtualisierung", ("token-id", "token")) is not None,
        plaene=plaene.alle(app[K_DB]), rezepte=plaene.REZEPTE, planfehler=planfehler,
        helfer=agenten.alle(app[K_DB]), neuer_schluessel=neuer_schluessel,
        module=[s for s in module.stand(app[K_DB], app[K_ABLAGE]) if not s.modul.kern],
        docker=await _docker_stand(app),
        erkundung={"laeuft": erk.laeuft, "text": erk.text, "prozent": int(erk.anteil * 100), "fehler": erk.fehler},
        letzte=None if beispiel else letzte(app[K_DB]),
    )


async def erkundung_start(request: web.Request) -> web.Response:
    request.app[K_ERK].starten()
    raise web.HTTPSeeOther("/onboarding")


async def dienst_neu(request: web.Request) -> web.Response:
    in_ordnung, meldung = await von_hand(request.app[K_DB], str((await request.post()).get("adresse", "")))
    if not in_ordnung:
        return await onboarding(request, 400, hand=meldung)
    raise web.HTTPSeeOther("/onboarding#dienste")


def _zugang(app: web.Application, art: str, felder: tuple[str, ...]) -> tuple[str, dict[str, str]] | None:
    """Adresse und Schlüssel des ersten verbundenen Dienstes dieser Art – nur für Aufrufe beim Dienst selbst."""
    for d in _dienste(app):
        if d["art"] == art and d["zustand"] == "verbunden":
            werte = {f: app[K_ABLAGE].lesen(module.schluesselname(d["id"], f)) for f in felder}
            if all(werte.values()):
                return d["adresse"], werte
    return None


async def _seite_dokumente(request: web.Request, modul: module.Modul) -> web.Response:
    """Nur das Gerüst; die Dokumente kommen über /api/dokumente. Das PDF im Leser ist ein Rahmen derselben Seite."""
    return _seite(request, "dokumente.html", modul=modul)


def _archiv(request: web.Request) -> tuple[str, dict[str, str]]:
    aktiv = any(s.aktiv and s.modul.id == "dokumente" for s in module.stand(request.app[K_DB], request.app[K_ABLAGE]))
    zugang = _zugang(request.app, "dokumente", ("token",)) if aktiv else None
    if zugang is None:
        raise web.HTTPNotFound()
    return zugang


async def api_dokumente(request: web.Request) -> web.Response:
    zugang = _archiv(request)
    try:
        daten = await dokumente.alle(zugang[0], zugang[1]["token"], frisch=request.query.get("frisch") == "1")
    except dokumente.DokumenteFehler as e:
        return web.json_response({"fehler": str(e)}, status=502)
    return web.json_response(daten, dumps=lambda o: json.dumps(o, ensure_ascii=False))


async def api_dokumente_suche(request: web.Request) -> web.Response:
    zugang, frage = _archiv(request), request.query.get("q", "").strip()[:200]
    if len(frage) < 2:
        return web.json_response({"anzahl": 0, "treffer": []})
    try:
        return web.json_response(await dokumente.volltext(zugang[0], zugang[1]["token"], frage), dumps=lambda o: json.dumps(o, ensure_ascii=False))
    except dokumente.DokumenteFehler as e:
        return web.json_response({"fehler": str(e)}, status=502)


async def dokument_datei(request: web.Request) -> web.Response:
    zugang, laden = _archiv(request), request.query.get("laden") == "1"
    try:
        inhalt, art, name = await dokumente.datei(zugang[0], zugang[1]["token"], int(request.match_info["nr"]), laden)
    except dokumente.DokumenteFehler:
        raise web.HTTPNotFound()
    name = re.sub(r"[^\w.\- ()äöüÄÖÜß]", "_", name)[:120] or "dokument.pdf"
    return web.Response(body=inhalt, content_type=art, headers={
        "Content-Disposition": f"{'attachment' if laden else 'inline'}; filename*=UTF-8''{URL.build(path=name).raw_path}",
        "Cache-Control": "private, max-age=600",
        # Das PDF darf im Leser dieser Seite erscheinen – nirgends sonst.
        "Content-Security-Policy": "frame-ancestors 'self'", "X-Frame-Options": "SAMEORIGIN"})


async def _seite_tag(request: web.Request, modul: module.Modul) -> web.Response:
    """Die Seite selbst ist nur das Gerüst; ihr Inhalt kommt über /api/tag. Bilder dürfen von https-Adressen kommen (Filmplakate)."""
    antwort = _seite(request, "tag.html", modul=modul)
    antwort.headers["Content-Security-Policy"] = KOPFZEILEN["Content-Security-Policy"].replace("img-src 'self' data:", "img-src 'self' data: https:")
    return antwort


def _ich(app: web.Application) -> str:
    z = app[K_DB].eine("SELECT wert FROM merk WHERE name='ich'")
    return z["wert"] if z else ""


async def api_tag(request: web.Request) -> web.Response:
    app = request.app
    try:
        tage = int(request.query.get("tage", "7"))
    except ValueError:
        tage = 7
    return web.json_response(await meintag.schnappschuss(
        _zugang(app, "assistent", ("token",)), _zugang(app, "homeassistant", ("token",)), tage, _ich(app), app[K_EINST].yamtrack),
        dumps=lambda o: json.dumps(o, ensure_ascii=False))


async def api_tag_entscheid(request: web.Request) -> web.Response:
    zugang = _zugang(request.app, "assistent", ("token",))
    if zugang is None:
        return web.json_response({"ok": False, "fehler": "Der Notiz-Assistent ist nicht verbunden."}, status=409)
    try:
        daten = await request.json()
        kennung, annehmen = str(daten["id"])[:80], bool(daten.get("annehmen"))
    except (ValueError, KeyError, TypeError):
        return web.json_response({"ok": False, "fehler": "Ungültige Anfrage."}, status=400)
    in_ordnung, meldung = await assistent.entscheid(zugang[0], zugang[1]["token"], request.match_info["art"], kennung, annehmen)
    meintag._merker.clear()      # die Seite soll die Änderung sofort zeigen
    return web.json_response({"ok": in_ordnung, **({} if in_ordnung else {"fehler": meldung})})


async def _seite_gesundheit(request: web.Request, modul: module.Modul) -> web.Response:
    zugang = _zugang(request.app, "homeassistant", ("token",))
    daten, fehler = None, ""
    try:
        daten = await gesundheit.uebersicht(zugang[0], zugang[1]["token"])
    except gesundheit.GesundheitFehler as e:
        fehler = str(e)
    helfer = _zugang(request.app, "assistent", ("token",))      # freiwillige Ergänzung: langer Verlauf und Trainings
    lang = await assistent.gesundheit(helfer[0], helfer[1]["token"]) if helfer else None
    return _seite(request, "gesundheit.html", status=200 if daten else 502, modul=modul, daten=daten, fehler=fehler, lang=lang,
                  meldung=request.query.get("meldung", ""))


async def _seite_aufnahme(request: web.Request, modul: module.Modul) -> web.Response:
    zugang = _zugang(request.app, "assistent", ("token",))
    daten, fehler = None, ""
    try:
        daten = await assistent.eintraege(zugang[0], zugang[1]["token"])
    except assistent.AssistentFehler as e:
        fehler = str(e)
    return _seite(request, "aufnahme.html", status=200 if daten else 502, modul=modul, daten=daten, fehler=fehler)


async def _seite_assistent(request: web.Request, modul: module.Modul) -> web.Response:
    zugang = _zugang(request.app, "assistent", ("token",))
    daten, fehler = None, ""
    try:
        daten = await assistent.profil_und_nutzung(zugang[0], zugang[1]["token"])
    except assistent.AssistentFehler as e:
        fehler = str(e)
    return _seite(request, "assistent.html", status=200 if daten else 502, modul=modul, daten=daten, fehler=fehler,
                  meldung=request.query.get("meldung", ""))


async def entscheid(request: web.Request) -> web.Response:
    """Der Nutzer nimmt einen Vorschlag des Assistenten an oder lehnt ihn ab. Das ändert Daten im Assistenten."""
    zugang = _zugang(request.app, "assistent", ("token",))
    if zugang is None:
        raise web.HTTPNotFound()
    daten = await request.post()
    art = request.match_info["art"]
    _, meldung = await assistent.entscheid(zugang[0], zugang[1]["token"], art, str(daten.get("id", ""))[:80], daten.get("annehmen") == "ja")
    ziel = {"finanzen": "/m/finanzen", "training": "/m/gesundheit", "profil": "/m/assistent"}[art]
    raise web.HTTPSeeOther(str(URL(ziel).with_query(meldung=meldung)))


async def briefkasten(request: web.Request) -> web.Response:
    """Nimmt die Lieferung der Gesundheits-App an und reicht sie unverändert an den Notiz-Assistenten weiter."""
    app = request.app
    signatur, ausweis = request.headers.get("X-Signature", ""), request.headers.get("Authorization", "")
    if not (re.fullmatch(r"sha256=[0-9a-f]{64}", signatur) or re.fullmatch(r"Bearer [\x21-\x7e]{16,200}", ausweis)):
        return web.json_response({"fehler": "Unterschrift fehlt"}, status=401)
    jetzt, wer = time.time(), _adresse(request)
    zeiten = [t for t in app[K_BRIEFE].get(wer, []) if jetzt - t < 60]
    if len(zeiten) >= 30:
        return web.json_response({"fehler": "zu viele Lieferungen"}, status=429)
    app[K_BRIEFE][wer] = zeiten + [jetzt]
    if len(app[K_BRIEFE]) > 500:
        app[K_BRIEFE].clear()
    zugang = _zugang(app, "assistent", ("token",))
    if zugang is None:
        return web.json_response({"fehler": "Der Notiz-Assistent ist nicht verbunden."}, status=503)
    inhalt = bytearray()
    async for stueck in request.content.iter_chunked(65536):
        inhalt.extend(stueck)
        if len(inhalt) > assistent.MAX_LIEFERUNG:
            return web.json_response({"fehler": "zu groß"}, status=413)
    if not inhalt:
        return web.json_response({"fehler": "leer"}, status=400)
    status, antwort = await assistent.lieferung_weitergeben(zugang[0], bytes(inhalt), signatur, ausweis)
    meintag._merker.clear()
    return web.Response(body=antwort, status=status, content_type="application/json", charset="utf-8")


async def _seite_finanzen(request: web.Request, modul: module.Modul) -> web.Response:
    zugang = _zugang(request.app, "assistent", ("token",))
    daten, fehler = None, ""
    try:
        daten = await assistent.finanzen(zugang[0], zugang[1]["token"])
    except assistent.AssistentFehler as e:
        fehler = str(e)
    return _seite(request, "finanzen.html", status=200 if daten else 502, modul=modul, daten=daten, fehler=fehler, meldung=request.query.get("meldung", ""))


async def aufnahme_senden(request: web.Request) -> web.Response:
    """Nimmt eine Sprachaufnahme aus dem Browser an und gibt sie an den Notiz-Assistenten weiter. Homie behält nichts."""
    aktiv = any(s.aktiv and s.modul.id == "aufnahme" for s in module.stand(request.app[K_DB], request.app[K_ABLAGE]))
    zugang = _zugang(request.app, "assistent", ("token",)) if aktiv else None
    if zugang is None:
        return web.json_response({"fehler": "Das Modul Aufnahme ist nicht aktiv."}, status=404)
    art = request.content_type
    if not art.startswith("audio/") and not art.startswith("video/"):
        return web.json_response({"fehler": "Das ist keine Tonaufnahme."}, status=415)
    ton = bytearray()
    async for stueck in request.content.iter_chunked(65536):
        ton.extend(stueck)
        if len(ton) > assistent.MAX_AUFNAHME:
            return web.json_response({"fehler": "Die Aufnahme ist zu lang."}, status=413)
    try:
        name = await assistent.aufnahme_senden(zugang[0], zugang[1]["token"], bytes(ton), request.headers.get("Content-Type", art),
                                               request.headers.get("X-Aufnahme-Zeit", ""))
    except assistent.AssistentFehler as e:
        return web.json_response({"fehler": str(e)}, status=502)
    return web.json_response({"ok": True, "name": name})


async def dokument_vorschau(request: web.Request) -> web.Response:
    zugang = _archiv(request)
    try:
        bild, art = await dokumente.vorschau(zugang[0], zugang[1]["token"], int(request.match_info["nr"]))
    except dokumente.DokumenteFehler:
        raise web.HTTPNotFound()
    return web.Response(body=bild, content_type=art, headers={"Cache-Control": "private, max-age=86400, immutable"})


def _dienst(request: web.Request) -> dict:
    try:
        nummer = int(request.match_info["id"])
    except ValueError:
        raise web.HTTPNotFound()
    for d in _dienste(request.app):
        if d["id"] == nummer:
            return d
    raise web.HTTPNotFound()


def _schluessel_loeschen(app: web.Application, nummer: int) -> None:
    for name in app[K_ABLAGE].namen():
        if name.startswith(f"dienst:{nummer}:"):
            app[K_ABLAGE].loeschen(name)


async def dienst_verbinden(request: web.Request) -> web.Response:
    app, d = request.app, _dienst(request)
    e = katalog.eintrag(d["details"].get("kennung", ""))
    if e is None:
        raise web.HTTPNotFound()
    daten = await request.post()
    werte = {f.name: str(daten.get(f.name, "")).strip() for f in e.felder}
    if any(not w for w in werte.values()):
        return await onboarding(request, 400, {d["id"]: "Bitte alle Felder ausfüllen."})
    in_ordnung, meldung = await verbinden.pruefen(e, d["adresse"], werte)
    if not in_ordnung:
        return await onboarding(request, 400, {d["id"]: meldung})
    for name, wert in werte.items():
        app[K_ABLAGE].setzen(module.schluesselname(d["id"], name), wert)
    app[K_DB].ausfuehren("UPDATE dienst SET zustand='verbunden' WHERE id=?", (d["id"],))
    raise web.HTTPSeeOther(f"/onboarding?ok={d['id']}#dienst-{d['id']}")


async def dienst_zustand(request: web.Request) -> web.Response:
    """Trennen, ignorieren oder wieder zeigen. Beim Trennen und Ignorieren werden die Schlüssel gelöscht."""
    d, was = _dienst(request), request.match_info["was"]
    neu = {"trennen": "gefunden", "ignorieren": "ignoriert", "zeigen": "gefunden"}[was]
    if was != "zeigen":
        _schluessel_loeschen(request.app, d["id"])
    request.app[K_DB].ausfuehren("UPDATE dienst SET zustand=? WHERE id=?", (neu, d["id"]))
    raise web.HTTPSeeOther("/onboarding")


# ---------- Pläne ----------

async def plan_neu(request: web.Request) -> web.Response:
    app = request.app
    zugang = _zugang(app, "virtualisierung", ("token-id", "token"))
    if zugang is None:
        return await onboarding(request, 400, planfehler="Dafür muss zuerst Proxmox verbunden sein.")
    daten = await request.post()
    try:
        nummer = await plaene.entwerfen(app[K_DB], zugang, str(daten.get("rezept", "")), dict(daten), "dir")
    except plaene.PlanFehler as e:
        return await onboarding(request, 400, planfehler=str(e))
    raise web.HTTPSeeOther(f"/plan/{nummer}")


def _plan(request: web.Request) -> dict:
    p = plaene.einer(request.app[K_DB], int(request.match_info["id"]))
    if p is None or p["zustand"] == "verworfen":
        raise web.HTTPNotFound()
    return p


async def plan_zeigen(request: web.Request) -> web.Response:
    plan = _plan(request)
    zugang = _zugang(request.app, "virtualisierung", ("token-id", "token"))
    befehle = plaene.rechte_befehle(zugang[1]["token-id"], plan["technik"]) if zugang and plan["technik"].get("rechte_fehlen") else []
    return _seite(request, "plan.html", plan=plan, befehle=befehle, fehler=request.query.get("fehler", ""))


async def plan_bestaetigen(request: web.Request) -> web.Response:
    """Nur der angemeldete Mensch kommt hierher. Erst jetzt wird an Proxmox geschrieben."""
    app, plan = request.app, _plan(request)
    zugang = _zugang(app, "virtualisierung", ("token-id", "token"))
    if zugang is None or plan["zustand"] != "entwurf" or not plan["machbar"] or plan["technik"].get("rechte_fehlen") \
            or str((await request.post()).get("gelesen", "")) != "ja":
        raise web.HTTPSeeOther(f"/plan/{plan['id']}?fehler=1")
    if plaene.bestaetigen(app[K_DB], plan["id"]):
        ausfuehren.starten(app[K_DB], app[K_ABLAGE], zugang, plan, **app[K_LAUF])
    raise web.HTTPSeeOther(f"/plan/{plan['id']}")


async def plan_verwerfen(request: web.Request) -> web.Response:
    plaene.verwerfen(request.app[K_DB], _plan(request)["id"])
    raise web.HTTPSeeOther("/onboarding#plaene")


# ---------- Helfende Agenten: Verwaltung (Mensch) und Schnittstelle (Agent) ----------

async def helfer_neu(request: web.Request) -> web.Response:
    name = str((await request.post()).get("name", ""))
    return await onboarding(request, neuer_schluessel=agenten.anlegen(request.app[K_DB], name))


async def helfer_entziehen(request: web.Request) -> web.Response:
    agenten.entziehen(request.app[K_DB], int(request.match_info["id"]))
    raise web.HTTPSeeOther("/onboarding#helfer")


AGENT_REGELN = [
    "Du darfst lesen und Pläne vorschlagen. Bestätigen und ausführen kann nur der Mensch im Dashboard.",
    "Erst lesen (/agent/zustand), dann dem Menschen in einfachen Worten sagen, was du vorschlägst, dann den Plan einreichen.",
    "Frag nie nach Passwörtern oder Schlüsseln und gib keine aus. Schlüssel trägt der Mensch selbst im Dashboard ein.",
]


def _plan_kurz(p: dict) -> dict:
    kurz = {k: p[k] for k in ("id", "titel", "rezept", "zustand", "von", "machbar", "schritte", "pruefung", "grenzen", "protokoll", "ergebnis")}
    return {**kurz, "parameter": {k: v for k, v in p["parameter"].items() if k != "ssh_schluessel"}}


async def agent_start(request: web.Request) -> web.Response:
    return web.json_response({
        "homie": VERSION, "agent": request[K_AGENT], "regeln": AGENT_REGELN,
        "wege": {"GET /agent/zustand": "Module, Dienste, letzte Erkundung, Pläne", "GET /agent/rezepte": "was sich planen lässt",
                 "GET /agent/plaene": "alle Pläne", "POST /agent/plaene": "Plan vorschlagen: {\"rezept\": …, \"parameter\": {…}}"},
    })


async def agent_zustand(request: web.Request) -> web.Response:
    app = request.app
    return web.json_response({
        "version": VERSION,
        "module": [{"id": s.modul.id, "titel": s.modul.titel, "aktiv": s.aktiv, "fehlt": s.fehlt} for s in module.stand(app[K_DB], app[K_ABLAGE])],
        "dienste": [{"id": d["id"], "name": d["name"], "art": d["art"], "zustand": d["zustand"], "adresse": d["adresse"]} for d in _dienste(app)],
        "erkundung": {k: v for k, v in (letzte(app[K_DB]) or {}).items() if k in ("zeit", "geraete", "dienste", "container", "docker")},
        "plaene": [_plan_kurz(p) for p in plaene.alle(app[K_DB])],
    })


async def agent_rezepte(request: web.Request) -> web.Response:
    return web.json_response([{
        "id": r.id, "titel": r.titel, "beschreibung": r.beschreibung,
        "parameter": {"name": "Name der VM (Kleinbuchstaben, Ziffern, Bindestriche)",
                      **{z.name: f"{z.titel}, {z.von}–{z.bis}{' ' + z.einheit if z.einheit else ''}, Standard {z.standard}" for z in r.zahlen}},
    } for r in plaene.REZEPTE])


async def agent_plaene(request: web.Request) -> web.Response:
    return web.json_response([_plan_kurz(p) for p in plaene.alle(request.app[K_DB])])


async def agent_plan_vorschlagen(request: web.Request) -> web.Response:
    app = request.app
    try:
        eingabe = await request.json()
        parameter = dict(eingabe.get("parameter") or {})
    except (ValueError, AttributeError, TypeError):
        return web.json_response({"fehler": "Erwartet wird JSON: {\"rezept\": …, \"parameter\": {…}}"}, status=400)
    zugang = _zugang(app, "virtualisierung", ("token-id", "token"))
    if zugang is None:
        return web.json_response({"fehler": "Proxmox ist nicht verbunden. Das kann nur der Mensch im Dashboard tun."}, status=409)
    if len([p for p in plaene.alle(app[K_DB]) if p["zustand"] == "entwurf"]) >= 20:
        return web.json_response({"fehler": "Es gibt schon viele offene Pläne. Bitte erst alte verwerfen lassen."}, status=429)
    try:
        nummer = await plaene.entwerfen(app[K_DB], zugang, str(eingabe.get("rezept", "")), parameter, f"Agent {request[K_AGENT]}")
    except plaene.PlanFehler as e:
        return web.json_response({"fehler": str(e)}, status=400)
    return web.json_response({**_plan_kurz(plaene.einer(app[K_DB], nummer)),
                              "hinweis": "Der Plan ist ein Entwurf. Bitte den Menschen, ihn im Dashboard unter Onboarding → Pläne zu lesen."}, status=201)


def _netzplan(app: web.Application) -> dict:
    db, stand = app[K_DB], letzte(app[K_DB]) or {}
    dienste: dict[str, list[dict]] = {}
    for k, d in zip(_karten(app), _dienste(app)):
        if k["zustand"] != "ignoriert":
            dienste.setdefault(d["details"].get("ip", ""), []).append(k)
    eigene, router = set(stand.get("eigene") or []), stand.get("router")
    geraete = []
    for z in db.alle("SELECT ip, name, mac, ports, sonstiges FROM geraet"):
        ip = z["ip"]
        geraete.append({
            "ip": ip, "name": z["name"], "mac": z["mac"], "ports": json.loads(z["ports"]),
            "dienste": dienste.get(ip, []), "sonstiges": json.loads(z["sonstiges"]),
            "rolle": "Router" if ip == router else "Dieser Rechner" if ip in eigene else "",
        })
    geraete.sort(key=lambda g: (g["rolle"] != "Router", g["rolle"] != "Dieser Rechner", not g["dienste"], int(ipaddress.IPv4Address(g["ip"]))))
    container = [{**dict(z), "ports": json.loads(z["ports"])} for z in db.alle("SELECT name, image, zustand, ports, stack FROM container ORDER BY stack, name")]
    return {"geraete": geraete, "container": container, "stand": stand, "router": router}


async def modulseite(request: web.Request) -> web.Response:
    kennung = request.match_info["id"]
    for s in module.stand(request.app[K_DB], request.app[K_ABLAGE]):
        if s.modul.id == kennung and s.aktiv and not s.modul.kern:
            if kennung == "netzplan":
                virt, virt_fehler = None, ""
                zugang = _zugang(request.app, "virtualisierung", ("token-id", "token"))
                if zugang:
                    try:
                        virt = await proxmox.lesen(zugang[0], zugang[1]["token-id"], zugang[1]["token"])
                    except proxmox.ProxmoxFehler as e:
                        virt_fehler = str(e)
                return _seite(request, "netzplan.html", modul=s.modul, virt=virt, virt_fehler=virt_fehler, **_netzplan(request.app))
            if kennung == "dokumente":
                return await _seite_dokumente(request, s.modul)
            if kennung == "tag":
                return await _seite_tag(request, s.modul)
            if kennung == "gesundheit":
                return await _seite_gesundheit(request, s.modul)
            if kennung == "aufnahme":
                return await _seite_aufnahme(request, s.modul)
            if kennung == "finanzen":
                return await _seite_finanzen(request, s.modul)
            if kennung == "assistent":
                return await _seite_assistent(request, s.modul)
            return _seite(request, "modul.html", modul=s.modul)
    raise web.HTTPNotFound(text="Dieses Modul ist nicht aktiv.")


# ---------- API (nur angemeldet) ----------

async def api_zustand(request: web.Request) -> web.Response:
    app = request.app
    return web.json_response({
        "version": VERSION,
        "dienste": len(_dienste(app)),
        "module_aktiv": [s.modul.id for s in module.stand(app[K_DB], app[K_ABLAGE]) if s.aktiv],
        "erkundung": {"docker": (await _docker_stand(app))["zustand"]},
    })


async def api_module(request: web.Request) -> web.Response:
    return web.json_response([s.als_dict() for s in module.stand(request.app[K_DB], request.app[K_ABLAGE])])


async def api_dienste(request: web.Request) -> web.Response:
    return web.json_response(_dienste(request.app))


async def api_erkundung(request: web.Request) -> web.Response:
    erk = request.app[K_ERK]
    return web.json_response({"laeuft": erk.laeuft, "text": erk.text, "anteil": erk.anteil, "fehler": erk.fehler,
                              "letzte": letzte(request.app[K_DB])})


async def api_netzplan(request: web.Request) -> web.Response:
    return web.json_response(_netzplan(request.app), dumps=lambda o: json.dumps(o, default=lambda x: x.__dict__))


def app_bauen(einst: Einstellungen, erkundung_ziele: list[str] | None = None, erkundung_ports: tuple[int, ...] | None = None,
              lauf: dict | None = None) -> web.Application:
    app = web.Application(middlewares=[kopfzeilen, herkunft, torwaechter], client_max_size=64 * 1024)
    db = Datenbank(einst.datenbank)
    app[K_EINST] = einst
    app[K_DB] = db
    app[K_ANM] = Anmeldung(db, einst.sitzung_tage)
    app[K_ABLAGE] = Ablage(db, einst.daten, einst.hauptschluessel)
    app[K_ERK] = Erkundung(db, einst.docker_url, erkundung_ziele, erkundung_ports)
    app[K_LAUF] = lauf or {}
    app[K_BRIEFE] = {}
    plaene.unterbrochene_markieren(db)
    app[K_JINJA] = jinja2.Environment(
        loader=jinja2.FileSystemLoader(PAKET / "templates"), autoescape=True, trim_blocks=True, lstrip_blocks=True
    )
    app.add_routes([
        web.get("/", start),
        web.get("/einrichten", einrichten_zeigen), web.post("/einrichten", einrichten),
        web.get("/login", login_zeigen), web.post("/login", login),
        web.post("/logout", logout),
        web.get("/onboarding", onboarding),
        web.get("/uebersicht", uebersicht),
        *[web.get(weg + zusatz, frueher) for weg in FRUEHER for zusatz in ("", "/") if not weg.endswith(".html") or not zusatz],
        web.get("/s/{name}", eigene_seite),
        web.post("/m/entscheid/{art:finanzen|training|profil}", entscheid),
        web.get("/m/{id}", modulseite),
        web.get("/api/zustand", api_zustand),
        web.get("/api/module", api_module),
        web.get("/api/dienste", api_dienste),
        web.get("/api/erkundung", api_erkundung),
        web.get("/api/tag", api_tag),
        web.post(BRIEFKASTEN, briefkasten),
        web.get("/api/dokumente", api_dokumente),
        web.get("/api/dokumente/suche", api_dokumente_suche),
        web.get("/m/dokumente/pdf/{nr:\\d+}", dokument_datei),
        web.post("/api/tag/entscheid/{art:finanzen|training|profil}", api_tag_entscheid),
        web.get("/api/netzplan", api_netzplan),
        web.post("/erkundung/start", erkundung_start),
        web.post("/dienst/neu", dienst_neu),
        web.post("/plan/neu", plan_neu),
        web.get("/plan/{id:\\d+}", plan_zeigen),
        web.post("/plan/{id:\\d+}/verwerfen", plan_verwerfen),
        web.post("/plan/{id:\\d+}/bestaetigen", plan_bestaetigen),
        web.post("/helfer/neu", helfer_neu),
        web.post("/helfer/{id:\\d+}/entziehen", helfer_entziehen),
        web.get("/agent", agent_start),
        web.get("/agent/zustand", agent_zustand),
        web.get("/agent/rezepte", agent_rezepte),
        web.get("/agent/plaene", agent_plaene),
        web.post("/agent/plaene", agent_plan_vorschlagen),
        web.post("/m/aufnahme/senden", aufnahme_senden),
        web.get("/m/dokumente/vorschau/{nr:\\d+}", dokument_vorschau),
        web.post("/dienst/{id}/verbinden", dienst_verbinden),
        web.post("/dienst/{id}/{was:trennen|ignorieren|zeigen}", dienst_zustand),
        web.static("/static", PAKET / "static"),
    ])

    async def aufraeumen(app: web.Application) -> None:
        db.schliessen()

    app.on_cleanup.append(aufraeumen)
    return app
