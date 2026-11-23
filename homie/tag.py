"""Zeitzone der Installation (Umgebungsvariable TZ, sonst Europe/Berlin)."""
from __future__ import annotations

import datetime as dt
import os
from zoneinfo import ZoneInfo


def zone() -> dt.tzinfo:
    try:
        return ZoneInfo(os.environ.get("TZ") or "Europe/Berlin")
    except Exception:
        return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc
