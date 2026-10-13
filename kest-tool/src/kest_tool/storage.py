"""Zentrale Dokumentenablage.

Regeln:
- Originaldateien werden byte-identisch kopiert und danach nie verändert.
- Identität = SHA-256 der Dateibytes; erneuter Import derselben Datei legt keine Kopie an.
- Namenskonflikte (gleicher Name, anderer Inhalt) erhalten ein Suffix „(2)“, „(3)“ … – nie überschreiben.
- Alle Zielpfade werden gegen den Ablageordner geprüft (Schutz vor Pfadmanipulation).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .security import UnsafePathError, safe_join, sanitize_filename, sanitize_path_component

from .models import DOC_SOURCES

DOC_SOURCE_FOLDERS = list(DOC_SOURCES)
IMPORT_SUBDIRS = ["original", "processed", "import_logs"]
EXPORT_SUBDIRS = ["excel", "pdf", "csv", "e1kv"]
VIEWABLE_EXTENSIONS = {".pdf", ".csv", ".txt", ".xlsx", ".xls", ".zip", ".png", ".jpg", ".jpeg", ".json", ".log"}


class StorageError(OSError):
    """Verständliche Fehlermeldung für Dateisystemprobleme."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _friendly(exc: OSError, path: Path) -> StorageError:
    if isinstance(exc, PermissionError):
        return StorageError(f"Keine Schreibberechtigung für „{path}“. Ist die Datei in einem anderen Programm geöffnet "
                            "oder fehlt die Berechtigung für den Ordner?")
    if getattr(exc, "winerror", None) == 206 or "name too long" in str(exc).lower():
        return StorageError(f"Pfad zu lang: „{path}“. Bitte einen kürzeren Ablageordner wählen.")
    if "No space" in str(exc) or getattr(exc, "errno", None) == 28:
        return StorageError("Nicht genügend Speicherplatz auf dem Laufwerk.")
    return StorageError(f"Dateifehler bei „{path}“: {exc}")


class DocumentStore:
    def __init__(self, base_dir: Path, years: list[int] | None = None):
        self.base = Path(base_dir)
        self.years = years or []

    # ------------------------------------------------------------------ #
    def ensure_structure(self, years: list[int] | None = None) -> None:
        try:
            for sub in ("database", "config", "logs", "backups"):
                (self.base / sub).mkdir(parents=True, exist_ok=True)
            for y in years or self.years:
                self.ensure_year(int(y))
        except OSError as exc:
            raise _friendly(exc, self.base) from exc

    def ensure_year(self, year: int) -> None:
        y = str(int(year))
        for src in DOC_SOURCE_FOLDERS:
            (self.base / "documents" / y / src).mkdir(parents=True, exist_ok=True)
        for sub in IMPORT_SUBDIRS:
            (self.base / "imports" / y / sub).mkdir(parents=True, exist_ok=True)
        for sub in EXPORT_SUBDIRS:
            (self.base / "exports" / y / sub).mkdir(parents=True, exist_ok=True)
        (self.base / "reports" / y).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def document_dir(self, year: int | None, source: str) -> Path:
        source = source if source in DOC_SOURCE_FOLDERS else "Unclassified"
        year_part = str(int(year)) if year else "ohne_Jahr"
        return safe_join(self.base, "documents", year_part, source)

    def import_dir(self, year: int | None, sub: str) -> Path:
        if sub not in IMPORT_SUBDIRS:
            raise ValueError(sub)
        return safe_join(self.base, "imports", str(int(year)) if year else "ohne_Jahr", sub)

    def export_dir(self, year: int, sub: str) -> Path:
        if sub not in EXPORT_SUBDIRS:
            raise ValueError(sub)
        d = safe_join(self.base, "exports", str(int(year)), sub)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def report_dir(self, year: int) -> Path:
        d = safe_join(self.base, "reports", str(int(year)))
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _assert_inside(self, path: Path) -> None:
        try:
            Path(path).resolve().relative_to(self.base.resolve())
        except ValueError as exc:
            raise UnsafePathError(f"Pfad liegt außerhalb des Ablageordners: {path}") from exc

    def relative(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.base.resolve()).as_posix()

    def absolute(self, stored_path: str) -> Path:
        """Wandelt einen in der Datenbank gespeicherten relativen Pfad sicher in einen absoluten um."""
        parts = Path(stored_path.replace("\\", "/")).parts
        if any(p in ("..",) for p in parts) or Path(stored_path).is_absolute():
            raise UnsafePathError(f"Ungültiger gespeicherter Pfad: {stored_path}")
        return safe_join(self.base, *parts)

    # ------------------------------------------------------------------ #
    @staticmethod
    def unique_target(directory: Path, filename: str) -> Path:
        """Freier Dateiname im Ordner – vorhandene Dateien werden nie überschrieben."""
        name = sanitize_filename(filename)
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem, ext = name, ""
        candidate = directory / name
        n = 2
        while candidate.exists():
            candidate = directory / (f"{stem} ({n}).{ext}" if ext else f"{stem} ({n})")
            n += 1
        return candidate

    def write_new_file(self, directory: Path, filename: str, data: bytes) -> Path:
        """Schreibt atomar in eine neue Datei (exklusiv angelegt)."""
        try:
            directory.mkdir(parents=True, exist_ok=True)
            self._assert_inside(directory)
            target = self.unique_target(directory, filename)
            fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=".tmp_", suffix=".part")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                # os.link + unlink würde auf manchen Dateisystemen fehlen; exklusiver Check direkt davor
                if target.exists():
                    target = self.unique_target(directory, filename)
                os.replace(tmp, target)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
            return target
        except OSError as exc:
            raise _friendly(exc, directory) from exc

    def store_document(self, data: bytes, filename: str, year: int | None, source: str) -> Path:
        directory = self.document_dir(year, source)
        return self.write_new_file(directory, filename, data)

    def move_document(self, stored_path: str, year: int | None, source: str) -> Path:
        """Verschiebt eine abgelegte Datei in einen anderen Jahres-/Quellenordner (Inhalt bleibt unverändert)."""
        src = self.absolute(stored_path)
        if not src.exists():
            raise StorageError(f"Datei nicht gefunden: {stored_path}")
        directory = self.document_dir(year, source)
        directory.mkdir(parents=True, exist_ok=True)
        if src.parent.resolve() == directory.resolve():
            return src
        target = self.unique_target(directory, src.name)
        before = sha256_file(src)
        try:
            shutil.move(str(src), str(target))
        except OSError as exc:
            raise _friendly(exc, target) from exc
        if sha256_file(target) != before:  # pragma: no cover - Sicherheitsnetz
            raise StorageError("Prüfsumme nach dem Verschieben stimmt nicht überein")
        return target

    # ------------------------------------------------------------------ #
    @staticmethod
    def open_in_os(path: Path) -> None:
        """Öffnet eine Datei mit dem Standardprogramm (nur lokal). Es wird nichts ausgeführt außer dem Viewer."""
        path = Path(path)
        if not path.exists():
            raise StorageError(f"Datei nicht gefunden: {path}")
        if path.suffix.lower() not in VIEWABLE_EXTENSIONS:
            raise StorageError(f"Dateityp {path.suffix} wird aus Sicherheitsgründen nicht geöffnet")
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607


def safe_component(value: str) -> str:
    return sanitize_path_component(value)
