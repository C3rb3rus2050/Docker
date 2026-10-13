"""Konfiguration: Standardwerte, Laden aus TOML, Speichern der UI-Einstellungen.

Die Konfiguration enthält bewusst KEINE Zugangsdaten. Unbekannte oder verdächtige
Schlüssel (password, token, cookie …) werden beim Laden abgelehnt.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

APP_NAME = "BrokerDocumentCollector"
FORBIDDEN_KEY_PARTS = ("password", "passwort", "pin", "token", "cookie", "secret", "session", "credential")


def default_output_dir() -> Path:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / "Documents" / APP_NAME


def default_profile_dir() -> Path:
    """Browserprofile liegen bewusst NICHT im Dokumente-Ordner (häufig OneDrive-synchronisiert),
    sondern unter %LOCALAPPDATA% (nicht servergespeichert)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / APP_NAME / "browser-profile"


@dataclass
class Settings:
    output_dir: Path = field(default_factory=default_output_dir)
    profile_dir: Path = field(default_factory=default_profile_dir)
    ocr_enabled: bool = False
    tesseract_cmd: str = ""
    pdf_text_extraction: bool = True

    # Download-Engine
    max_download_mb: int = 100
    download_timeout_s: int = 90
    retry_attempts: int = 3
    retry_backoff_s: float = 2.0

    # Discovery-Grenzen (Schutz vor Endlosschleifen)
    max_pages_per_area: int = 200
    max_load_more_clicks: int = 500
    max_areas: int = 60
    max_items_per_area: int = 5000
    action_delay_ms: int = 600  # höflich: kein Hämmern auf die Brokerseite

    # Browser
    browser_channel: str = ""  # "" = Playwright-Chromium, "msedge"/"chrome" möglich
    browser_executable: str = ""
    login_wait_timeout_s: int = 600

    # Zweite Quelle (Abgleich)
    trade_republic_websocket: bool = True
    network_capture: bool = True
    # Zusätzliche erlaubte Download-Hosts (kommagetrennt), falls ein Broker Dokumente von
    # einem weiteren Host ausliefert. Nur offizielle Speicherorte des Brokers eintragen.
    extra_document_hosts: str = ""

    # Web-UI
    ui_host: str = "127.0.0.1"
    ui_port: int = 8765
    open_browser_ui: bool = True

    # Sync-Modus
    recheck_old_areas: bool = False

    # --------------------------------------------------------------------- #
    @property
    def database_path(self) -> Path:
        return self.output_dir / "database" / "collector.sqlite3"

    @property
    def logs_dir(self) -> Path:
        return self.output_dir / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.output_dir / "reports"

    @property
    def max_download_bytes(self) -> int:
        return int(self.max_download_mb) * 1024 * 1024

    def broker_profile_dir(self, broker: str) -> Path:
        return self.profile_dir / broker

    def ensure_dirs(self) -> None:
        for d in (self.output_dir, self.database_path.parent, self.logs_dir, self.reports_dir, self.profile_dir):
            d.mkdir(parents=True, exist_ok=True)

    def to_public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: (str(v) if isinstance(v, Path) else v) for k, v in data.items()}


class ConfigError(ValueError):
    pass


def _coerce(name: str, value: Any, current: Any) -> Any:
    if isinstance(current, Path):
        return Path(os.path.expandvars(os.path.expanduser(str(value))))
    if isinstance(current, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "ja", "yes", "on")
        return bool(value)
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return str(value)


def _check_key(key: str) -> None:
    low = key.lower()
    if any(part in low for part in FORBIDDEN_KEY_PARTS) and low not in {"profile_dir"}:
        raise ConfigError(
            f"Der Konfigurationsschlüssel '{key}' ist nicht erlaubt: Zugangsdaten dürfen nicht in "
            "Konfigurationsdateien gespeichert werden."
        )


def apply_values(settings: Settings, values: dict[str, Any]) -> Settings:
    known = {f.name for f in fields(Settings)}
    for key, value in values.items():
        if isinstance(value, dict):
            apply_values(settings, value)  # Abschnitte wie [download] flach übernehmen
            continue
        _check_key(key)
        if key not in known:
            raise ConfigError(f"Unbekannter Konfigurationsschlüssel: {key}")
        setattr(settings, key, _coerce(key, value, getattr(settings, key)))
    return settings


def load_settings(path: Path | None = None) -> Settings:
    settings = Settings()
    env_out = os.environ.get("BDC_OUTPUT_DIR")
    if path is None:
        path = Path(os.environ.get("BDC_CONFIG", "config.toml"))
    if path.exists():
        with path.open("rb") as fh:
            apply_values(settings, tomllib.load(fh))
    if env_out:
        settings.output_dir = Path(env_out)
    if os.environ.get("BDC_BROWSER_EXECUTABLE"):
        settings.browser_executable = os.environ["BDC_BROWSER_EXECUTABLE"]
    return settings


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def save_settings(settings: Settings, path: Path) -> None:
    """Speichert die Einstellungen (ohne Zugangsdaten – solche Felder existieren nicht)."""
    lines = ["# Broker Document Collector – automatisch gespeicherte Einstellungen", ""]
    for key, value in settings.to_public_dict().items():
        lines.append(f"{key} = {_toml_value(value)}")
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)
