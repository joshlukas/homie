"""Erzeugt die kleine „Startscheibe“ für eine neue VM: ein CD-Abbild mit der Einrichtungsanweisung.

Ubuntu-Cloud-Images lesen beim ersten Start eine Scheibe mit dem Namen „cidata“ und richten sich danach
selbst ein (Benutzer, Schlüssel, Pakete). So kann Homie eine VM vollständig vorbereiten, ohne sich
je in sie einzuloggen. Das Abbild wird hier ohne fremde Werkzeuge geschrieben (ISO 9660 mit Joliet,
damit die Dateinamen „user-data“ und „meta-data“ genau so ankommen).
"""
from __future__ import annotations

import struct
import time

SEKTOR = 2048


def _beide16(n: int) -> bytes:
    return struct.pack("<H", n) + struct.pack(">H", n)


def _beide32(n: int) -> bytes:
    return struct.pack("<I", n) + struct.pack(">I", n)


def _eintrag(name: bytes, ort: int, laenge: int, ordner: bool, zeit: time.struct_time) -> bytes:
    kopf = bytes([0]) + _beide32(ort) + _beide32(laenge) + bytes([zeit.tm_year - 1900, zeit.tm_mon, zeit.tm_mday, zeit.tm_hour, zeit.tm_min, zeit.tm_sec, 0])
    kopf += bytes([2 if ordner else 0, 0, 0]) + _beide16(1) + bytes([len(name)]) + name
    if len(kopf) % 2 == 0:      # mit dem Längenbyte davor muss die Gesamtlänge gerade sein
        kopf += b"\x00"
    return bytes([len(kopf) + 1]) + kopf


def _ordner(eintraege: list[tuple[bytes, int, int]], ort: int, zeit: time.struct_time) -> bytes:
    inhalt = _eintrag(b"\x00", ort, SEKTOR, True, zeit) + _eintrag(b"\x01", ort, SEKTOR, True, zeit)
    for name, wo, laenge in sorted(eintraege):
        inhalt += _eintrag(name, wo, laenge, False, zeit)
    assert len(inhalt) <= SEKTOR
    return inhalt.ljust(SEKTOR, b"\x00")


def _pfadtabelle(ort: int, gross: bool) -> bytes:
    return (bytes([1, 0]) + struct.pack(">I" if gross else "<I", ort) + struct.pack(">H" if gross else "<H", 1) + b"\x00\x00").ljust(SEKTOR, b"\x00")


def _kennsatz(art: int, name: bytes, system: bytes, flucht: bytes, sektoren: int, tabelle_klein: int, tabelle_gross: int,
              wurzel: bytes, zeit: time.struct_time, leer: bytes) -> bytes:
    datum = time.strftime("%Y%m%d%H%M%S00", zeit).encode() + b"\x00"
    kein_datum = b"0" * 16 + b"\x00"
    k = bytes([art]) + b"CD001" + bytes([1, 0]) + system + name + bytes(8) + _beide32(sektoren) + flucht.ljust(32, b"\x00")
    k += _beide16(1) + _beide16(1) + _beide16(SEKTOR) + _beide32(10)
    k += struct.pack("<I", tabelle_klein) + bytes(4) + struct.pack(">I", tabelle_gross) + bytes(4) + wurzel
    k += leer * (128 // len(leer)) * 4            # Bandsatz, Herausgeber, Ersteller, Programm
    k += (leer * 37)[:37] * 3                     # Urheber-, Kurzfassungs-, Quellendatei
    k += datum + datum + kein_datum + kein_datum + bytes([1, 0])
    assert len(k) == 883, len(k)
    return k.ljust(SEKTOR, b"\x00")


def abbild(dateien: dict[str, bytes], name: str = "cidata") -> bytes:
    """ISO-Abbild mit den Dateien im Wurzelordner. Dateinamen: höchstens 8 Zeichen ohne Bindestrich im Kurznamen-Teil."""
    zeit = time.gmtime()
    erster = 25
    orte, daten = {}, b""
    for datei, inhalt in dateien.items():
        orte[datei] = (erster + len(daten) // SEKTOR, len(inhalt))
        daten += inhalt.ljust(-(-max(len(inhalt), 1) // SEKTOR) * SEKTOR, b"\x00")
    sektoren = erster + len(daten) // SEKTOR

    kurz = [(datei.replace("-", "").upper()[:8].encode() + b".;1", *orte[datei]) for datei in dateien]
    lang = [(datei.encode("utf-16-be"), *orte[datei]) for datei in dateien]
    wurzel_kurz = _eintrag(b"\x00", 23, SEKTOR, True, zeit)
    wurzel_lang = _eintrag(b"\x00", 24, SEKTOR, True, zeit)

    bild = bytes(16 * SEKTOR)
    bild += _kennsatz(1, name.upper().encode().ljust(32), b" " * 32, b"", sektoren, 19, 20, wurzel_kurz, zeit, b" ")
    bild += _kennsatz(2, (name.encode("utf-16-be") + b"\x00 " * 16)[:32], b"\x00 " * 16, b"%/E", sektoren, 21, 22, wurzel_lang, zeit, b"\x00 ")
    bild += (bytes([255]) + b"CD001" + bytes([1])).ljust(SEKTOR, b"\x00")
    bild += _pfadtabelle(23, False) + _pfadtabelle(23, True) + _pfadtabelle(24, False) + _pfadtabelle(24, True)
    bild += _ordner(kurz, 23, zeit) + _ordner(lang, 24, zeit)
    assert len(bild) == erster * SEKTOR
    return bild + daten


def anweisung(name: str, schluessel: list[str], vmid: int | str) -> dict[str, bytes]:
    """Die Einrichtung der neuen VM: Benutzer ohne Passwort, nur Schlüssel; Gast-Agent und Docker aus den offiziellen Quellen."""
    zeilen = [
        "#cloud-config",
        f"hostname: {name}",
        "ssh_pwauth: false",
        "users:",
        "  - name: homie",
        "    shell: /bin/bash",
        "    groups: [sudo]",
        '    sudo: "ALL=(ALL) NOPASSWD:ALL"',
        "    lock_passwd: true",
        "    ssh_authorized_keys:",
        *[f"      - {s}" for s in schluessel],
        "package_update: true",
        "packages: [qemu-guest-agent, ca-certificates, curl]",
        "runcmd:",
        "  - systemctl enable --now qemu-guest-agent",
        "  - install -m 0755 -d /etc/apt/keyrings",
        "  - curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc",
        "  - chmod a+r /etc/apt/keyrings/docker.asc",
        "  - sh -c 'echo \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable\" > /etc/apt/sources.list.d/docker.list'",
        "  - apt-get update",
        "  - DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin",
        "  - usermod -aG docker homie",
        "  - touch /var/lib/homie-eingerichtet",
        "",
    ]
    return {"user-data": "\n".join(zeilen).encode(), "meta-data": f"instance-id: homie-{vmid}\nlocal-hostname: {name}\n".encode()}
