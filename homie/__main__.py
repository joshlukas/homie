"""Start: `python -m homie`.

Weitere Befehle (im Container: `docker exec -i homie python -m homie …`):
  passwort-zuruecksetzen             Konto entfernen; im Browser legst du ein neues Passwort an.
  einstellung ich NAME               Dein Name, so wie er bei den geteilten Ausgaben steht (für „du schuldest / du bekommst“).
  verbinden NAME FELD [FELD …]       Einen Dienst ohne Browser verbinden. Die Werte der Felder werden zeilenweise
        [--adresse URL]              von der Eingabe gelesen – nie als Argument, damit sie in keiner Befehlsliste stehen.
  yamtrack-helfer                    Der kleine Helfer, der Gesehenes in Yamtrack einträgt (eigener Dienst in der Stackdatei).
"""
from __future__ import annotations

import asyncio
import json
import sys

from aiohttp import web

from . import katalog, module, verbinden
from .ablage import Ablage
from .anmeldung import Anmeldung
from .config import VERSION, laden
from .db import Datenbank
from .erkundung import von_hand
from .server import app_bauen


async def dienst_verbinden(db: Datenbank, ablage: Ablage, name: str, felder: list[str], werte: list[str], adresse: str = "") -> tuple[bool, str]:
    """Prüft die Schlüssel beim Dienst und legt sie verschlüsselt ab. Gibt nie einen Schlüssel aus."""
    if adresse:
        hinzu, meldung = await von_hand(db, adresse)
        if not hinzu and "schon eingetragen" not in meldung:
            return False, meldung
    treffer = [z for z in db.alle("SELECT id, name, adresse, details FROM dienst WHERE zustand != 'ignoriert'")
               if z["name"].lower() == name.lower() and (not adresse or z["adresse"].rstrip("/") == adresse.rstrip("/") or "://" not in adresse)]
    if len(treffer) != 1:
        return False, f"Unter dem Namen „{name}“ gibt es {len(treffer)} Dienste – erwartet wird genau einer."
    d = treffer[0]
    e = katalog.eintrag(json.loads(d["details"]).get("kennung", ""))
    if e is None or [f.name for f in e.felder] != felder:
        erwartet = ", ".join(f.name for f in e.felder) if e else "?"
        return False, f"{name} erwartet die Felder: {erwartet or 'keine'}."
    if len(werte) != len(felder) or any(not w for w in werte):
        return False, "Zu jedem Feld wird genau eine nicht leere Zeile erwartet."
    in_ordnung, meldung = await verbinden.pruefen(e, d["adresse"], dict(zip(felder, werte)))
    if not in_ordnung:
        return False, meldung
    for feld, wert in zip(felder, werte):
        ablage.setzen(module.schluesselname(d["id"], feld), wert)
    db.ausfuehren("UPDATE dienst SET zustand='verbunden' WHERE id=?", (d["id"],))
    return True, f"{name}: {meldung}"


def main() -> int:
    einst = laden()
    befehl = sys.argv[1] if len(sys.argv) > 1 else "start"
    if befehl == "passwort-zuruecksetzen":
        Anmeldung(Datenbank(einst.datenbank)).konto_loeschen()
        print("Konto entfernt. Beim nächsten Aufruf im Browser legst du ein neues Passwort an. Daten und Schlüssel bleiben.")
        return 0
    if befehl == "verbinden":
        teile = sys.argv[2:]
        adresse = ""
        if "--adresse" in teile:
            stelle = teile.index("--adresse")
            adresse, teile = (teile[stelle + 1] if stelle + 1 < len(teile) else ""), teile[:stelle] + teile[stelle + 2:]
        if not teile:
            print("Aufruf: verbinden NAME FELD [FELD …] [--adresse URL]   (Werte zeilenweise über die Eingabe)", file=sys.stderr)
            return 2
        name, felder = teile[0], teile[1:]
        werte = [zeile.strip() for zeile in sys.stdin.read().splitlines() if zeile.strip()] if felder else []
        db = Datenbank(einst.datenbank)
        in_ordnung, meldung = asyncio.run(dienst_verbinden(db, Ablage(db, einst.daten, einst.hauptschluessel), name, felder, werte, adresse))
        print(meldung, file=sys.stdout if in_ordnung else sys.stderr)
        return 0 if in_ordnung else 1
    if befehl == "einstellung":
        if len(sys.argv) != 4 or sys.argv[2] not in ("ich",):
            print("Aufruf: einstellung ich NAME   (dein Name, so wie er bei den geteilten Ausgaben steht)", file=sys.stderr)
            return 2
        Datenbank(einst.datenbank).ausfuehren("INSERT INTO merk (name, wert) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET wert=excluded.wert",
                                              (sys.argv[2], sys.argv[3][:60]))
        print("Gespeichert.")
        return 0
    if befehl == "yamtrack-helfer":
        import os

        from . import yamtrack
        port = int(os.environ.get("HOMIE_YAMTRACK_PORT", "23751"))
        print(f"Homie {VERSION} – Yamtrack-Helfer auf 127.0.0.1:{port}, Container „{yamtrack.CONTAINER}“", flush=True)
        web.run_app(yamtrack.helfer_app(), host="127.0.0.1", port=port, print=None, access_log=None)
        return 0
    if befehl != "start":
        print("Unbekannter Befehl. Möglich: start, passwort-zuruecksetzen, verbinden, einstellung, yamtrack-helfer", file=sys.stderr)
        return 2
    print(f"Homie {VERSION} – Datenordner {einst.daten}, Port {einst.port}", flush=True)
    web.run_app(app_bauen(einst), host=einst.bind, port=einst.port, print=None, access_log=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
