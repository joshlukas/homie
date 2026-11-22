# Hinweise für helfende Agenten

Homie braucht keinen Agenten: Installation und Einrichtung laufen über die README und das Dashboard. Wenn dich jemand trotzdem um Hilfe bittet (Claude Code, Codex o. Ä.), gilt:

## Reihenfolge

1. **Erst nur lesen.** Sieh dir an, was da ist: README, `docker-compose.yml`, laufende Container, Protokolle. Ändere nichts.
2. **Plan zeigen.** Sag in einfachen Worten, was du tun willst, was sich dadurch ändert und wie es rückgängig geht. Warte auf ein Ja.
3. **Dann bauen.** Nur das Besprochene. Danach prüfen und ehrlich berichten, was geprüft wurde und was nicht.

## Schlüssel und Privates

- **Keine Schlüssel im Chat.** Frag nie nach Passwörtern oder Tokens und gib nie welche aus. Der Mensch trägt sie selbst im Dashboard oder in Portainer ein.
- Lies den Datenordner (`/data`, Volume `homie-daten`) nicht aus und zeig seinen Inhalt nicht an. `docker inspect` und `docker compose config` können Geheimnisse anzeigen – nur gefiltert bzw. mit `-q` verwenden.
- Ins Repository gehören nur Programm und Beispielkonfiguration: keine echten Adressen, Namen, Geräte, Schlüssel. Vor jedem Push `scripts/privat-pruefung.sh` ausführen.

## Grenzen

- Homie bleibt im Heimnetz. Keine Portfreigaben, keine Tunnel, keine Cloud-Dienste ohne ausdrücklichen Auftrag.
- Bestehende Dienste im Netz werden nur gelesen. Anlegen, Ändern oder Löschen von VMs, Containern und Daten nur nach bestätigtem Plan.
- Der Docker-Zugriff bleibt lesend und über den Zwischendienst `docker-lesen`. Den Docker-Socket nicht direkt in `homie` einhängen.

## Aufbau des Programms

| Datei | Aufgabe |
|---|---|
| `homie/server.py` | Webserver, Seiten, API; der „Torwächter“ lässt ohne Anmeldung nichts durch |
| `homie/anmeldung.py` | Konto, Passwort-Prüfwert (scrypt), Sitzungen |
| `homie/ablage.py` | verschlüsselte Ablage für Schlüssel (AES-256-GCM) |
| `homie/module.py` | Modul-Register: was jedes Modul braucht |
| `homie/katalog.py` | bekannte Dienste: Erkennungsmerkmal, nötige Schlüssel, was sie freischalten |
| `homie/erkundung.py` | Erkundung des Heimnetzes, nur lesend |
| `homie/verbinden.py` | Schlüssel beim Dienst prüfen, bevor er abgelegt wird |
| `homie/dokumente.py` | Modul Dokumente: liest Paperless-ngx (nur lesend, nichts wird gespeichert) |
| `homie/db.py`, `homie/config.py` | Datenbank im Datenordner, Einstellungen |
| `tests/` | `python -m unittest discover -s tests -v` muss vor jeder Änderung und danach grün sein |

Neue Seiten und API-Wege sind automatisch geschützt. Öffentlich sind nur die in `OEFFENTLICH` genannten Wege – diese Liste nicht erweitern.
