"""Sicherheitsfunktionen: Dateinamen, Pfade, Redaktion sensibler Daten (eigenständige Kopie für das KESt-Tool).

Dieses Modul hat keine Abhängigkeiten zu Playwright und ist vollständig testbar.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# --------------------------------------------------------------------------- #
# Dateinamen und Pfade
# --------------------------------------------------------------------------- #

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
MAX_FILENAME_LENGTH = 150


class UnsafePathError(ValueError):
    """Ein Pfad würde den erlaubten Basisordner verlassen."""


def sanitize_filename(name: str | None, default: str = "dokument", max_length: int = MAX_FILENAME_LENGTH) -> str:
    """Erzeugt einen unter Windows gültigen, ungefährlichen Dateinamen.

    - entfernt Pfadanteile (Directory Traversal: ``../``, ``C:\\``, ``\\\\server``)
    - entfernt Steuer- und unter Windows ungültige Zeichen
    - vermeidet reservierte Gerätenamen (CON, NUL, COM1 …)
    - entfernt führende/abschließende Punkte und Leerzeichen
    - begrenzt die Länge unter Erhalt der Dateiendung
    """
    if not name:
        return default
    name = unicodedata.normalize("NFC", str(name))
    # Nur den letzten Pfadbestandteil verwenden – egal ob / oder \ als Trenner.
    name = re.split(r"[\\/]", name)[-1]
    name = _INVALID_CHARS.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    name = re.sub(r"_+", "_", name)
    if not name or set(name) <= {"_", "."}:
        return default
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if not re.fullmatch(r"[A-Za-z0-9]{1,8}", ext or "x"):
        stem, ext = name, ""
    if stem.split(".")[0].upper() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    if not stem:
        stem = default
    ext_part = f".{ext.lower()}" if ext else ""
    room = max(1, max_length - len(ext_part))
    return stem[:room].rstrip(" .") + ext_part or default


def sanitize_path_component(value: str | None, default: str = "Sonstige") -> str:
    """Bereinigt einen einzelnen Ordnernamen (z. B. Kategorie, Jahr)."""
    cleaned = sanitize_filename(value, default=default, max_length=60)
    return cleaned.replace(".", "_") if cleaned.startswith(".") else cleaned


def safe_join(base: Path | str, *parts: str) -> Path:
    """Verbindet Pfade und stellt sicher, dass das Ergebnis innerhalb von ``base`` bleibt."""
    base_path = Path(base).resolve()
    candidate = base_path.joinpath(*parts).resolve()
    try:
        candidate.relative_to(base_path)
    except ValueError as exc:
        raise UnsafePathError(f"Pfad verlässt den Basisordner: {candidate}") from exc
    return candidate


# --------------------------------------------------------------------------- #
# URL-Prüfung
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UrlPolicy:
    """Erlaubte Hosts für Navigation und Downloads eines Brokers.

    ``allowed_suffixes``: Host muss gleich dem Eintrag sein oder auf ``.<eintrag>`` enden.
    ``allowed_patterns``: reguläre Ausdrücke für zusätzliche Hosts (z. B. Dokumentenspeicher).
    """

    allowed_suffixes: tuple[str, ...]
    allowed_patterns: tuple[str, ...] = ()

    def host_allowed(self, host: str) -> bool:
        host = (host or "").lower().rstrip(".")
        if not host:
            return False
        for suffix in self.allowed_suffixes:
            suffix = suffix.lower().lstrip(".")
            if host == suffix or host.endswith("." + suffix):
                return True
        return any(re.fullmatch(p, host) for p in self.allowed_patterns)


class UrlValidationError(ValueError):
    pass


def validate_url(url: str, policy: UrlPolicy | None = None, allow_blob: bool = False) -> str:
    """Prüft eine URL vor Navigation oder Download.

    Erlaubt nur ``https`` (optional ``blob:`` innerhalb der Brokerseite), keine
    eingebetteten Zugangsdaten, keine IP-Adressen/localhost und nur Hosts der Policy.
    Gibt die URL unverändert zurück oder wirft ``UrlValidationError``.
    """
    if not url or not isinstance(url, str):
        raise UrlValidationError("Leere URL")
    if len(url) > 8192:
        raise UrlValidationError("URL zu lang")
    if any(ch in url for ch in "\r\n\t\x00"):
        raise UrlValidationError("URL enthält Steuerzeichen")
    if url.startswith("blob:"):
        if not allow_blob:
            raise UrlValidationError("blob:-URL hier nicht erlaubt")
        inner = url[5:]
        validate_url(inner, policy, allow_blob=False)
        return url
    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        raise UrlValidationError(f"Nur HTTPS erlaubt (gefunden: {parts.scheme or 'kein Schema'})")
    if parts.username or parts.password:
        raise UrlValidationError("URL mit eingebetteten Zugangsdaten abgelehnt")
    host = (parts.hostname or "").lower()
    if not host:
        raise UrlValidationError("URL ohne Host")
    if host == "localhost" or host.endswith(".localhost"):
        raise UrlValidationError("localhost nicht erlaubt")
    try:
        ipaddress.ip_address(host.strip("[]"))
        raise UrlValidationError("IP-Adressen als Host nicht erlaubt")
    except ValueError as exc:
        if isinstance(exc, UrlValidationError):
            raise
    if policy is not None and not policy.host_allowed(host):
        raise UrlValidationError(f"Host nicht erlaubt: {host}")
    return url


def url_without_query(url: str) -> str:
    """Stabile URL-Basis ohne Query/Fragment (z. B. für vorab signierte Links)."""
    try:
        p = urlsplit(url)
    except ValueError:
        return url
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


# --------------------------------------------------------------------------- #
# Redaktion sensibler Daten (Logs, Fehlermeldungen, Berichte, Datenbank)
# --------------------------------------------------------------------------- #

SENSITIVE_PARAM_PATTERN = re.compile(
    r"(token|auth|session|sess|sid|cookie|key|secret|signature|sig|password|passwd|pwd|pin|code|"
    r"credential|jwt|bearer|x-amz-[a-z-]+|expires|policy|otp|nonce|state)",
    re.IGNORECASE,
)

_REDACT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization / Cookie Header
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+|basic\s+)?[^\s,;\"']+"), r"\1\2[REDACTED]"),
    (re.compile(r"(?i)((?:set-)?cookie\s*[:=]\s*)[^\n\"']+"), r"\1[REDACTED]"),
    # JSON-ähnliche Schlüssel: "sessionToken": "..." / 'password': '...'
    (
        re.compile(
            r"(?i)([\"']?(?:[a-z_]*token|password|passwd|pin|session[a-z_]*|cookie|secret|refresh[a-z_]*|"
            r"access[a-z_]*|api[_-]?key|jwt)[\"']?\s*[:=]\s*[\"']?)([^\"',;\s}]+)"
        ),
        r"\1[REDACTED]",
    ),
    # JWTs
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED_JWT]"),
    # Lange Hex/Base64-Blöcke, die wie Geheimnisse aussehen (aber keine SHA-256-Hashes in Klartextform
    # mit Präfix sha256=, die wir bewusst protokollieren)
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{10,}"), "Bearer [REDACTED]"),
    # Telefonnummern im internationalen Format (Trade-Republic-Login nutzt Telefonnummern)
    (re.compile(r"\+\d{2}\s?\d{3,4}[\s\d]{5,12}"), "[REDACTED_PHONE]"),
]

_URL_IN_TEXT = re.compile(r"(?:https?|wss?)://[^\s\"'<>]+")


def redact_url(url: str) -> str:
    """Entfernt Werte sensibler Query-Parameter und Fragmente aus einer URL."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[UNPARSEABLE_URL]"
    if not parts.query and not parts.fragment and "@" not in parts.netloc:
        return url
    netloc = parts.netloc.rsplit("@", 1)[-1]
    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if SENSITIVE_PARAM_PATTERN.search(key) or len(value) > 64:
            query_items.append((key, "REDACTED"))
        else:
            query_items.append((key, value))
    fragment = "REDACTED" if parts.fragment else ""
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query_items, safe="[]"), fragment))


