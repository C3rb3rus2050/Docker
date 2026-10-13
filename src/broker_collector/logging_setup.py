"""Logging mit rotierenden Dateien und automatischer Redaktion sensibler Daten."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .security import RedactingFilter

FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"


def setup_logging(logs_dir: Path, level: int = logging.INFO, console: bool = True) -> logging.Logger:
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        if getattr(h, "_bdc", False):
            root.removeHandler(h)
            h.close()
    redactor = RedactingFilter()
    file_handler = RotatingFileHandler(logs_dir / "collector.log", maxBytes=5 * 1024 * 1024, backupCount=5,
                                       encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(FORMAT))
    file_handler.addFilter(redactor)
    file_handler._bdc = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)
    if console:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        stream.addFilter(redactor)
        stream._bdc = True  # type: ignore[attr-defined]
        root.addHandler(stream)
    # Playwright/asyncio-Debugausgaben könnten Header enthalten → nicht unter WARNING protokollieren
    for noisy in ("asyncio", "urllib3", "playwright"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return root
