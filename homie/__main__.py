"""Start: `python -m homie`. Hilfe bei vergessenem Passwort: `python -m homie passwort-zuruecksetzen`."""
from __future__ import annotations

import sys

from aiohttp import web

from .anmeldung import Anmeldung
from .config import VERSION, laden
from .db import Datenbank
from .server import app_bauen


def main() -> int:
    einst = laden()
    befehl = sys.argv[1] if len(sys.argv) > 1 else "start"
    if befehl == "passwort-zuruecksetzen":
        Anmeldung(Datenbank(einst.datenbank)).konto_loeschen()
        print("Konto entfernt. Beim nächsten Aufruf im Browser legst du ein neues Passwort an. Daten und Schlüssel bleiben.")
        return 0
    if befehl != "start":
        print("Unbekannter Befehl. Möglich: start, passwort-zuruecksetzen", file=sys.stderr)
        return 2
    print(f"Homie {VERSION} – Datenordner {einst.daten}, Port {einst.port}", flush=True)
    web.run_app(app_bauen(einst), host=einst.bind, port=einst.port, print=None, access_log=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
