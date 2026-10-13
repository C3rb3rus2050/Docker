"""Erzeugt den Anwendungskontext (Einstellungen, Datenbank, Ablage, Repository)."""

from __future__ import annotations

import logging
import logging.handlers
from dataclasses import dataclass
from pathlib import Path

from .security import RedactingFilter

from .config import Settings, load_settings
from .db import Database
from .repository import Repository
from .storage import DocumentStore

log = logging.getLogger("kest_tool")


@dataclass
class AppContext:
    settings: Settings
    db: Database
    store: DocumentStore
    repo: Repository

    @property
    def base_dir(self) -> Path:
        return self.store.base

    def close(self) -> None:
        self.db.close()


def setup_logging(base_dir: Path) -> None:
    logs = base_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("kest_tool")
    target = str((logs / "kest_tool.log").resolve())
    for h in list(root.handlers):
        if getattr(h, "_kest", False):
            if getattr(h, "baseFilename", None) == target:
                return
            h.close()
            root.removeHandler(h)
    handler = logging.handlers.RotatingFileHandler(logs / "kest_tool.log", maxBytes=5_000_000, backupCount=5,
                                                   encoding="utf-8")
    handler._kest = True  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def create_context(settings: Settings | None = None, base_dir: Path | None = None) -> AppContext:
    settings = settings or load_settings()
    base = Path(base_dir) if base_dir else settings.base_dir
    store = DocumentStore(base, settings.tax_years)
    store.ensure_structure(settings.tax_years)
    setup_logging(base)
    db = Database(base / "database" / "kest_tool.db")
    ctx = AppContext(settings=settings, db=db, store=store, repo=Repository(db, store))
    try:
        if base_dir is None:
            settings.write_copy_to_base()
    except OSError as exc:  # nicht kritisch
        log.warning("Konfigurationskopie konnte nicht geschrieben werden: %s", exc)
    return ctx


def shutdown_logging() -> None:
    """Schließt die Logdatei (nötig unter Windows, bevor der Ablageordner verschoben werden kann)."""
    root = logging.getLogger("kest_tool")
    for h in list(root.handlers):
        if getattr(h, "_kest", False):
            h.close()
            root.removeHandler(h)
