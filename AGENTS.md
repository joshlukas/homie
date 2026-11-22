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
| `homie/meintag.py` | trägt für „Mein Tag“ alles in einer Antwort zusammen (`/api/tag`); die Seite dazu ist `static/mein-tag.js` |
| `homie/gesundheit.py`, `homie/tag.py` | Modul Gesundheit: liest Home Assistant; Zeitzone |
| `homie/assistent.py` | Module Aufnahme, Finanzen, Assistent: lesen den Notiz-Assistenten; geben neue Aufnahmen und Entscheidungen zu Vorschlägen an ihn weiter |
| `homie/dokumente.py` | Modul Dokumente: liest Paperless-ngx (nur lesend, nichts wird gespeichert); die Seite dazu ist `static/dokumente.js` |
| `homie/proxmox.py` | Proxmox lesen (VMs, Container, Speicher) |
| `homie/plaene.py` | Pläne entwerfen und prüfen; enthält bewusst keinen schreibenden Aufruf |
| `homie/ausfuehren.py` | einzige Stelle, die an Proxmox schreibt: legt nach Bestätigung genau eine neue VM an, löscht nie |
| `homie/startscheibe.py` | Einrichtungsanweisung für die neue VM als kleines CD-Abbild |
| `homie/agenten.py` | Schlüssel für helfende Agenten, Wege unter `/agent/…` |
| `homie/db.py`, `homie/config.py` | Datenbank im Datenordner, Einstellungen |
| `tests/` | `python -m unittest discover -s tests -v` muss vor jeder Änderung und danach grün sein |

Das Menüband ist für alle Seiten dasselbe: Vorlage `templates/_menue.html`, Aussehen `static/menue.css` (wird überall zuletzt geladen). Neue Seiten binden beides ein.

Neue Seiten und API-Wege sind automatisch geschützt. Öffentlich sind nur die in `OEFFENTLICH` genannten Wege und der Briefkasten `POST /api/health-webhook` (nimmt nur unterschriebene Lieferungen an und reicht sie weiter) – diese Liste nicht erweitern.
