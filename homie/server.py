"""Webserver: Anmeldung, Onboarding, Modul-Menü und eine kleine API. Ohne Anmeldung gibt es nur Login/Einrichtung."""
from __future__ import annotations

import asyncio
import hmac
import json
import warnings
from urllib.parse import urlsplit

import aiohttp
import jinja2
from aiohttp import web

from . import module
from .ablage import Ablage
from .anmeldung import COOKIE, MIN_LAENGE, Anmeldung, passwort_maengel
from .config import PAKET, VERSION, Einstellungen
from .db import Datenbank

warnings.filterwarnings("ignore", category=web.NotAppKeyWarning)

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
    if not request.path.startswith("/static/"):
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
    anm = request.app[K_ANM]
    sitzung = anm.sitzung_finden(request.cookies.get(COOKIE))
    request["sitzung"] = sitzung
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


def _seite(request: web.Request, vorlage: str, status: int = 200, **werte) -> web.Response:
    app = request.app
    sitzung = request.get("sitzung")
    menue = []
    if sitzung is not None:
        menue = [s.modul for s in module.stand(app[K_DB], app[K_ABLAGE]) if s.aktiv]
    html = app[K_JINJA].get_template(vorlage).render(
        version=VERSION, pfad=request.path, menue=menue, csrf=sitzung.csrf if sitzung else "", **werte
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
        raise web.HTTPSeeOther("/" if request.get("sitzung") else "/login")
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
    if request.get("sitzung"):
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
    request.app[K_ANM].sitzung_beenden(request["sitzung"].kennung)
    antwort = web.HTTPSeeOther("/login")
    antwort.del_cookie(COOKIE, path="/")
    raise antwort


# ---------- Seiten ----------

async def start(request: web.Request) -> web.Response:
    raise web.HTTPSeeOther("/onboarding")


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
        for z in app[K_DB].alle("SELECT id, art, name, adresse, zustand, gefunden, details FROM dienst ORDER BY name")
    ]


def _beispiele(app: web.Application) -> list[dict]:
    try:
        return json.loads(app[K_EINST].beispiele.read_text(encoding="utf-8"))["dienste"]
    except (OSError, ValueError, KeyError):
        return []


async def onboarding(request: web.Request) -> web.Response:
    app = request.app
    beispiel = request.query.get("beispiel") == "1"
    return _seite(
        request, "onboarding.html",
        beispiel=beispiel,
        dienste=_beispiele(app) if beispiel else _dienste(app),
        module=[s for s in module.stand(app[K_DB], app[K_ABLAGE]) if not s.modul.kern],
        docker=await _docker_stand(app),
    )


async def modulseite(request: web.Request) -> web.Response:
    kennung = request.match_info["id"]
    for s in module.stand(request.app[K_DB], request.app[K_ABLAGE]):
        if s.modul.id == kennung and s.aktiv and not s.modul.kern:
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


def app_bauen(einst: Einstellungen) -> web.Application:
    app = web.Application(middlewares=[kopfzeilen, herkunft, torwaechter], client_max_size=64 * 1024)
    db = Datenbank(einst.datenbank)
    app[K_EINST] = einst
    app[K_DB] = db
    app[K_ANM] = Anmeldung(db, einst.sitzung_tage)
    app[K_ABLAGE] = Ablage(db, einst.daten, einst.hauptschluessel)
    app[K_JINJA] = jinja2.Environment(
        loader=jinja2.FileSystemLoader(PAKET / "templates"), autoescape=True, trim_blocks=True, lstrip_blocks=True
    )
    app.add_routes([
        web.get("/", start),
        web.get("/einrichten", einrichten_zeigen), web.post("/einrichten", einrichten),
        web.get("/login", login_zeigen), web.post("/login", login),
        web.post("/logout", logout),
        web.get("/onboarding", onboarding),
        web.get("/m/{id}", modulseite),
        web.get("/api/zustand", api_zustand),
        web.get("/api/module", api_module),
        web.get("/api/dienste", api_dienste),
        web.static("/static", PAKET / "static"),
    ])

    async def aufraeumen(app: web.Application) -> None:
        db.schliessen()

    app.on_cleanup.append(aufraeumen)
    return app
