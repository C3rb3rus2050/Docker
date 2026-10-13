"""SHA-256-basierte Duplikaterkennung.

Identität eines Dokuments = SHA-256 über die tatsächlichen Dateibytes. Dateinamen,
Titel oder Datumsangaben werden NIE allein als Duplikatkriterium verwendet.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .database import Database

CHUNK = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class DedupResult:
    is_duplicate: bool
    sha256: str
    existing: dict[str, Any] | None = None


class Deduplicator:
    def __init__(self, db: Database):
        self.db = db

    def check(self, data: bytes) -> DedupResult:
        digest = sha256_bytes(data)
        existing = self.db.find_document_by_hash(digest)
        if existing and existing.get("local_path") and not Path(existing["local_path"]).exists():
            # Datei wurde lokal gelöscht: Inhalt erneut speichern (gleicher Datensatz).
            return DedupResult(False, digest, existing)
        return DedupResult(existing is not None, digest, existing)

    def register_alternative(self, document_id: int, ref: Any, original_name: str) -> None:
        """Weitere Fundstelle desselben Inhalts als Metadaten speichern."""
        self.db.add_location(document_id, ref, original_name)
