"""Verbindung zum Notiz-Assistenten – einem eigenen Dienst im Heimnetz, der Sprachnotizen mit lokaler KI
verschriftlicht und einordnet und Kontoumsätze auswertet. Genutzt von den Modulen Aufnahme, Finanzen, Gesundheit
(langer Verlauf, Trainings) und Assistent (Profil, KI-Kosten).

Lesen: /api/finanzen, /api/cospend, /api/gesundheit, /api/profil, /api/claude.
Abgeben – immer nur auf eine Handlung des Nutzers hin:
  - eine Aufnahme, ein Foto oder eine getippte Notiz (/api/aufnahme),
  - einen Kontoauszug (/api/finanzen/import),
  - sein Ja oder Nein zu einem Vorschlag (…/entscheid – das ändert Daten im Assistenten),
  - die Lieferung der Gesundheits-App vom Handy, unverändert durchgereicht (/api/health-webhook).
Homie speichert nichts davon. Die Funktionen bereiten die Antworten fertig für die Vorlagen auf (Beträge als Text).
"""
from __future__ import annotations

import asyncio
import datetime as dt

import aiohttp

from .gesundheit import deutsch
from .tag import zone

WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
MONATE = ("Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")
MAX_AUFNAHME = 40_000_000
MAX_AUSZUG = 5_000_000


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


def _objekt(antwort) -> dict:
    """Antworten, die kein JSON-Objekt sind (null, Liste, Zahl), wie eine leere Antwort behandeln:
    Dann greift die normale Fehlermeldung mit dem Status, statt dass Homie an antwort.get(...) scheitert."""
    return antwort if isinstance(antwort, dict) else {}


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


def _betrag(wert) -> float | None:
    """Betrag ohne Vorzeichen; None (wird als „–“ gezeigt), wenn keine Zahl ankommt."""
    return abs(wert) if isinstance(wert, (int, float)) else None


def _einmalig(budget: dict) -> dict | None:
    """Ausgaben, die der Nutzer als einmalig benannt hat: Sie sind aus „ausgegeben“ und „frei“ herausgerechnet
    und werden nur genannt, damit die Zahlen nachvollziehbar bleiben. None, wenn es keine gibt."""
    liste = budget.get("einmalig_liste")
    posten = [e for e in liste if isinstance(e, dict) and isinstance(e.get("betrag"), (int, float))] if isinstance(liste, list) else []
    if not posten:
        return None
    summe = budget.get("einmalig")
    if not isinstance(summe, (int, float)):
        summe = sum(abs(e["betrag"]) for e in posten)
    return {"summe": _euro(abs(summe), 0), "posten": [{"betrag": _euro(abs(e["betrag"]), 0), "tag": _datum(e.get("tag") if isinstance(e.get("tag"), str) else "")[:-4],
                                                      "wer": str(e.get("wer") or "")[:80], "grund": str(e.get("grund") or "")[:160]} for e in posten[:10]]}


async def aufnahme_senden(basis: str, token: str, ton: bytes, art: str, zeit: str) -> str:
    """Gibt eine neue Aufnahme an den Assistenten ab. Antwort: Name, unter dem sie abgelegt wurde."""
    kopf = {"Authorization": f"Bearer {token}", "Content-Type": art or "audio/webm", "X-Aufnahme-Zeit": zeit}
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=150)) as s:
            async with s.post(basis.rstrip("/") + "/api/aufnahme", data=ton, headers=kopf, allow_redirects=False) as r:
                antwort = _objekt(await r.json(content_type=None))
                if r.status == 200 and antwort.get("ok"):
                    return str(antwort.get("name", ""))
                if r.status == 413:
                    raise AssistentFehler("Die Aufnahme ist leer oder zu groß.")
                raise AssistentFehler(str(antwort.get("fehler") or f"Fehler {r.status}")[:200])
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as e:
        raise AssistentFehler("Der Notiz-Assistent ist gerade nicht erreichbar.") from e


