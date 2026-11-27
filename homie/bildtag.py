"""„Bild des Tages“: wählt aus einem Ordner jeden Tag ein Bild für „Mein Tag“.

Der Ordner wird nur gelesen (im Container nur lesbar eingehängt). Wie die Bilder hineinkommen, ist Homie gleich –
zum Beispiel über die freiwillige Netzwerk-Freigabe aus docker-compose.yml. Jeden Tag ist ein anderes Bild dran,
den ganzen Tag dasselbe; wiederholt wird erst, wenn alle an der Reihe waren. Kommen Bilder dazu oder fallen weg
(ändert sich also die Anzahl), wird neu gemischt. Wird nur ein Bild gegen ein anderes getauscht, bleibt die
Reihenfolge, und das neue Bild kommt an die Stelle des alten.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import random
from pathlib import Path

# Nur Bildarten, die der Browser als Bild zeigt und die nichts ausführen können (kein SVG).
ARTEN = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif"}
MAX_BYTES = 30 * 1024 * 1024
MAX_DATEIEN = 5000


def bilder(ordner: Path) -> list[Path]:
    """Alle brauchbaren Bilder im Ordner und seinen Unterordnern, nach Namen sortiert."""
    gefunden: list[Path] = []
    try:
        for p in sorted(ordner.rglob("*")):
            if p.suffix.lower() not in ARTEN or any(teil.startswith(".") for teil in p.relative_to(ordner).parts):
                continue
            if p.is_symlink() or not p.is_file() or not 0 < p.stat().st_size <= MAX_BYTES:
                continue
            gefunden.append(p)
            if len(gefunden) >= MAX_DATEIEN:
                break
    except OSError:
        pass
    return gefunden


def heute(ordner: Path, tag: dt.date) -> Path | None:
    """Das Bild für diesen Tag. Die Tage zählen fortlaufend; je len(alle) Tage sind eine Runde, und jede Runde
    hat ihre eigene, feste Mischung – so kommt in einer Runde jedes Bild genau einmal dran."""
    alle = bilder(ordner)
    if not alle:
        return None
    runde, platz = divmod(tag.toordinal(), len(alle))
    random.Random(f"{runde}:{len(alle)}").shuffle(alle)
    return alle[platz]


def marke(bild: Path, tag: dt.date) -> str:
    """Kurzes Kennzeichen für Tag und Datei – ändert es sich, lädt der Browser das Bild neu."""
    try:
        stand = bild.stat()
    except OSError:
        return ""
    return hashlib.sha256(f"{tag.isoformat()}|{bild.name}|{stand.st_size}|{stand.st_mtime_ns}".encode()).hexdigest()[:16]