def redact(text: object) -> str:
    """Redigiert sensible Inhalte in beliebigem Text (Logs, Fehlermeldungen)."""
    if text is None:
        return ""
    s = str(text)
    s = _URL_IN_TEXT.sub(lambda m: redact_url(m.group(0)), s)
    for pattern, repl in _REDACT_PATTERNS:
        s = pattern.sub(repl, s)
    return s


class RedactingFilter(logging.Filter):
    """Logging-Filter, der jede Meldung vor der Ausgabe redigiert."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


# --------------------------------------------------------------------------- #
# Löschen sensibler Daten
# --------------------------------------------------------------------------- #


def remove_tree(path: Path, must_be_inside: Iterable[Path] = ()) -> bool:
    """Löscht einen Ordner rekursiv – nur, wenn er existiert und (optional) in einem
    erwarteten Basisordner liegt. Gibt ``True`` zurück, wenn etwas gelöscht wurde."""
    path = Path(path)
    if not path.exists():
        return False
    resolved = path.resolve()
    if resolved == Path(resolved.anchor):
        raise UnsafePathError("Löschen des Laufwerksstamms verweigert")
    bases = [Path(b).resolve() for b in must_be_inside]
    if bases and not any(resolved == b or b in resolved.parents for b in bases):
        raise UnsafePathError(f"Ordner liegt außerhalb der erlaubten Basis: {resolved}")
    if resolved.is_file():
        resolved.unlink()
    else:
        shutil.rmtree(resolved)
    return True


def is_probably_cloud_synced(path: Path) -> bool:
    """Grobe Erkennung, ob ein Ordner in einem Cloud-Sync-Verzeichnis liegt (OneDrive & Co.).

    Unter Windows 11 ist ``Dokumente`` häufig per OneDrive synchronisiert – das würde
    Dokumente in die Cloud übertragen. Die UI warnt in diesem Fall.
    """
    text = str(Path(path)).lower()
    markers = ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "nextcloud", "owncloud")
    if any(m in text for m in markers):
        return True
    for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        root = os.environ.get(env)
        if root and text.startswith(root.lower()):
            return True
    return False
