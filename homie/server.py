"""Webserver: Anmeldung, Onboarding, Modul-Menü und eine kleine API. Ohne Anmeldung gibt es nur Login/Einrichtung."""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
from urllib.parse import urlsplit

import aiohttp
import jinja2
from aiohttp import web

from . import dokumente, gesundheit, katalog, module, tag, verbinden
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


def _seite(request: web.Request, vorlage: str, status: int = 200, **werte) -> web.Response:
    app = request.app
    sitzung = request.get(K_SITZUNG)
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


async def onboarding(request: web.Request, status: int = 200, kartenfehler: dict | None = None, hand: str = "") -> web.Response:
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
    zugang = _zugang(request.app, "dokumente", ("token",))
    suche = request.query.get("q", "").strip()[:200]
    try:
        seite = max(1, int(request.query.get("seite", "1")))
    except ValueError:
        seite = 1
    daten, fehler = None, ""
    try:
        daten = await dokumente.uebersicht(zugang[0], zugang[1]["token"], suche, seite)
    except dokumente.DokumenteFehler as e:
        fehler = str(e)
    return _seite(request, "dokumente.html", status=200 if daten else 502, modul=modul, suche=suche, daten=daten, fehler=fehler)


async def _seite_tag(request: web.Request, modul: module.Modul) -> web.Response:
    zugang = _zugang(request.app, "homeassistant", ("token",))
    daten, fehler = None, ""
    try:
        daten = await tag.uebersicht(zugang[0], zugang[1]["token"])
    except tag.TagFehler as e:
        fehler = str(e)
    return _seite(request, "tag.html", status=200 if daten else 502, modul=modul, daten=daten, fehler=fehler)


async def _seite_gesundheit(request: web.Request, modul: module.Modul) -> web.Response:
    zugang = _zugang(request.app, "homeassistant", ("token",))
    daten, fehler = None, ""
    try:
        daten = await gesundheit.uebersicht(zugang[0], zugang[1]["token"])
    except gesundheit.GesundheitFehler as e:
        fehler = str(e)
    return _seite(request, "gesundheit.html", status=200 if daten else 502, modul=modul, daten=daten, fehler=fehler)


async def dokument_vorschau(request: web.Request) -> web.Response:
    aktiv = any(s.aktiv and s.modul.id == "dokumente" for s in module.stand(request.app[K_DB], request.app[K_ABLAGE]))
    zugang = _zugang(request.app, "dokumente", ("token",)) if aktiv else None
    if zugang is None:
        raise web.HTTPNotFound()
    try:
        bild, art = await dokumente.vorschau(zugang[0], zugang[1]["token"], int(request.match_info["nr"]))
    except dokumente.DokumenteFehler:
        raise web.HTTPNotFound()
    return web.Response(body=bild, content_type=art, headers={"Cache-Control": "private, max-age=3600"})


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
                return _seite(request, "netzplan.html", modul=s.modul, **_netzplan(request.app))
            if kennung == "dokumente":
                return await _seite_dokumente(request, s.modul)
            if kennung == "tag":
                return await _seite_tag(request, s.modul)
            if kennung == "gesundheit":
                return await _seite_gesundheit(request, s.modul)
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


def app_bauen(einst: Einstellungen, erkundung_ziele: list[str] | None = None, erkundung_ports: tuple[int, ...] | None = None) -> web.Application:
    app = web.Application(middlewares=[kopfzeilen, herkunft, torwaechter], client_max_size=64 * 1024)
    db = Datenbank(einst.datenbank)
    app[K_EINST] = einst
    app[K_DB] = db
    app[K_ANM] = Anmeldung(db, einst.sitzung_tage)
    app[K_ABLAGE] = Ablage(db, einst.daten, einst.hauptschluessel)
    app[K_ERK] = Erkundung(db, einst.docker_url, erkundung_ziele, erkundung_ports)
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
        web.get("/api/erkundung", api_erkundung),
        web.get("/api/netzplan", api_netzplan),
        web.post("/erkundung/start", erkundung_start),
        web.post("/dienst/neu", dienst_neu),
        web.get("/m/dokumente/vorschau/{nr:\\d+}", dokument_vorschau),
        web.post("/dienst/{id}/verbinden", dienst_verbinden),
        web.post("/dienst/{id}/{was:trennen|ignorieren|zeigen}", dienst_zustand),
        web.static("/static", PAKET / "static"),
    ])

    async def aufraeumen(app: web.Application) -> None:
        db.schliessen()

    app.on_cleanup.append(aufraeumen)
    return app
