# Homie

Ein Dashboard fürs Heimnetz, das sich selbst aufbaut: Homie erkundet dein Netz (nur lesend), zeigt gefundene Dienste als Karten, und sobald du einen Dienst verbindest, schaltet sich das passende Modul ein – Tagesüberblick, Aufnahme mit lokaler KI, Gesundheit, Finanzen, Dokumente, Netzplan.

**Stand: Etappe 1.** Installation, Anmeldung, Erkundung des Heimnetzes, Verbinden gefundener Dienste mit geprüften Schlüsseln und ein erster Netzplan. Die Inhalte der einzelnen Module folgen in Etappe 2.

Homie ist für das Heimnetz gedacht. Bitte nicht ins Internet freigeben.

## Installation in drei Schritten

Du brauchst einen Linux-Rechner mit Docker (ein Mini-PC, eine VM, ein NAS). Homie kommt als fertiges, öffentliches Image – gebaut werden muss nichts, und ein Token braucht es dafür nicht.

### Weg A: mit Portainer

1. **Stack anlegen:** Portainer → *Stacks* → *Add stack* → *Web editor*, Name `homie`. Den Inhalt von [docker-compose.yml](docker-compose.yml) hineinkopieren.
2. **Starten:** *Deploy the stack*. Portainer lädt das Image und startet Homie.
3. **Öffnen:** `http://<Adresse-des-Rechners>:8090` im Browser aufrufen und dein Passwort anlegen. Alles Weitere geschieht im Tab *Onboarding*.

### Weg B: ohne Portainer

1. **Holen:** `docker-compose.yml` in einen leeren Ordner auf dem Rechner legen.
2. **Starten:** in diesem Ordner `docker compose up -d`
3. **Öffnen:** `http://<Adresse-des-Rechners>:8090` aufrufen und dein Passwort anlegen.

Lege das Passwort gleich nach dem Start an: Bis dahin könnte es jeder in deinem Heimnetz tun.

## Was öffentlich ist und was nicht

| | Sichtbarkeit | Inhalt |
|---|---|---|
| Image `ghcr.io/joshlukas/homie` | öffentlich | nur das Programm – keine Daten, keine Schlüssel, keine Adressen |
| Dieses Repository | privat | Quelltext und seine Geschichte |
| Datenordner der Installation | nur auf deinem Rechner | alles Persönliche |

**Woher kommt das Image?** GitHub baut es bei jeder Änderung automatisch aus diesem Quelltext ([.github/workflows/image.yml](.github/workflows/image.yml)). Vorher laufen die Tests und die Privat-Prüfung: Steht im Repository eine Heimnetz-Adresse, ein Schlüssel oder eine E-Mail-Adresse, wird nichts gebaut und nichts veröffentlicht.

**Stack direkt aus dem Repository (optional):** In Portainer geht statt *Web editor* auch *Repository* (`https://github.com/joshlukas/homie`). Weil das Repository privat ist, braucht das ein GitHub-Token mit Lesezugriff auf dieses Repository (*Fine-grained token*, *Contents: Read-only*), das **du selbst** unter *Authentication* einträgst – nie in einen Chat. Dasselbe gilt für `git clone`. Dafür lässt sich Homie dann auch ohne das Image vor Ort bauen.

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

## Die Erkundung

Ein Klick auf *Heimnetz erkunden* im Onboarding – nie von selbst. Homie liest dabei nur:

1. **Eigenes Netz bestimmen:** nur private Adressbereiche, höchstens 254 Adressen um die eigene.
2. **Ports prüfen:** bei jeder Adresse ein Verbindungsversuch auf rund zwei Dutzend bekannten Ports. Drucker- und SSH-Ports sind ausgenommen.
3. **Dienste erkennen:** offene Web-Ports werden einmal abgerufen; im Katalog ([homie/katalog.py](homie/katalog.py)) steht, woran ein Dienst zu erkennen ist. Weiterleitungen aus dem Heimnetz hinaus werden nicht verfolgt.
4. **Docker lesen:** welche Container auf diesem Rechner laufen, über den nur lesenden Zwischendienst.

Homie meldet sich dabei nirgends an und ändert nichts. Das Ergebnis liegt ausschließlich im Datenordner.

**Verbinden:** Auf der Karte eines Dienstes trägst du seinen Schlüssel ein. Homie prüft ihn mit einem einzigen lesenden Aufruf bei genau diesem Dienst und legt ihn erst dann verschlüsselt ab. *Trennen* löscht ihn wieder.

## Module

Jedes Modul erklärt in [homie/module.py](homie/module.py), welchen Dienst und welchen Schlüssel es braucht. Es erscheint erst im Menü, wenn ein passender Dienst verbunden ist und sein Schlüssel in der Ablage liegt. Bis dahin steht im Onboarding, was noch fehlt.

## Alltag

- **Aktualisieren:** Portainer → Stack → *Pull and redeploy* (mit *Re-pull image*). Ohne Portainer: `docker compose pull && docker compose up -d`.
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
