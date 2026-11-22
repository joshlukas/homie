# Homie

Ein Dashboard fürs Heimnetz, das sich selbst aufbaut: Homie erkundet dein Netz (nur lesend), zeigt gefundene Dienste als Karten, und sobald du einen Dienst verbindest, schaltet sich das passende Modul ein – Tagesüberblick, Aufnahme mit lokaler KI, Gesundheit, Finanzen, Dokumente, Netzplan.

**Stand: Etappe 0 – das Grundgerüst.** Installation, Passwort, Anmeldung, Modul-Register, verschlüsselte Schlüssel-Ablage und ein noch leeres Onboarding. Die Erkundung folgt in Etappe 1.

Homie ist für das Heimnetz gedacht. Bitte nicht ins Internet freigeben.

## Installation in drei Schritten

Du brauchst einen Linux-Rechner mit Docker (ein Mini-PC, eine VM, ein NAS). Homie kommt als fertiges Image; gebaut werden muss nichts.

### Weg A: mit Portainer

1. **Stack anlegen:** Portainer → *Stacks* → *Add stack* → *Repository*.
   Repository-URL `https://github.com/joshlukas/homie`, Compose-Pfad `docker-compose.yml` (ist schon vorausgefüllt).
2. **Starten:** *Deploy the stack*. Portainer lädt das fertige Image und startet Homie.
3. **Öffnen:** `http://<Adresse-des-Rechners>:8090` im Browser aufrufen und dein Passwort anlegen. Alles Weitere geschieht im Tab *Onboarding*.

### Weg B: ohne Portainer

1. **Holen:** `git clone https://github.com/joshlukas/homie.git && cd homie`
2. **Starten:** `docker compose up -d`
3. **Öffnen:** `http://<Adresse-des-Rechners>:8090` aufrufen und dein Passwort anlegen.

Lege das Passwort gleich nach dem Start an: Bis dahin könnte es jeder in deinem Heimnetz tun.

## Solange Repository und Image privat sind

Dann braucht der Abruf einen GitHub-Zugang, den **du selbst** einträgst – nie in einen Chat, nie in eine Datei im Repository:

- Auf GitHub: *Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token* mit den Rechten `repo` (Repository lesen) und `read:packages` (Image laden).
- **Portainer:** unter *Registries* einmal `ghcr.io` mit Benutzername und Token hinterlegen; beim Stack *Authentication* einschalten und dieselben Angaben eintragen.
- **Ohne Portainer:** einmal `docker login ghcr.io` ausführen; `git clone` fragt selbst nach Benutzername und Token.

Sind Repository und Image öffentlich, entfällt das alles.

**Woher kommt das Image?** GitHub baut es bei jeder Änderung automatisch aus genau diesem Quelltext ([.github/workflows/image.yml](.github/workflows/image.yml)), nach bestandenen Tests, und legt es als `ghcr.io/joshlukas/homie:latest` ab. Lässt sich das Image nicht laden, baut der Stack Homie ersatzweise auf deinem Rechner aus dem Repository – dann reicht der Lesezugriff auf das Repository.

## Was wo liegt

| Ort | Inhalt |
|---|---|
| Dieses Repository | Nur Programm und Beispielkonfiguration. Nichts Persönliches. |
| Volume `homie-daten` (im Container `/data`) | Alles Private: dein Konto (Passwort nur als scrypt-Prüfwert), Sitzungen, gefundene Dienste, eingetragene Schlüssel (AES-256-GCM-verschlüsselt) und der Hauptschlüssel dazu. |

Eine Sicherung von Homie ist eine Sicherung dieses Volumes. Wer das Volume samt Hauptschlüssel-Datei kopiert, kann die Schlüssel lesen – wer das trennen will, setzt `HOMIE_MASTER_KEY` (siehe `.env.example`).

## Der Stack

- **homie** – das Dashboard. Läuft im Netz des Rechners (`network_mode: host`), damit die spätere Erkundung Geräte im Heimnetz sehen kann. Ohne Root-Rechte, Dateisystem nur lesbar, schreibt ausschließlich in den Datenordner.
- **docker-lesen** – ein Zwischendienst, der Homie einen *nur lesenden* Blick auf Docker gibt (welche Container laufen). Homie bekommt den Docker-Zugang nie direkt, und der Zwischendienst ist nur auf dem Rechner selbst erreichbar. Abschalten mit `HOMIE_DOCKER_LESEN=0`.

Einstellungen sind freiwillig; alle stehen mit Erklärung in [.env.example](.env.example). Auf Docker Desktop (Windows/Mac) funktioniert das Heimnetz des Rechners anders – vorgesehen ist ein Linux-Rechner.

## Module

Jedes Modul erklärt in [homie/module.py](homie/module.py), welchen Dienst und welchen Schlüssel es braucht. Es erscheint erst im Menü, wenn ein passender Dienst verbunden ist und sein Schlüssel in der Ablage liegt. Bis dahin steht im Onboarding, was noch fehlt.

## Alltag

- **Aktualisieren:** Portainer → Stack → *Pull and redeploy* (mit *Re-pull image*). Ohne Portainer: `git pull && docker compose pull && docker compose up -d`.
- **Passwort vergessen:** `docker exec homie python -m homie passwort-zuruecksetzen` – danach legst du im Browser ein neues an. Daten und Schlüssel bleiben.
- **Entfernen:** Stack löschen. Das Volume `homie-daten` bleibt, bis du es ausdrücklich löschst.

## Entwicklung

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v                 # Tests
HOMIE_DATA=./data HOMIE_DOCKER_LESEN=0 python -m homie  # lokal starten, http://localhost:8090
scripts/privat-pruefung.sh                              # vor jedem Push: nichts Privates im Repository?
```

Wer sich von einem KI-Agenten helfen lässt: [AGENTS.md](AGENTS.md).
