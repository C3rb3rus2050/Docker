"""Download-Engine: Prüfung, Wiederholung, sichere Speicherung, Duplikaterkennung.

Die eigentliche Übertragung erfolgt immer über die angemeldete Browsersitzung
(der Adapter liefert die Bytes). Diese Engine ist dafür zuständig, dass

- nur gültige Dateien gespeichert werden (Signaturprüfung, keine HTML-Fehlerseiten als PDF),
- Größenlimits eingehalten werden,
- temporäre Fehler mit Backoff wiederholt werden,
- Dateien atomar und ohne Überschreiben in die Zielstruktur geschrieben werden,
- identische Inhalte (SHA-256) nicht doppelt gespeichert werden.
"""

from __future__ import annotations

import logging
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeVar

from .broker_adapter import DocumentRef, DownloadedFile, DownloadError, ScanCancelled
from .classifier import Classification, Classifier
from .database import Database, utcnow
from .deduplication import Deduplicator
from .security import safe_join, sanitize_filename, sanitize_path_component

log = logging.getLogger(__name__)
T = TypeVar("T")

BROKER_FOLDERS = {"trade_republic": "TradeRepublic", "scalable_capital": "ScalableCapital"}

# --------------------------------------------------------------------------- #
# Dateisignaturen
# --------------------------------------------------------------------------- #

ALLOWED_FORMATS = ("pdf", "zip", "csv", "txt", "xml", "json", "png", "jpg")


class FileValidationError(DownloadError):
    def __init__(self, message: str):
        super().__init__(message, retryable=False, status="invalid")


def detect_format(data: bytes) -> str:
    """Erkennt das Dateiformat anhand der Bytes (nicht anhand von Namen oder Headern)."""
    head = data[:2048]
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        return "zip"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    low = stripped[:512].lower()
    if low.startswith((b"<!doctype html", b"<html", b"<head", b"<body")) or b"<html" in low[:256]:
        return "html"
    if b"%PDF-" in head[:1024]:  # PDF-Spezifikation erlaubt Header innerhalb der ersten 1024 Bytes
        return "pdf"
    if low.startswith(b"<?xml"):
        return "xml"
    if low.startswith((b"{", b"[")):
        return "json"
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = head.decode("cp1252")
        except UnicodeDecodeError:
            return "binary"
    if "\x00" in text:
        return "binary"
    lines = [ln for ln in text.splitlines() if ln.strip()][:5]
    if lines and all(ln.count(";") >= 1 or ln.count(",") >= 1 or ln.count("\t") >= 1 for ln in lines):
        return "csv"
    return "txt"


def validate_file(data: bytes, expected: str | None, max_bytes: int, content_type: str = "") -> str:
    """Prüft Größe und Signatur. Gibt das erkannte Format zurück oder wirft FileValidationError."""
    if not data:
        raise FileValidationError("Leere Datei erhalten")
    if len(data) > max_bytes:
        raise FileValidationError(f"Datei zu groß ({len(data)} Bytes, Limit {max_bytes})")
    fmt = detect_format(data)
    if fmt == "html":
        raise FileValidationError("HTML-Seite statt Dokument erhalten (vermutlich Fehler- oder Loginseite)")
    if fmt == "pdf":
        if len(data) < 64:
            raise FileValidationError("PDF unvollständig (zu klein)")
        tail = data[-2048:]
        if b"%%EOF" not in tail:
            raise FileValidationError("PDF unvollständig oder beschädigt (kein %%EOF am Dateiende)")
    if expected == "pdf" and fmt != "pdf":
        raise FileValidationError(f"Als PDF angeboten, aber Inhalt ist '{fmt}'")
    if fmt not in ALLOWED_FORMATS:
        raise FileValidationError(f"Nicht unterstütztes Dateiformat: {fmt}")
    if "text/html" in (content_type or "").lower() and fmt in ("txt", "csv"):
        raise FileValidationError("Server lieferte text/html statt Dokument")
    return fmt


# --------------------------------------------------------------------------- #
# Wiederholungslogik
# --------------------------------------------------------------------------- #


