"""Optionaler Windows-Aufgabenplaner-Eintrag für die regelmäßige Synchronisierung.

- Läuft nur, wenn der Benutzer angemeldet ist (``/IT``), da ggf. eine Anmeldung im
  sichtbaren Browser nötig ist. Abgelaufene Sitzungen werden NICHT umgangen: der Sync wartet
  auf den Benutzer und bricht nach dem Zeitlimit mit Status „Anmeldung erforderlich“ ab.
- Keine Administratorrechte nötig (``/RL LIMITED``).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TASK_NAME = "BrokerDocumentCollector Sync"


class SchedulerError(RuntimeError):
    pass


def build_create_command(start_bat: Path, time_hhmm: str, schedule: str = "DAILY") -> list[str]:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time_hhmm or ""):
        raise SchedulerError("Uhrzeit bitte im Format HH:MM angeben, z. B. 07:30")
    if schedule not in ("DAILY", "WEEKLY"):
        raise SchedulerError("Nur DAILY oder WEEKLY werden unterstützt")
    tr = f'"{Path(start_bat).resolve()}" --sync'
    return ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", tr, "/SC", schedule, "/ST", time_hhmm,
            "/RL", "LIMITED", "/IT", "/F"]


def build_delete_command() -> list[str]:
    return ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]


def _run(cmd: list[str]) -> str:
    if sys.platform != "win32":
        raise SchedulerError("Der Aufgabenplaner ist nur unter Windows verfügbar.")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="cp850", errors="replace")
    if proc.returncode != 0:
        raise SchedulerError((proc.stderr or proc.stdout).strip() or f"schtasks-Fehler {proc.returncode}")
    return proc.stdout.strip()


def create_task(start_bat: Path, time_hhmm: str, schedule: str = "DAILY") -> str:
    return _run(build_create_command(start_bat, time_hhmm, schedule))


def delete_task() -> str:
    return _run(build_delete_command())
