"""Module „Aufnahme“ und „Finanzen“: lesen einen Notiz-Assistenten – einen eigenen Dienst im Heimnetz,
der Sprachnotizen mit lokaler KI verschriftlicht und einordnet und Kontoumsätze auswertet.

Gelesen wird über seine Schnittstelle (/api/eintraege, /api/finanzen). Die einzige Stelle, an der Homie
etwas abgibt, ist eine neue Sprachaufnahme (/api/aufnahme) – nur wenn der Nutzer selbst aufnimmt.
Homie speichert nichts davon.
"""
from __future__ import annotations

import asyncio
import datetime as dt

import aiohttp

from .gesundheit import deutsch
from .tag import WOCHENTAGE, zone

MONATE = ("Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")
ARTEN = {"aufnahme": "Aufnahme", "fuer_claude": "Auftrag"}
MAX_AUFNAHME = 40_000_000


class AssistentFehler(Exception):
    """Meldung, die dem Nutzer gezeigt werden kann."""


async def _holen(basis: str, token: str, pfad: str) -> dict:
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=25),
                                         headers={"Authorization": f"Bearer {token}"}) as s:
            async with s.get(basis.rstrip("/") + pfad, allow_redirects=False) as r:
                if r.status in (401, 403):
                    raise AssistentFehler("Der Notiz-Assistent lehnt den Schlüssel ab. Bitte im Onboarding trennen und neu verbinden.")
                if r.status != 200:
                    raise AssistentFehler(f"Der Notiz-Assistent antwortet mit Fehler {r.status}.")
                return await r.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as e:
        raise AssistentFehler("Der Notiz-Assistent ist gerade nicht erreichbar.") from e


def _tag_text(tag: str, heute: dt.date) -> str:
    try:
        t = dt.date.fromisoformat(tag[:10])
    except ValueError:
        return tag
    if t == heute:
        return "Heute"
    if t == heute - dt.timedelta(days=1):
        return "Gestern"
    return f"{WOCHENTAGE[t.weekday()]}, {t.day}.{t.month}."


def _datum(tag: str | None) -> str:
    try:
        t = dt.date.fromisoformat((tag or "")[:10])
        return f"{t.day}.{t.month}.{t.year}"
    except ValueError:
        return ""


def _euro(wert, stellen: int = 2) -> str:
    return "–" if not isinstance(wert, (int, float)) else deutsch(wert, stellen) + " €"


async def eintraege(basis: str, token: str, tage: int = 14) -> dict:
    roh = await _holen(basis, token, f"/api/eintraege?tage={tage}")
    namen = {**ARTEN, **(roh.get("kategorien") or {})}
    heute = dt.datetime.now(zone()).date()
    je_tag: dict[str, list[dict]] = {}
    for e in roh.get("eintraege", []):
        daten = e.get("daten") or {}
        if e.get("typ") == "aufnahme":
            continue   # die Aufnahme selbst; ihre Inhalte stehen in den eingeordneten Einträgen
        je_tag.setdefault(e.get("tag", ""), []).append({
            "zeit": (e.get("zeit") or "")[11:16], "art": namen.get(e.get("typ"), e.get("typ", "")), "typ": e.get("typ", ""),
            "text": e.get("text", ""), "antwort": daten.get("antwort") or "",
            "betrag": _euro(daten["betrag_eur"]) if isinstance(daten.get("betrag_eur"), (int, float)) else "",
        })
    return {"tage": [{"name": _tag_text(tag, heute), "eintraege": je_tag[tag]} for tag in sorted(je_tag, reverse=True)],
            "anzahl": sum(len(v) for v in je_tag.values()), "spanne": tage}


async def aufnahme_senden(basis: str, token: str, ton: bytes, art: str, zeit: str) -> str:
    """Gibt eine neue Aufnahme an den Assistenten ab. Antwort: Name, unter dem sie abgelegt wurde."""
    kopf = {"Authorization": f"Bearer {token}", "Content-Type": art or "audio/webm", "X-Aufnahme-Zeit": zeit}
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=150)) as s:
            async with s.post(basis.rstrip("/") + "/api/aufnahme", data=ton, headers=kopf, allow_redirects=False) as r:
                antwort = await r.json(content_type=None)
                if r.status == 200 and antwort.get("ok"):
                    return str(antwort.get("name", ""))
                if r.status == 413:
                    raise AssistentFehler("Die Aufnahme ist leer oder zu lang.")
                raise AssistentFehler(str(antwort.get("fehler") or f"Fehler {r.status}")[:200])
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as e:
        raise AssistentFehler("Der Notiz-Assistent ist gerade nicht erreichbar.") from e


async def finanzen(basis: str, token: str) -> dict:
    roh = await _holen(basis, token, "/api/finanzen")
    budget, prognose = roh.get("budget") or {}, roh.get("prognose") or {}
    bilanz = roh.get("bilanz") or {}
    hoch = max([max(abs(m.get("ein", 0)), abs(m.get("aus", 0))) for m in bilanz.values()] or [0]) or 1
    monate = []
    for kennung in sorted(bilanz)[-6:]:
        m = bilanz[kennung]
        try:
            name = MONATE[int(kennung[5:7]) - 1]
        except (ValueError, IndexError):
            name = kennung
        monate.append({"name": name, "ein": _euro(m.get("ein"), 0), "aus": _euro(abs(m.get("aus", 0)), 0), "netto": _euro(m.get("netto"), 0),
                       "minus": (m.get("netto") or 0) < 0,
                       "anteil_ein": int(100 * abs(m.get("ein", 0)) / hoch), "anteil_aus": int(100 * abs(m.get("aus", 0)) / hoch)})
    return {
        "hinweis": roh.get("hinweis") or "",
        "budget": {
            "frei": _euro(budget.get("frei"), 0), "je_tag": _euro(budget.get("je_tag"), 0), "rest_tage": budget.get("rest_tage"),
            "ausgegeben": _euro(budget.get("ausgegeben"), 0), "spielraum": _euro(budget.get("spielraum"), 0),
            "ampel": budget.get("ampel", ""), "minus": isinstance(budget.get("frei"), (int, float)) and budget["frei"] < 0,
        } if budget else None,
        "konten": [{"name": k.get("name", ""), "bank": k.get("bank", ""), "saldo": _euro(k.get("saldo")),
                    "minus": isinstance(k.get("saldo"), (int, float)) and k["saldo"] < 0, "stand": _datum(k.get("stand"))}
                   for k in roh.get("konten", [])],
        "monate": monate,
        "giro_ende": _euro(prognose.get("giro_ende"), 0) if prognose.get("giro_ende") is not None else "",
        "offen": [{"wer": p.get("wer", ""), "betrag": _euro(abs(p.get("offen", 0)), 0), "tag": p.get("tag")}
                  for p in prognose.get("posten", []) if p.get("offen")],
        "abos": [{"wer": a.get("wer", ""), "betrag": _euro(abs(a.get("je_monat", 0)))} for a in roh.get("abos", [])],
        "letzte": [{"tag": _datum(u.get("tag"))[:-4], "wer": u.get("wer", ""), "zweck": u.get("zweck", ""), "konto": u.get("konto", ""),
                    "betrag": _euro(u.get("betrag")), "minus": (u.get("betrag") or 0) < 0} for u in roh.get("letzte", [])],
    }