async def auszug_senden(basis: str, token: str, inhalt: bytes) -> dict:
    """Gibt einen Kontoauszug (CSV oder Excel) an den Assistenten ab. Antwort: Konto, gelesene und neue Zeilen."""
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=60)) as s:
            async with s.post(basis.rstrip("/") + "/api/finanzen/import", data=inhalt, allow_redirects=False,
                              headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"}) as r:
                antwort = _objekt(await r.json(content_type=None))
                if r.status == 200 and antwort.get("ok"):
                    return {"konto": str(antwort.get("konto", ""))[:80], "zeilen": int(antwort.get("zeilen") or 0), "neu": int(antwort.get("neu") or 0)}
                if "Format" in str(antwort.get("fehler", "")):
                    raise AssistentFehler("Das Format der Datei wurde nicht erkannt. Erwartet wird der Umsatz-Export deiner Bank (CSV oder Excel).")
                raise AssistentFehler(str(antwort.get("fehler") or f"Fehler {r.status}")[:200])
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError, TypeError) as e:
        raise AssistentFehler("Der Notiz-Assistent ist gerade nicht erreichbar.") from e


async def finanzen(basis: str, token: str) -> dict:
    """Alles für die Seite Finanzen: budget (Monatsverlauf, einmalige Ausgaben), konten, monate (letzte sechs mit
    Balkenanteilen), offen (erwartete Abbuchungen), abos, letzte Umsätze, vorschlaege (für die gemeinsame Abrechnung)
    und geteilt (siehe geteilt). Beträge kommen als fertiger Text („1.990 €“), „–“ wenn eine Zahl fehlt."""
    roh, teilen = await asyncio.gather(_holen(basis, token, "/api/finanzen"), geteilt(basis, token))
    offen = roh.get("cospend_offen") or {}
    budget, prognose = roh.get("budget") or {}, roh.get("prognose") or {}
    bilanz = roh.get("bilanz") or {}
    # Ein Monat ohne Wert kommt als null an; m.get("ein", 0) gäbe dann None zurück, darum hier immer eine Zahl.
    zahl = lambda w: w if isinstance(w, (int, float)) else 0
    bilanz = {k: m for k, m in bilanz.items() if isinstance(m, dict)}
    hoch = max([max(abs(zahl(m.get("ein"))), abs(zahl(m.get("aus")))) for m in bilanz.values()] or [0]) or 1
    monate = []
    for kennung in sorted(bilanz)[-6:]:
        m = bilanz[kennung]
        ein, aus, netto = zahl(m.get("ein")), zahl(m.get("aus")), zahl(m.get("netto"))
        try:
            name = MONATE[int(kennung[5:7]) - 1]
        except (ValueError, IndexError):
            name = kennung
        monate.append({"name": name, "ein": _euro(m.get("ein"), 0), "aus": _euro(abs(aus), 0), "netto": _euro(m.get("netto"), 0),
                       "minus": netto < 0, "anteil_ein": int(100 * abs(ein) / hoch), "anteil_aus": int(100 * abs(aus) / hoch)})
    return {
        "geteilt": teilen,
        "vorschlaege": [{"id": v.get("id", ""), "text": f"{_datum(v.get('tag'))[:-4]} {v.get('name') or v.get('wer', '')}", "betrag": _euro(v.get("betrag"))}
                        for v in offen.get("liste", [])] if isinstance(offen.get("liste"), list) else [],
        "hinweis": roh.get("hinweis") or "",
        "budget": {
            "frei": _euro(budget.get("frei"), 0), "je_tag": _euro(budget.get("je_tag"), 0), "rest_tage": budget.get("rest_tage"),
            "ausgegeben": _euro(budget.get("ausgegeben"), 0), "spielraum": _euro(budget.get("spielraum"), 0),
            "ampel": budget.get("ampel", ""), "minus": isinstance(budget.get("frei"), (int, float)) and budget["frei"] < 0,
            "einmalig": _einmalig(budget),
        } if budget else None,
        "konten": [{"name": k.get("name", ""), "bank": k.get("bank", ""), "saldo": _euro(k.get("saldo")),
                    "minus": isinstance(k.get("saldo"), (int, float)) and k["saldo"] < 0, "stand": _datum(k.get("stand"))}
                   for k in roh.get("konten", [])],
        "monate": monate,
        "giro_ende": _euro(prognose.get("giro_ende"), 0) if prognose.get("giro_ende") is not None else "",
        "offen": [{"wer": p.get("wer", ""), "betrag": _euro(abs(p.get("offen", 0)), 0), "tag": p.get("tag")}
                  for p in prognose.get("posten", []) if p.get("offen")],
        "abos": [{"wer": a.get("wer", ""), "betrag": _euro(_betrag(a.get("je_monat")))} for a in roh.get("abos", [])],
        "letzte": [{"tag": _datum(u.get("tag"))[:-4], "wer": u.get("wer", ""), "zweck": u.get("zweck", ""), "konto": u.get("konto", ""),
                    "betrag": _euro(u.get("betrag")), "minus": (u.get("betrag") or 0) < 0} for u in roh.get("letzte", [])],
    }


