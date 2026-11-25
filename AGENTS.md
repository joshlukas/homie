# Hinweise für helfende Agenten

Homie braucht keinen Agenten: Installation und Einrichtung laufen über die README und das Dashboard. Wenn dich jemand trotzdem um Hilfe bittet (Claude Code, Codex o. Ä.), gilt:

## Reihenfolge

1. **Erst nur lesen.** Sieh dir an, was da ist: README, `docker-compose.yml`, laufende Container, Protokolle. Ändere nichts.
2. **Plan zeigen.** Sag in einfachen Worten, was du tun willst, was sich dadurch ändert und wie es rückgängig geht. Warte auf ein Ja.
3. **Dann bauen.** Nur das Besprochene. Danach prüfen und ehrlich berichten, was geprüft wurde und was nicht.

## Schnittstelle für Agenten

Der Mensch erzeugt im Dashboard unter *Onboarding → Helfende Agenten* einen Schlüssel für dich (`hm_…`). Damit kannst du lesen und Pläne vorschlagen – mehr nicht:

```bash
curl -H "Authorization: Bearer $HOMIE_AGENT" http://<adresse>:8090/agent            # Regeln und Wege
curl -H "Authorization: Bearer $HOMIE_AGENT" http://<adresse>:8090/agent/zustand    # Module, Dienste, Pläne
curl -H "Authorization: Bearer $HOMIE_AGENT" http://<adresse>:8090/agent/rezepte    # was sich planen lässt
curl -H "Authorization: Bearer $HOMIE_AGENT" -H "Content-Type: application/json" \
     -d '{"rezept": "docker-vm", "parameter": {"name": "beispiel", "ram_gb": 2}}' http://<adresse>:8090/agent/plaene
```

Ein vorgeschlagener Plan ist ein Entwurf. Lesen, bestätigen und ausführen kann ihn nur der Mensch im Dashboard. Über diese Schnittstelle bekommst du nie Schlüssel zu sehen, kannst nichts verbinden, nichts erkunden und nichts ändern. Den Schlüssel selbst behandelst du wie jedes Geheimnis: nicht ausgeben, nicht in Dateien des Repositorys schreiben.

## Schlüssel und Privates

- **Keine Schlüssel im Chat.** Frag nie nach Passwörtern oder Tokens und gib nie welche aus. Der Mensch trägt sie selbst im Dashboard oder in Portainer ein.
- Lies den Datenordner (`/data`, Volume `homie-daten`) nicht aus und zeig seinen Inhalt nicht an. `docker inspect` und `docker compose config` können Geheimnisse anzeigen – nur gefiltert bzw. mit `-q` verwenden.
- Ins Repository gehören nur Programm und Beispielkonfiguration: keine echten Adressen, Namen, Geräte, Schlüssel. Vor jedem Push `scripts/privat-pruefung.sh` ausführen.

## Grenzen

- Homie bleibt im Heimnetz. Keine Portfreigaben, keine Tunnel, keine Cloud-Dienste ohne ausdrücklichen Auftrag.
- Bestehende Dienste im Netz werden nur gelesen. Anlegen, Ändern oder Löschen von VMs, Containern und Daten nur nach bestätigtem Plan.
- Homies Docker-Zugriff bleibt lesend und über den Zwischendienst `docker-lesen`. Den Docker-Socket nicht direkt in `homie` einhängen. Die einzige schreibende Stelle ist der abschaltbare Dienst `yamtrack-helfer` (von Haus aus aus): Er führt nur sein festes Programm im Yamtrack-Container aus – nicht um weitere Aufträge erweitern.

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
| `homie/meintag.py` | trägt für „Mein Tag“ alles in einer Antwort zusammen (`/api/tag`); die Seite dazu ist `static/mein-tag.js` |
| `homie/gesundheit.py`, `homie/tag.py` | Modul Gesundheit: liest Home Assistant; `tag.py` liefert nur die Zeitzone |
| `homie/assistent.py` | Module Aufnahme, Finanzen, Assistent: lesen den Notiz-Assistenten; geben neue Aufnahmen, Fotos, Kontoauszüge und Entscheidungen zu Vorschlägen an ihn weiter (`static/hochladen.js`) |
| `homie/dokumente.py` | Modul Dokumente: liest Paperless-ngx (nur lesend, nichts wird gespeichert); die Seite dazu ist `static/dokumente.js` |
| `homie/guide.py` | Tagesguide für „Mein Tag“: zieht aus dem Schnappschuss mit festen Regeln Schlüsse (Hinweise, Agenda, Ampeln). Kein Sprachmodell; jede Regel schweigt, wenn ihre Daten fehlen. Neue Regeln brauchen einen Test in `tests/test_grundgeruest.py` |
| `homie/bildtag.py` | Bild des Tages: wählt täglich ein Bild aus dem nur lesbar eingehängten Ordner `/bilder`; ausgeliefert unter `GET /api/bild-des-tages` mit fester Bildart (nie HTML oder SVG) |
| `homie/yamtrack.py` | Gesehenes in Yamtrack eintragen: Prüfung der Aufträge und der kleine Helfer mit Docker-Zugang (`python -m homie yamtrack-helfer`) |
| `homie/proxmox.py` | Proxmox lesen (VMs, Container, Speicher) |
| `homie/plaene.py` | Pläne entwerfen und prüfen; enthält bewusst keinen schreibenden Aufruf |
| `homie/ausfuehren.py` | einzige Stelle, die an Proxmox schreibt: legt nach Bestätigung genau eine neue VM an, löscht nie |
| `homie/startscheibe.py` | Einrichtungsanweisung für die neue VM als kleines CD-Abbild |
| `homie/agenten.py` | Schlüssel für helfende Agenten, Wege unter `/agent/…` |
| `homie/db.py`, `homie/config.py` | Datenbank im Datenordner, Einstellungen |
| `tests/` | `python -m unittest discover -s tests -v` muss vor jeder Änderung und danach grün sein |

Das Menüband ist für alle Seiten dasselbe: Vorlage `templates/_menue.html`, Aussehen `static/menue.css` (wird überall zuletzt geladen). Neue Seiten binden beides ein.

Neue Seiten und API-Wege sind automatisch geschützt. Öffentlich sind nur die in `OEFFENTLICH` genannten Wege, der Briefkasten `POST /api/health-webhook` (nimmt nur unterschriebene Lieferungen an und reicht sie weiter) und `POST /api/yamtrack` (nur mit dem Schlüssel des verbundenen Notiz-Assistenten, nur bei eingeschaltetem Helfer) – diese Liste nicht erweitern.
