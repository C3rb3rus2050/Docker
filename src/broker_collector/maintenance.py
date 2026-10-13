"""Getrenntes Löschen von Browserprofil, Datenbank und heruntergeladenen Dateien."""

from __future__ import annotations

import logging
from pathlib import Path

from .config import Settings
from .downloader import BROKER_FOLDERS
from .security import remove_tree

log = logging.getLogger(__name__)


def delete_browser_profile(settings: Settings, broker: str | None = None) -> list[str]:
    """Löscht das Browserprofil (Cookies, Sitzungen) – danach ist eine Neuanmeldung nötig.
    Der Browser muss dafür geschlossen sein."""
    targets = [settings.broker_profile_dir(broker)] if broker else [settings.profile_dir]
    removed = []
    for t in targets:
        if remove_tree(t, must_be_inside=[settings.profile_dir.parent]):
            removed.append(str(t))
    log.info("Browserprofil gelöscht: %s", removed or "nichts vorhanden")
    return removed


def delete_database(settings: Settings) -> list[str]:
    removed = []
    db = settings.database_path
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db) + suffix)
        if p.exists():
            p.unlink()
            removed.append(str(p))
    log.info("Datenbank gelöscht: %s", removed or "nichts vorhanden")
    return removed


def delete_downloads(settings: Settings, broker: str | None = None) -> list[str]:
    """Löscht heruntergeladene Dokumente (nur die Broker-Ordner, nicht Datenbank/Logs/Berichte)."""
    folders = [BROKER_FOLDERS[broker]] if broker else list(BROKER_FOLDERS.values())
    removed = []
    for folder in folders:
        target = settings.output_dir / folder
        if remove_tree(target, must_be_inside=[settings.output_dir]):
            removed.append(str(target))
    log.info("Downloads gelöscht: %s", removed or "nichts vorhanden")
    return removed
