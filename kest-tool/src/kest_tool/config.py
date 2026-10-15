"""Konfiguration.

Reihenfolge (spätere Quellen überschreiben frühere):

1. ``config.yaml`` im Projektordner (mitgelieferte Standardwerte, versioniert)
2. Mit ``KEST_TOOL_HOME``: ``<Ablage>/config/config.yaml``; sonst ``config.local.yaml`` im Projektordner
3. Umgebungsvariable ``KEST_TOOL_HOME`` (Ablageordner, z. B. für Tests)

Eine Kopie der wirksamen Konfiguration wird zusätzlich unter ``<Ablage>/config/config.yaml``
abgelegt, damit Backups die Einstellungen enthalten.

Zugangsdaten gehören nicht in die Konfiguration: Schlüssel wie ``password`` oder ``token``
werden beim Laden abgelehnt.
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config.yaml"
LOCAL_CONFIG_FILE = PROJECT_ROOT / "config.local.yaml"

FORBIDDEN_KEYS = re.compile(r"pass(wort|word)?|pin$|token|secret|cookie|session|api_?key", re.IGNORECASE)

DEFAULTS: dict[str, Any] = {
    "base_dir": "%USERPROFILE%/Documents/KESt-Tool",
    "default_tax_year": None,  # None = Vorjahr
    "tax_years": [2022, 2023, 2024, 2025, 2026],
    "base_currency": "EUR",
    "currencies": ["EUR", "USD", "CHF", "GBP", "CAD", "JPY", "DKK", "SEK", "NOK", "AUD"],
    "import": {
        "date_formats": ["%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y"],
        "decimal_separator": "auto",  # auto | , | .
        "max_upload_mb": 50,
        "allowed_extensions": [".csv", ".txt", ".xlsx", ".xls", ".pdf"],
        "fuzzy_duplicate_days": 3,
        "fuzzy_duplicate_tolerance": 0.005,
    },
    "pdf": {"engine": "auto", "ocr_enabled": False},  # auto = pdfplumber, Fallback PyMuPDF
    "privacy": {"allow_external_services": False},
    "fx": {"auto_fetch": True},
    "prices": {"provider": "eodhd", "auto_fetch": True,
               "preferred_exchanges": ["XETRA", "F", "VI", "LSE", "AS", "PA", "SW", "MI", "US"]},
    "oekb": {"automatic_provider": "none"},
}


class ConfigError(ValueError):
    pass


def expand_path(value: str | os.PathLike) -> Path:
    """Löst ``%USERPROFILE%``, ``%APPDATA%``, ``~`` und ``$VAR`` auf."""
    text = str(value)

    def repl(m: re.Match) -> str:
        name = m.group(1)
        if name.upper() == "USERPROFILE" and name not in os.environ and "USERPROFILE" not in os.environ:
            return str(Path.home())
        return os.environ.get(name, os.environ.get(name.upper(), m.group(0)))

    text = re.sub(r"%([A-Za-z_][A-Za-z0-9_]*)%", repl, text)
    text = os.path.expandvars(os.path.expanduser(text))
    return Path(text)


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _check_no_secrets(data: Any, path: str = "") -> None:
    if isinstance(data, dict):
        for k, v in data.items():
            if FORBIDDEN_KEYS.search(str(k)):
                raise ConfigError(
                    f"Unzulässiger Konfigurationsschlüssel '{path}{k}': Zugangsdaten dürfen nicht in der "
                    "Konfiguration stehen (optionale API-Schlüssel nur über Umgebungsvariablen)."
                )
            _check_no_secrets(v, f"{path}{k}.")


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Konfigurationsdatei {path.name} ist kein gültiges YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Konfigurationsdatei {path.name} muss ein Mapping enthalten.")
    _check_no_secrets(data)
    return data


@dataclass
class Settings:
    data: dict = field(default_factory=lambda: copy.deepcopy(DEFAULTS))
    local_file: Path = LOCAL_CONFIG_FILE

    # ------------------------------------------------------------------ #
    @property
    def base_dir(self) -> Path:
        env = os.environ.get("KEST_TOOL_HOME")
        return expand_path(env) if env else expand_path(self.data["base_dir"])

    @property
    def db_path(self) -> Path:
        return self.base_dir / "database" / "kest_tool.db"

    @property
    def tax_years(self) -> list[int]:
        return sorted({int(y) for y in self.data.get("tax_years", [])})

    @property
    def default_tax_year(self) -> int:
        from datetime import date

        y = self.data.get("default_tax_year")
        return int(y) if y else date.today().year - 1

    @property
    def currencies(self) -> list[str]:
        return list(self.data.get("currencies", ["EUR"]))

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    # ------------------------------------------------------------------ #
    def save_local(self, changes: dict) -> None:
        """Speichert Benutzeränderungen in ``config.local.yaml`` (ohne Geheimnisse)."""
        _check_no_secrets(changes)
        current = _read_yaml(self.local_file)
        merged = _deep_merge(current, changes)
        self.local_file.parent.mkdir(parents=True, exist_ok=True)
        self.local_file.write_text(yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.data = _deep_merge(self.data, changes)

    def write_copy_to_base(self) -> Path:
        target = self.base_dir / "config" / "config.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        header = "# Wirksame Konfiguration des KESt-Tools (automatisch erzeugte Kopie)\n"
        target.write_text(header + yaml.safe_dump(self.data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return target


def load_settings(default_file: Path | None = None, local_file: Path | None = None) -> Settings:
    default_file = default_file or DEFAULT_CONFIG_FILE
    managed_home = os.environ.get("KEST_TOOL_HOME")
    explicit_local = local_file is not None
    local_file = local_file or (expand_path(managed_home) / "config" / "config.yaml"
                                if managed_home else LOCAL_CONFIG_FILE)
    data = _deep_merge(DEFAULTS, _read_yaml(default_file))
    # One-time compatibility with earlier installations; subsequent writes live in the data volume.
    if managed_home and not explicit_local and not local_file.exists():
        data = _deep_merge(data, _read_yaml(LOCAL_CONFIG_FILE))
    data = _deep_merge(data, _read_yaml(local_file))
    return Settings(data=data, local_file=local_file)


ENV_FILE = PROJECT_ROOT / ".env"


def env_file() -> Path:
    home = os.environ.get("KEST_TOOL_HOME")
    return expand_path(home) / "secrets" / ".env" if home else ENV_FILE


_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


def load_env_file(path: Path | None = None) -> None:
    """Lädt KEY=VALUE-Zeilen aus .env in die Umgebung (bestehende Variablen haben Vorrang)."""
    path = path or env_file()
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if _ENV_NAME.match(k) and k not in os.environ:
            os.environ[k] = v


def save_env_var(name: str, value: str, path: Path | None = None) -> None:
    """Setzt bzw. entfernt (leerer Wert) eine Variable in .env – für optionale API-Schlüssel, nie in config.yaml."""
    if not _ENV_NAME.match(name):
        raise ConfigError("Ungültiger Variablenname")
    if any(c in value for c in "\r\n"):
        raise ConfigError("Ungültiger Wert")
    path = path or env_file()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [l for l in lines if not l.strip().startswith(f"{name}=")]
    if value:
        lines.append(f"{name}={value}")
        os.environ[name] = value
    else:
        os.environ.pop(name, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