def retry_call(
    fn: Callable[[], T],
    attempts: int = 3,
    backoff_s: float = 2.0,
    is_retryable: Callable[[BaseException], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """Führt ``fn`` aus und wiederholt bei temporären Fehlern mit exponentiellem Backoff."""

    def default_retryable(exc: BaseException) -> bool:
        if isinstance(exc, ScanCancelled):
            return False
        if isinstance(exc, DownloadError):
            return exc.retryable
        return isinstance(exc, (TimeoutError, ConnectionError, OSError))

    check = is_retryable or default_retryable
    last: BaseException | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 - bewusst breit, Entscheidung über check()
            last = exc
            if attempt >= attempts or not check(exc):
                raise
            if on_retry:
                on_retry(attempt, exc)
            delay = backoff_s * (2 ** (attempt - 1)) * (1 + random.uniform(0, 0.25))
            sleep(delay)
    assert last is not None  # pragma: no cover
    raise last  # pragma: no cover


def is_retryable_http(status: int | None) -> bool:
    return status in (408, 425, 429, 500, 502, 503, 504)


# --------------------------------------------------------------------------- #
# Speicherung
# --------------------------------------------------------------------------- #


@dataclass
class StoreResult:
    status: str  # downloaded | duplicate | failed | invalid | not_downloadable
    document_id: int | None = None
    sha256: str = ""
    local_path: str = ""
    error: str = ""
    classification: Classification | None = None
    extra: dict[str, Any] = field(default_factory=dict)


_EXT_FOR_FORMAT = {"pdf": ".pdf", "zip": ".zip", "csv": ".csv", "txt": ".txt", "xml": ".xml", "json": ".json",
                   "png": ".png", "jpg": ".jpg"}


class DocumentStore:
    """Speichert geprüfte Dateien in ``<Ausgabe>/<Broker>/<Kategorie>/<Jahr>/``."""

    def __init__(self, output_dir: Path, db: Database, classifier: Classifier, max_bytes: int):
        self.output_dir = Path(output_dir)
        self.db = db
        self.classifier = classifier
        self.max_bytes = max_bytes
        self.dedup = Deduplicator(db)

    def target_dir(self, broker: str, folder: str, year: str | None) -> Path:
        parts = [BROKER_FOLDERS.get(broker, sanitize_path_component(broker)), sanitize_path_component(folder)]
        if year and re.fullmatch(r"(19|20)\d{2}", year):
            parts.append(year)
        target = safe_join(self.output_dir, *parts)
        target.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def unique_path(directory: Path, filename: str) -> Path:
        """Nie überschreiben: bei Namenskollision mit anderem Inhalt Suffix anhängen."""
        candidate = safe_join(directory, filename)
        if not candidate.exists():
            return candidate
        stem, ext = os.path.splitext(filename)
        for i in range(2, 10_000):
            candidate = safe_join(directory, f"{stem} ({i}){ext}")
            if not candidate.exists():
                return candidate
        raise DownloadError("Kein freier Dateiname gefunden")

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        fd, tmp = tempfile.mkstemp(prefix=".bdc-", suffix=".part", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            # os.link + unlink würde unter Windows nicht überall funktionieren; wir prüfen vorher,
            # dass das Ziel nicht existiert, und benennen dann exklusiv um.
            if path.exists():
                raise FileExistsError(str(path))
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def build_filename(self, ref: DocumentRef, file: DownloadedFile, fmt: str, cls: Classification) -> str:
        base = file.original_name or ref.title or "dokument"
        name = sanitize_filename(base)
        stem, ext = os.path.splitext(name)
        wanted_ext = _EXT_FOR_FORMAT.get(fmt, ext or ".bin")
        if ext.lower() != wanted_ext:
            # Endung an den tatsächlichen Inhalt anpassen (Inhalt bleibt unverändert)
            stem = name if ext.lower() not in _EXT_FOR_FORMAT.values() else stem
            name = sanitize_filename(stem + wanted_ext)
        date = cls.doc_date or ref.date
        if date and not name.startswith(date):
            name = sanitize_filename(f"{date}_{name}")
        return name

    def store(self, ref: DocumentRef, file: DownloadedFile, expected_format: str | None = None) -> StoreResult:
        fmt = validate_file(file.data, expected_format, self.max_bytes, file.content_type)
        dedup = self.dedup.check(file.data)
        if dedup.is_duplicate and dedup.existing:
            self.dedup.register_alternative(dedup.existing["id"], ref, file.original_name)
            log.info("Duplikat erkannt (sha256=%s…): %s", dedup.sha256[:12], ref.title)
            return StoreResult("duplicate", dedup.existing["id"], dedup.sha256, dedup.existing.get("local_path") or "")

        cls = self.classifier.classify(
            title=ref.title, filename=file.original_name, list_date=ref.date, type_hint=ref.doc_type_hint,
            data=file.data if fmt == "pdf" else None,
        )
        year = (cls.doc_date or ref.date or "")[:4] or cls.year or None
        directory = self.target_dir(ref.broker, cls.folder, year)
        filename = self.build_filename(ref, file, fmt, cls)
        path = self.unique_path(directory, filename)
        self._atomic_write(path, file.data)

        if dedup.existing:  # Datensatz existierte, Datei war lokal gelöscht → wiederherstellen
            self.db.execute(
                "UPDATE documents SET local_path=?, downloaded_at=?, download_status='downloaded' WHERE id=?",
                (str(path), utcnow(), dedup.existing["id"]),
            )
            self.db.add_location(dedup.existing["id"], ref, file.original_name)
            return StoreResult("downloaded", dedup.existing["id"], dedup.sha256, str(path), classification=cls)

        doc_id = self.db.insert_document(
            broker=ref.broker, doc_key=ref.key, original_name=file.original_name or ref.title,
            local_path=str(path), sha256=dedup.sha256, file_size=len(file.data), file_format=fmt,
            doc_type=cls.category, doc_type_confidence=cls.confidence, doc_date=cls.doc_date or ref.date or None,
            downloaded_at=utcnow(), source_url=file.source_url or ref.url, page_url=ref.page_url,
            download_status="downloaded", error_message=None,
        )
        self.db.add_location(doc_id, ref, file.original_name)
        log.info("Gespeichert: %s (%s, sha256=%s…)", path.name, cls.category, dedup.sha256[:12])
        return StoreResult("downloaded", doc_id, dedup.sha256, str(path), classification=cls)


def guess_filename_from_headers(headers: dict[str, str], url: str = "", fallback: str = "dokument") -> str:
    """Dateiname aus Content-Disposition oder URL-Pfad (immer bereinigt)."""
    cd = ""
    for k, v in (headers or {}).items():
        if k.lower() == "content-disposition":
            cd = v
            break
    if cd:
        m = re.search(r"filename\*\s*=\s*(?:UTF-8'')?([^;]+)", cd, re.IGNORECASE)
        if m:
            from urllib.parse import unquote

            return sanitize_filename(unquote(m.group(1).strip().strip('"')), fallback)
        m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.IGNORECASE)
        if m:
            return sanitize_filename(m.group(1).strip(), fallback)
    if url and not url.startswith("blob:"):
        from urllib.parse import unquote, urlsplit

        last = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        if last and "." in last:
            return sanitize_filename(last, fallback)
    return sanitize_filename(fallback)
