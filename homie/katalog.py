"""Katalog bekannter Dienste: woran Homie sie erkennt, was sie zum Verbinden brauchen, was sie freischalten.

Ein neuer Dienst = ein Eintrag hier. Erkannt wird nur durch Lesen: Homie ruft eine Seite des Dienstes
ab und sucht darin nach einem Kennzeichen. Es wird nichts angemeldet, geändert oder geschrieben.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Feld:
    name: str                 # Name in der verschlüsselten Ablage
    titel: str                # Beschriftung im Formular
    geheim: bool = True
    hinweis: str = ""         # wo man den Wert im Dienst findet


@dataclass(frozen=True)
class Eintrag:
    id: str
    art: str                  # Art des Dienstes – darauf beziehen sich die Module
    name: str
    beschreibung: str
    ports: tuple[int, ...]
    muster: tuple[str, ...]   # eines dieser Kennzeichen (klein geschrieben) muss in der Antwort stehen
    pfad: str = "/"           # Seite, die zum Erkennen gelesen wird
    felder: tuple[Feld, ...] = ()
    schaltet_frei: str = ""
    farbe: str = "#8b7cff"


_BESCHRIFTUNG = "Zugriffstoken"

KATALOG: tuple[Eintrag, ...] = (
    Eintrag(
        "proxmox", "virtualisierung", "Proxmox VE", "Server, auf dem virtuelle Maschinen laufen",
        (8006,), ("proxmox virtual environment",),
        felder=(
            Feld("token-id", "Token-ID", geheim=False, hinweis="Form: benutzer@bereich!name – Datacenter → Permissions → API Tokens"),
            Feld("token", "Token-Geheimnis", hinweis="wird beim Anlegen des Tokens einmal angezeigt"),
        ),
        schaltet_frei="Netzplan mit VMs; später: fehlende Dienste anlegen", farbe="#c77dff",
    ),
    Eintrag(
        "homeassistant", "homeassistant", "Home Assistant", "Smart-Home-Zentrale",
        (8123, 80), ("<title>home assistant</title>",),
        felder=(Feld("token", _BESCHRIFTUNG, hinweis="Profil → Sicherheit → Langlebige Zugriffstoken"),),
        schaltet_frei="Gesundheit", farbe="#3ddc97",
    ),
    Eintrag(
        "ollama", "ki-lokal", "Ollama", "Lokale KI für Text und Sprache",
        (11434,), ("ollama is running",), schaltet_frei="Aufnahme", farbe="#2fd4c4",
    ),
    Eintrag(
        "paperless", "dokumente", "Paperless-ngx", "Dokumentenarchiv",
        (8000, 8010), ("paperless-ngx",),
        felder=(Feld("token", "API-Token", hinweis="Mein Profil → API-Token; am besten ein Konto, das nur lesen darf"),),
        schaltet_frei="Dokumente", farbe="#5b9dff",
    ),
    Eintrag(
        "nextcloud", "kalender", "Nextcloud", "Kalender, Aufgaben und Dateien",
        (80, 443, 8080), ('"productname":"nextcloud"',), pfad="/status.php",
        felder=(
            Feld("benutzer", "Benutzername", geheim=False),
            Feld("app-passwort", "App-Passwort", hinweis="Einstellungen → Sicherheit → Geräte & Sitzungen → Neues App-Passwort"),
        ),
        schaltet_frei="Mein Tag", farbe="#ff5fa2",
    ),
    Eintrag(
        "firefly", "finanzen", "Firefly III", "Haushaltsbuch",
        (8080, 80), ("firefly iii",),
        felder=(Feld("token", "Persönlicher Zugriffstoken", hinweis="Optionen → Profil → OAuth → Persönliche Zugriffstoken"),),
        schaltet_frei="Finanzen", farbe="#ffc46b",
    ),
    Eintrag(
        "portainer", "docker-verwaltung", "Portainer", "Verwaltung für Docker-Container",
        (9000, 9443), ("<title>portainer</title>", "portainer.io"),
        felder=(Feld("token", "API-Schlüssel", hinweis="Mein Konto → Access tokens"),),
        schaltet_frei="Netzplan mit Stacks", farbe="#5b9dff",
    ),
    Eintrag(
        "immich", "fotos", "Immich", "Fotosammlung",
        (2283,), ('"res":"pong"',), pfad="/api/server/ping",
        felder=(Feld("token", "API-Schlüssel", hinweis="Kontoeinstellungen → API-Schlüssel"),), farbe="#ff8a6b",
    ),
    Eintrag("jellyfin", "medien", "Jellyfin", "Filme, Serien und Musik", (8096,), ('"productname":"jellyfin',), pfad="/System/Info/Public", farbe="#a36bff"),
    Eintrag("plex", "medien", "Plex", "Filme, Serien und Musik", (32400,), ("<mediacontainer",), pfad="/identity", farbe="#ffc46b"),
    Eintrag("pihole", "dns", "Pi-hole", "Werbefilter für das Heimnetz", (80, 8080), ("pi-hole",), pfad="/admin/", farbe="#ff6b8b"),
    Eintrag("adguard", "dns", "AdGuard Home", "Werbefilter für das Heimnetz", (3000, 80), ("adguard home",), farbe="#3ddc97"),
    Eintrag("npm", "proxy", "Nginx Proxy Manager", "Leitet Namen auf Dienste weiter", (81,), ("nginx proxy manager",), farbe="#ff8a6b"),
    Eintrag("vaultwarden", "passwoerter", "Vaultwarden", "Passwort-Tresor", (80, 8085, 8080), ("vaultwarden",), farbe="#5b9dff"),
    Eintrag("unifi", "router", "UniFi", "Router und Netzwerkverwaltung", (443, 8443), ("unifi",), farbe="#5b9dff"),
    Eintrag("fritzbox", "router", "FRITZ!Box", "Router", (80, 443), ("fritz!box",), farbe="#ff6b8b"),
)

# Ports ohne Webseite: hier genügt, dass der Port offen ist.
NUR_PORT: dict[int, tuple[str, str]] = {
    53: ("dns", "DNS-Server"),
    445: ("freigabe", "Dateifreigabe (SMB)"),
    1883: ("mqtt", "MQTT-Broker"),
}

# Weitere übliche Web-Ports, auf denen unbekannte Seiten mit ihrem Titel in den Netzplan kommen.
WEB_PORTS = (80, 443, 3000, 5000, 5001, 8080, 8081, 8443, 9090)
TLS_ZUERST = (443, 8006, 8443, 9443, 5001)


def alle_ports() -> tuple[int, ...]:
    ports = set(WEB_PORTS) | set(NUR_PORT)
    for e in KATALOG:
        ports.update(e.ports)
    return tuple(sorted(ports))


def eintrag(kennung: str) -> Eintrag | None:
    return next((e for e in KATALOG if e.id == kennung), None)