# ---------- Gesundheitsverlauf und Trainings, geteilte Ausgaben, Profil, KI-Kosten ----------

async def _versuchen(basis: str, token: str, pfad: str) -> dict | None:
    """Wie _holen, aber ein Teil, der gerade nicht geht, soll die Seite nicht mitreißen."""
    try:
        return await _holen(basis, token, pfad)
    except AssistentFehler:
        return None


async def gesundheit(basis: str, token: str, tage: int = 30) -> dict | None:
    """Langer Verlauf für die Seite Gesundheit: tage (Schritte je Tag mit Balkenanteil), schnitt, training (letzte
    Einheiten), vorschlaege (erkannte Trainings zum Bestätigen). None, wenn der Assistent nicht antwortet."""
    roh = await _versuchen(basis, token, f"/api/gesundheit?tage={tage}")
    if roh is None:
        return None
    heute = dt.datetime.now(zone()).date()
    werte = {t.get("tag"): t for t in roh.get("tage", [])}
    reihe = [heute - dt.timedelta(days=tage - 1 - i) for i in range(tage)]
    schritte = [werte.get(t.isoformat(), {}).get("schritte") for t in reihe]
    hoch = max([s for s in schritte if s] or [1])
    mit = [s for s in schritte if s]
    return {
        "tage": [{"name": f"{t.day}.{t.month}.", "wert": deutsch(s, 0) if s else "–", "anteil": int(100 * s / hoch) if s else 0,
                  "woche": t.weekday() == 0} for t, s in zip(reihe, schritte)],
        "schnitt": deutsch(sum(mit) / len(mit), 0) if mit else "–", "spanne": tage, "stand": _datum(roh.get("stand")),
        "training": [{
            "tag": _tag_text(t.get("tag", ""), heute), "titel": t.get("titel") or t.get("art") or "Training", "art": t.get("art", ""),
            "dauer": f"{t['dauer_min']} Min." if t.get("dauer_min") else "",
            "strecke": f"{deutsch(t['distanz_m'] / 1000, 1)} km" if t.get("distanz_m") else "",
            "geschaetzt": t.get("quelle") in ("notiz", "erkannt"),
        } for t in roh.get("training", [])],
        "vorschlaege": [{"id": v.get("id", ""), "text": f"{_tag_text(v.get('tag', ''), heute)}, {v.get('von', '')}–{v.get('bis', '')} Uhr: "
                         f"{v.get('dauer_min', '?')} Minuten zügig gegangen ({deutsch(v.get('schritte', 0), 0)} Schritte)"}
                        for v in roh.get("training_vorschlaege", [])],
    }


async def geteilt(basis: str, token: str) -> dict | None:
    """Die gemeinsame Haushaltskasse (Cospend) der letzten 30 Tage: salden je Person, summe, arten (nach Kategorie)
    und letzte Ausgaben. None, wenn der Assistent nicht antwortet."""
    roh = await _versuchen(basis, token, "/api/cospend?tage=30")
    if roh is None:
        return None
    zeitraum = roh.get("zeitraum") or {}
    arten = sorted((zeitraum.get("nach_kategorie") or {}).items(), key=lambda x: -x[1])
    hoch = max([b for _, b in arten] or [1]) or 1
    return {
        "projekt": roh.get("projekt", ""),
        "salden": [{"wer": wer, "betrag": _euro(b), "minus": isinstance(b, (int, float)) and b < 0} for wer, b in (roh.get("saldo") or {}).items()],
        "summe": _euro(zeitraum.get("summe"), 0), "anzahl": zeitraum.get("anzahl") or 0,
        "arten": [{"name": n, "betrag": _euro(b, 0), "anteil": int(100 * b / hoch)} for n, b in arten],
        "letzte": [{"tag": _datum(u.get("tag"))[:-4], "was": u.get("was", ""), "wer": u.get("zahler", ""), "art": u.get("kategorie", ""),
                    "betrag": _euro(u.get("betrag"))} for u in roh.get("letzte", [])],
    }


