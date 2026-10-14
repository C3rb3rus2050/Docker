"""Privacy-conscious local diagnostics for the KESt web application."""
from __future__ import annotations

import io
import json
import logging
import os
import platform
import re
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from kest_tool import __version__

_LOGGER = logging.getLogger("kest_tool.diagnostics")
_MAX_EVENTS = 150
_MAX_LOG_BYTES = 256 * 1024


def _directory() -> Path:
    base = Path(os.environ.get("KEST_TOOL_HOME", str(Path.home() / ".kest-tool")))
    directory = base / "diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _safe_message(message: str) -> str:
    """Conservatively remove likely private values; do not include stack traces in exports."""
    message = re.sub(r"(?i)(password|token|secret|api[_-]?key|authorization)\\s*[:=]\\s*\\S+",
                     r"\\1=[REDACTED]", message)
    message = re.sub(r"(?i)bearer\\s+\\S+", "Bearer [REDACTED]", message)
    message = re.sub(r"(?i)[A-Z]:\\\\[^\\s]+|/(?:home|data|mnt|opt|users)/[^\\s]+", "[PATH]", message)
    message = re.sub(r"\\b[A-Z]{2}[A-Z0-9]{10}\\b", "[ISIN]", message)
    return message[:500]


def record_error(area: str, exc: Exception) -> str:
    """Record exception type and safe context, not exception values or document content."""
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    event = {
        "id": identifier,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "area": re.sub(r"[^a-zA-Z0-9_.-]", "_", area)[:80],
        "exception": type(exc).__name__,
    }
    try:
        path = _directory() / "events.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        if path.stat().st_size > _MAX_LOG_BYTES:
            lines = path.read_text(encoding="utf-8").splitlines()[-_MAX_EVENTS:]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        _LOGGER.warning("Could not persist diagnostic event", exc_info=False)
    _LOGGER.error("Application error %s in %s (%s)", identifier, area, type(exc).__name__)
    return identifier


def export_report() -> bytes:
    """Downloadable metadata-only report, excluding DB, PDF, config, secrets and raw Docker logs."""
    events = []
    try:
        path = _directory() / "events.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines()[-_MAX_EVENTS:]:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "app_version": __version__,
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "events": events,
        "note": "No documents, transactions, credentials, paths or raw logs included.",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", json.dumps(report, ensure_ascii=False, indent=2))
        archive.writestr("README.txt", "KESt diagnostic report. Review contents before sharing.\n")
    return output.getvalue()


def event_count() -> int:
    try:
        return len((_directory() / "events.jsonl").read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0
