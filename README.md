# Homie

Ein Dashboard fürs Heimnetz, das sich selbst aufbaut: Homie erkundet dein Netz (nur lesend), zeigt gefundene Dienste als Karten, und sobald du einen Dienst verbindest, schaltet sich das passende Modul ein – Tagesüberblick, Aufnahme mit lokaler KI, Gesundheit, Finanzen, Dokumente, Netzplan.

**Stand: Etappe 0 – das Grundgerüst.** Installation, Passwort, Anmeldung, Modul-Register, verschlüsselte Schlüssel-Ablage und ein noch leeres Onboarding. Die Erkundung folgt in Etappe 1.

Homie ist für das Heimnetz gedacht. Bitte nicht ins Internet freigeben.

## Installation in drei Schritten

Du brauchst einen Linux-Rechner mit Docker (ein Mini-PC, eine VM, ein NAS).

### Weg A: mit Portainer

1. **Stack anlegen:** Portainer → *Stacks* → *Add stack* → *Repository*.
   Repository-URL `https://github.com/joshlukas/homie`, Compose-Pfad `docker-compose.yml` (ist schon vorausgefüllt).
   Solange das Repository privat ist: *Authentication* einschalten und GitHub-Benutzername plus ein Zugriffstoken eintragen (siehe [Privates Repository](#privates-repository)).
2. **Starten:** *Deploy the stack*. Das erste Mal dauert ein paar Minuten, weil Homie auf deinem Rechner gebaut wird.
3. **Öffnen:** `http://<Adresse-des-Rechners>:8090` im Browser aufrufen und dein Passwort anlegen. Alles Weitere geschieht im Tab *Onboarding*.

### Weg B: ohne Portainer

1. **Holen:** `git clone https://github.com/joshlukas/homie.git && cd homie`
   (bei privatem Repository fragt Git nach Benutzername und Zugriffstoken)
2. **Starten:** `docker compose up -d`
3. **Öffnen:** `http://<Adresse-des-Rechners>:8090` aufrufen und dein Passwort anlegen.

Lege das Passwort gleich nach dem Start an: Bis dahin könnte es jeder in deinem Heimnetz tun.

## Privates Repository

Solange dieses Repository privat ist, braucht der Abruf einen GitHub-Zugang – genau einen, und nur zum Lesen:

- Auf GitHub: *Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token*.
  Zugriff nur auf dieses eine Repository, Berechtigung *Contents: Read-only*, sonst nichts.
- Dieses Token trägst **du selbst** in Portainer (*Authentication*) oder bei der Git-Abfrage ein. Es gehört in keinen Chat und in keine Datei im Repository.

**Warum wird gebaut und kein fertiges Image geladen?** Geprüft wurden beide Wege:

| | Bauen aus dem Repository (gewählt) | Fertiges Image (GitHub-Paketablage) |
|---|---|---|
| Zugänge bei privatem Repo | einer: Lesen des Repos | zwei: Lesen des Repos **und** Anmeldung an der Paketablage in Docker/Portainer |
| Zusätzliche Technik | keine | Bau-Automatik auf GitHub, die bei jeder Änderung ein Image erzeugt |
| Erster Start | einige Minuten (Bauen) | schneller |
| Was läuft | genau der Quelltext, den du siehst | ein Image, dem du vertrauen musst |

Mit privatem Repository ist Bauen der Weg mit den wenigsten Handgriffen. Wird das Repository öffentlich, braucht keiner der beiden Wege noch einen Zugang; dann lohnt sich ein fertiges Image für den schnelleren Start.

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

- **Aktualisieren:** Portainer → Stack → *Pull and redeploy*. Ohne Portainer: `git pull && docker compose up -d`.
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