async def profil_und_nutzung(basis: str, token: str) -> dict:
    """Für Blueprint › Assistent: profil (Text und Änderungsvorschläge) und nutzung (KI-Kosten heute, je Tag, je Modell).
    Fehlt einer der beiden Teile, ist er None; fehlen beide, gibt es eine Meldung."""
    profil, nutzung = await asyncio.gather(_versuchen(basis, token, "/api/profil"), _versuchen(basis, token, "/api/claude"))
    if profil is None and nutzung is None:
        raise AssistentFehler("Der Notiz-Assistent ist gerade nicht erreichbar.")
    ergebnis: dict = {"profil": None, "nutzung": None}
    if profil is not None:
        ergebnis["profil"] = {"text": profil.get("profil", ""), "vorschlaege": [{
            "id": v.get("id"), "abschnitt": v.get("abschnitt", ""), "art": v.get("art", ""), "alt": v.get("alt") or "", "neu": v.get("neu") or "",
            "grund": v.get("begruendung") or ""} for v in profil.get("vorschlaege", [])]}
    if nutzung is not None:
        tage = nutzung.get("tage", [])
        hoch = max([t.get("usd") or 0 for t in tage] or [0]) or 1
        dollar = lambda w: "–" if not isinstance(w, (int, float)) else deutsch(w, 2) + " $"
        ergebnis["nutzung"] = {
            "aktiv": bool(nutzung.get("aktiv")), "heute": dollar((nutzung.get("heute") or {}).get("usd")),
            "aufrufe": (nutzung.get("heute") or {}).get("aufrufe") or 0, "limit": dollar(nutzung.get("tageslimit")),
            "guthaben": dollar(nutzung.get("guthaben")) if nutzung.get("guthaben") is not None else "",
            "tage": [{"name": _datum(t.get("tag"))[:-4], "wert": dollar(t.get("usd")), "anteil": int(100 * (t.get("usd") or 0) / hoch)} for t in tage[-14:]],
            "modelle": [{"name": n, "betrag": dollar(m.get("usd")), "aufrufe": m.get("aufrufe") or 0} for n, m in (nutzung.get("modelle_30_tage") or {}).items()],
        }
    return ergebnis


ENTSCHEID_WEGE = {"finanzen": "/api/finanzen/entscheid", "training": "/api/training/entscheid", "profil": "/api/profil/entscheid",
                  "betrag": "/api/betrag/entscheid"}


async def entscheid(basis: str, token: str, art: str, kennung: str, annehmen: bool) -> tuple[bool, str]:
    """Gibt die Entscheidung des Nutzers zu einem Vorschlag an den Assistenten weiter. Das ändert dort Daten."""
    if art not in ENTSCHEID_WEGE:
        return False, "Diese Art von Vorschlag gibt es nicht."
    sende = {"id": int(kennung) if art in ("profil", "betrag") and kennung.isdigit() else kennung, "annehmen": annehmen}
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=40),
                                         headers={"Authorization": f"Bearer {token}"}) as s:
            async with s.post(basis.rstrip("/") + ENTSCHEID_WEGE[art], json=sende, allow_redirects=False) as r:
                antwort = _objekt(await r.json(content_type=None))
                if r.status == 200 and antwort.get("ok", True) is not False:
                    return True, "Übernommen." if annehmen else "Abgelehnt."
                return False, str(antwort.get("fehler") or f"Fehler {r.status}")[:200]
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
        return False, "Der Notiz-Assistent ist gerade nicht erreichbar."


MAX_LIEFERUNG = 12_000_000


async def lieferung_weitergeben(basis: str, inhalt: bytes, signatur: str, ausweis: str) -> tuple[int, bytes]:
    """Reicht eine Lieferung der Gesundheits-App vom Handy unverändert an den Assistenten weiter.

    Homie kennt das Geheimnis der App nicht und braucht es nicht: Die App unterschreibt ihre Lieferung,
    und der Assistent prüft die Unterschrift. Homie ist nur der Briefkasten."""
    kopf = {"Content-Type": "application/json"}
    if signatur:
        kopf["X-Signature"] = signatur
    if ausweis:
        kopf["Authorization"] = ausweis
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False), timeout=aiohttp.ClientTimeout(total=45)) as s:
            async with s.post(basis.rstrip("/") + "/api/health-webhook", data=inhalt, headers=kopf, allow_redirects=False) as r:
                return r.status, await r.read()
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return 502, b'{"fehler": "Der Notiz-Assistent ist gerade nicht erreichbar."}'
