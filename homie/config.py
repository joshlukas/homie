"""Einstellungen aus der Umgebung. Alles hat einen Standardwert – Homie startet ohne Vorkonfiguration."""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path

VERSION = "0.19.4"
PAKET = Path(__file__).resolve().parent


def _an(wert: str | None, standard: bool) -> bool:
    if wert is None or wert.strip() == "":
        return standard
    return wert.strip().lower() not in ("0", "aus", "nein", "false", "off", "no")


@dataclass(frozen=True)
class Einstellungen:
    daten: Path            # Datenordner: alles Private liegt nur hier
    bind: str
    port: int
    sitzung_tage: int
    hauptschluessel: str   # optional: Hauptschlüssel von außen statt Datei im Datenordner
    docker_url: str        # Adresse des nur lesenden Docker-Zwischendienstes ("" = aus)
    beispiele: Path        # Beispielzustand für das Onboarding (keine echten Daten)
    yamtrack: str = ""     # Pfad zur nur lesbar eingehängten Yamtrack-Datenbank (freiwillig)
    yamtrack_helfer: str = ""   # Adresse des Helfers, der Gesehenes in Yamtrack einträgt ("" = aus)
    gedaechtnis: str = ""       # Adresse des Gedächtnis-Dienstes ("" = derselbe Rechner wie der Notiz-Assistent, Port 8097)
    bilder: Path = Path("/bilder")   # Ordner für das „Bild des Tages“ (freiwillig; leer oder fehlend = kein Bild)
    proxys: tuple = ()          # Netze des eigenen Reverse Proxys: nur deren X-Forwarded-For wird geglaubt (siehe _proxys)

    @property
    def seiten(self) -> Path:
        """Eigene Seiten des Nutzers (HTML-Dateien), die als zusätzliche Tabs erscheinen."""
        return self.daten / "seiten"

    @property
    def datenbank(self) -> Path:
        return self.daten / "homie.sqlite"


def _proxys(wert: str) -> tuple:
    """HOMIE_PROXY: Adressen oder Netze des Reverse Proxys, durch Kommas getrennt. Unlesbares wird übergangen,
    damit ein Tippfehler Homie nicht am Start hindert (dann gilt die Bremse wie ohne Proxy für alle zugleich)."""
    netze = []
    for teil in wert.split(","):
        try:
            netze.append(ipaddress.ip_network(teil.strip(), strict=False))
        except ValueError:
            pass
    return tuple(netze)


def laden(umgebung: dict[str, str] | None = None) -> Einstellungen:
    u = os.environ if umgebung is None else umgebung
    docker_an = _an(u.get("HOMIE_DOCKER_LESEN"), True)
    docker_url = u.get("HOMIE_DOCKER_URL", "http://127.0.0.1:23750").strip().rstrip("/")
    return Einstellungen(
        daten=Path(u.get("HOMIE_DATA", "/data")),
        bind=u.get("HOMIE_BIND", "0.0.0.0"),
        port=int(u.get("HOMIE_PORT", "8090")),
        sitzung_tage=int(u.get("HOMIE_SITZUNG_TAGE", "30")),
        hauptschluessel=u.get("HOMIE_MASTER_KEY", ""),
        docker_url=docker_url if docker_an else "",
        beispiele=Path(u.get("HOMIE_BEISPIELE", PAKET.parent / "config" / "beispiel-dienste.json")),
        yamtrack=u.get("HOMIE_YAMTRACK_DB", "/yamtrack/db.sqlite3"),
        bilder=Path(u.get("HOMIE_BILDER", "/bilder")),
        gedaechtnis=u.get("HOMIE_GEDAECHTNIS_URL", "").strip().rstrip("/"),
        proxys=_proxys(u.get("HOMIE_PROXY", "")),
        yamtrack_helfer=u.get("HOMIE_YAMTRACK_URL", "http://127.0.0.1:23751").strip().rstrip("/") if _an(u.get("HOMIE_YAMTRACK_SCHREIBEN"), False) else "",
    )
