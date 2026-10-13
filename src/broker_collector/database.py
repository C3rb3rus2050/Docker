"""SQLite-Persistenz für Dokumente, Scanläufe, Scanelemente, Bereiche und Quellen-Abgleich.

Die Datenbank enthält niemals Passwörter, Cookies oder Sessiontokens. Alle URLs werden
vor dem Speichern mit :func:`security.redact_url` bereinigt (vorab signierte Links
enthalten Signaturen in Query-Parametern).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .security import redact, redact_url

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    doc_key TEXT UNIQUE,
    original_name TEXT,
    local_path TEXT,
    sha256 TEXT UNIQUE,
    file_size INTEGER,
    file_format TEXT,
    doc_type TEXT,
    doc_type_confidence REAL,
    doc_date TEXT,
    downloaded_at TEXT,
    source_url TEXT,
    page_url TEXT,
    download_status TEXT NOT NULL,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_broker ON documents(broker);

CREATE TABLE IF NOT EXISTS document_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    broker TEXT NOT NULL,
    doc_key TEXT NOT NULL,
    source TEXT,
    title TEXT,
    original_name TEXT,
    doc_date TEXT,
    source_url TEXT,
    page_url TEXT,
    found_at TEXT,
    UNIQUE(document_id, doc_key)
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    pages_visited INTEGER DEFAULT 0,
    documents_found INTEGER DEFAULT 0,
    downloaded INTEGER DEFAULT 0,
    duplicates INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    skipped_known INTEGER DEFAULT 0,
    inaccessible_areas TEXT DEFAULT '[]',
    message TEXT,
    resumed_from INTEGER
);

CREATE TABLE IF NOT EXISTS scan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker TEXT NOT NULL,
    doc_key TEXT NOT NULL,
    run_id INTEGER,
    page_url TEXT,
    external_id TEXT,
    title TEXT,
    source TEXT,
    area TEXT,
    doc_date TEXT,
    status TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    last_attempt TEXT,
    error_message TEXT,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    UNIQUE(broker, doc_key)
);
CREATE INDEX IF NOT EXISTS idx_scan_items_status ON scan_items(broker, status);

CREATE TABLE IF NOT EXISTS areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
    broker TEXT NOT NULL,
    area_key TEXT NOT NULL,
    name TEXT,
    url TEXT,
    source TEXT,
    kind TEXT,
    status TEXT NOT NULL,
    pages_visited INTEGER DEFAULT 0,
    periods TEXT DEFAULT '[]',
    note TEXT,
    UNIQUE(run_id, area_key)
);

CREATE TABLE IF NOT EXISTS run_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
    broker TEXT NOT NULL,
    doc_key TEXT NOT NULL,
    title TEXT,
    area TEXT,
    source TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    document_id INTEGER,
    UNIQUE(run_id, doc_key)
);

CREATE TABLE IF NOT EXISTS markers (
    broker TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    seen_at TEXT,
    PRIMARY KEY (broker, kind, key)
);

CREATE TABLE IF NOT EXISTS source_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
    broker TEXT NOT NULL,
    source TEXT NOT NULL,
    doc_key TEXT NOT NULL,
    title TEXT,
    doc_date TEXT,
    url_base TEXT,
    external_id TEXT,
    UNIQUE(run_id, source, doc_key)
);
"""

ITEM_FINAL_OK = ("downloaded", "duplicate")


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
        )

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.lastrowid or cur.rowcount

    # ------------------------------------------------------------------ #
    # Scanläufe
    # ------------------------------------------------------------------ #
    def start_run(self, broker: str, mode: str, resumed_from: int | None = None) -> int:
        return self.execute(
            "INSERT INTO scan_runs(broker, mode, started_at, status, resumed_from) VALUES (?,?,?,?,?)",
            (broker, mode, utcnow(), "running", resumed_from),
        )

    def update_run(self, run_id: int, **fields: Any) -> None:
        if not fields:
            return
        if "inaccessible_areas" in fields and not isinstance(fields["inaccessible_areas"], str):
            fields["inaccessible_areas"] = json.dumps(fields["inaccessible_areas"], ensure_ascii=False)
        if "message" in fields:
            fields["message"] = redact(fields["message"])
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.execute(f"UPDATE scan_runs SET {cols} WHERE id = ?", (*fields.values(), run_id))

    def finish_run(self, run_id: int, status: str, message: str = "") -> None:
        self.update_run(run_id, status=status, finished_at=utcnow(), message=message)

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        return self.query_one("SELECT * FROM scan_runs WHERE id = ?", (run_id,))

    def last_run(self, broker: str | None = None) -> dict[str, Any] | None:
        if broker:
            return self.query_one("SELECT * FROM scan_runs WHERE broker = ? ORDER BY id DESC LIMIT 1", (broker,))
        return self.query_one("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1")

    def interrupted_run(self, broker: str) -> dict[str, Any] | None:
        """Letzter nicht regulär beendeter Lauf (für Fortsetzung)."""
        return self.query_one(
            "SELECT * FROM scan_runs WHERE broker = ? AND status IN ('running','interrupted','cancelled',"
            "'waiting_user','failed') ORDER BY id DESC LIMIT 1",
            (broker,),
        )

    def mark_stale_runs_interrupted(self) -> int:
        """Beim Programmstart: Läufe mit Status 'running' wurden hart unterbrochen."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE scan_runs SET status='interrupted', finished_at=? WHERE status IN ('running','waiting_user')",
                (utcnow(),),
            )
            return cur.rowcount

    def recompute_run_counters(self, run_id: int) -> dict[str, int]:
        rows = self.query(
            "SELECT status, COUNT(*) AS n FROM run_results WHERE run_id = ? GROUP BY status", (run_id,)
        )
        counts = {r["status"]: r["n"] for r in rows}
        pages = self.query_one("SELECT COALESCE(SUM(pages_visited),0) AS p FROM areas WHERE run_id = ?", (run_id,))
        result = {
            "documents_found": sum(counts.values()),
            "downloaded": counts.get("downloaded", 0),
            "duplicates": counts.get("duplicate", 0),
            "failed": counts.get("failed", 0) + counts.get("invalid", 0) + counts.get("not_downloadable", 0),
            "skipped_known": counts.get("skipped_known", 0),
            "pages_visited": int(pages["p"]) if pages else 0,
        }
        self.update_run(run_id, **result)
        return result

    # ------------------------------------------------------------------ #
    # Bereiche
    # ------------------------------------------------------------------ #
    def upsert_area(self, run_id: int, broker: str, area: Any) -> None:
        self.execute(
            """INSERT INTO areas(run_id, broker, area_key, name, url, source, kind, status, pages_visited, periods, note)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(run_id, area_key) DO UPDATE SET status=excluded.status,
                 pages_visited=excluded.pages_visited, periods=excluded.periods, note=excluded.note""",
            (
                run_id, broker, area.key, area.name, redact_url(area.url or ""), area.source, area.kind,
                area.status, area.pages_visited, json.dumps(area.periods, ensure_ascii=False), redact(area.note),
            ),
        )

    def areas_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.query("SELECT * FROM areas WHERE run_id = ? ORDER BY id", (run_id,))
        for r in rows:
            r["periods"] = json.loads(r["periods"] or "[]")
        return rows

    def completed_area_keys(self, run_id: int) -> set[str]:
        return {
            r["area_key"]
            for r in self.query("SELECT area_key FROM areas WHERE run_id = ? AND status = 'complete'", (run_id,))
        }

    # ------------------------------------------------------------------ #
    # Scanelemente
    # ------------------------------------------------------------------ #
    def get_item(self, broker: str, doc_key: str) -> dict[str, Any] | None:
        return self.query_one("SELECT * FROM scan_items WHERE broker = ? AND doc_key = ?", (broker, doc_key))

    def record_item(
        self,
        run_id: int,
        ref: Any,
        status: str,
        error: str = "",
        document_id: int | None = None,
        count_attempt: bool = False,
    ) -> None:
        """Speichert das Ergebnis eines Dokuments: dauerhaft (scan_items) und je Lauf (run_results).

        ``skipped_known`` verändert den dauerhaften Status nicht (Dokument bleibt "downloaded")."""
        now = utcnow()
        err = redact(error) if error else None
        with self.transaction() as conn:
            if status == "skipped_known":
                conn.execute(
                    "UPDATE scan_items SET run_id=? WHERE broker=? AND doc_key=?", (run_id, ref.broker, ref.key)
                )
            else:
                conn.execute(
                    """INSERT INTO scan_items(broker, doc_key, run_id, page_url, external_id, title, source, area,
                                              doc_date, status, attempts, last_attempt, error_message, document_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(broker, doc_key) DO UPDATE SET
                         run_id=excluded.run_id, page_url=excluded.page_url, title=excluded.title,
                         source=excluded.source, area=excluded.area,
                         doc_date=COALESCE(excluded.doc_date, scan_items.doc_date),
                         status=excluded.status,
                         attempts=scan_items.attempts + excluded.attempts,
                         last_attempt=COALESCE(excluded.last_attempt, scan_items.last_attempt),
                         error_message=excluded.error_message,
                         document_id=COALESCE(excluded.document_id, scan_items.document_id)""",
                    (
                        ref.broker, ref.key, run_id, redact_url(ref.page_url or ""), ref.external_id or None,
                        ref.title, ref.source, ref.area, ref.date or None, status, 1 if count_attempt else 0,
                        now if count_attempt else None, err, document_id,
                    ),
                )
            conn.execute(
                """INSERT INTO run_results(run_id, broker, doc_key, title, area, source, status, error_message,
                                           document_id) VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(run_id, doc_key) DO UPDATE SET status=excluded.status,
                     error_message=excluded.error_message, document_id=excluded.document_id""",
                (run_id, ref.broker, ref.key, ref.title, ref.area, ref.source, status, err, document_id),
            )

    def run_results(self, run_id: int, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return self.query("SELECT * FROM run_results WHERE run_id = ? AND status = ? ORDER BY id",
                              (run_id, status))
        return self.query("SELECT * FROM run_results WHERE run_id = ? ORDER BY id", (run_id,))

    # ------------------------------------------------------------------ #
    # Marker (z. B. bereits ausgewertete Timeline-Ereignisse)
    # ------------------------------------------------------------------ #
    def add_markers(self, broker: str, kind: str, keys: Any) -> None:
        now = utcnow()
        with self.transaction() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO markers(broker, kind, key, seen_at) VALUES (?,?,?,?)",
                [(broker, kind, str(k), now) for k in keys],
            )

    def markers(self, broker: str, kind: str) -> set[str]:
        return {r["key"] for r in self.query("SELECT key FROM markers WHERE broker=? AND kind=?", (broker, kind))}

    def items_for_run(self, run_id: int, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            return self.query("SELECT * FROM scan_items WHERE run_id = ? AND status = ? ORDER BY id", (run_id, status))
        return self.query("SELECT * FROM scan_items WHERE run_id = ? ORDER BY id", (run_id,))

    def failed_items(self, broker: str) -> list[dict[str, Any]]:
        return self.query(
            "SELECT * FROM scan_items WHERE broker = ? AND status IN ('failed','found') ORDER BY id", (broker,)
        )

    # ------------------------------------------------------------------ #
    # Dokumente
    # ------------------------------------------------------------------ #
    def find_document_by_hash(self, sha256: str) -> dict[str, Any] | None:
        return self.query_one("SELECT * FROM documents WHERE sha256 = ?", (sha256,))

    def find_document_by_key(self, doc_key: str) -> dict[str, Any] | None:
        doc = self.query_one("SELECT * FROM documents WHERE doc_key = ?", (doc_key,))
        if doc:
            return doc
        return self.query_one(
            "SELECT d.* FROM documents d JOIN document_locations l ON l.document_id = d.id WHERE l.doc_key = ?",
            (doc_key,),
        )

    def insert_document(self, **fields: Any) -> int:
        fields = dict(fields)
        for url_field in ("source_url", "page_url"):
            if fields.get(url_field):
                fields[url_field] = redact_url(fields[url_field])
        if fields.get("error_message"):
            fields["error_message"] = redact(fields["error_message"])
        with self.transaction() as conn:
            # Ein früher fehlgeschlagener Eintrag mit gleichem doc_key wird ersetzt.
            if fields.get("doc_key"):
                conn.execute(
                    "DELETE FROM documents WHERE doc_key = ? AND sha256 IS NULL", (fields["doc_key"],)
                )
            cols = ", ".join(fields)
            marks = ", ".join("?" for _ in fields)
            cur = conn.execute(f"INSERT INTO documents({cols}) VALUES ({marks})", tuple(fields.values()))
            return int(cur.lastrowid)

    def upsert_failed_document(self, broker: str, doc_key: str, original_name: str, status: str, error: str,
                               source_url: str = "", page_url: str = "", doc_date: str = "") -> None:
        self.execute(
            """INSERT INTO documents(broker, doc_key, original_name, download_status, error_message, source_url,
                                     page_url, doc_date, downloaded_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(doc_key) DO UPDATE SET download_status=excluded.download_status,
                 error_message=excluded.error_message, downloaded_at=excluded.downloaded_at
               WHERE documents.sha256 IS NULL""",
            (broker, doc_key, original_name, status, redact(error), redact_url(source_url), redact_url(page_url),
             doc_date or None, utcnow()),
        )

    def add_location(self, document_id: int, ref: Any, original_name: str = "") -> None:
        self.execute(
            """INSERT OR IGNORE INTO document_locations(document_id, broker, doc_key, source, title, original_name,
                                                       doc_date, source_url, page_url, found_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                document_id, ref.broker, ref.key, ref.source, ref.title, original_name, ref.date or None,
                redact_url(ref.url or ""), redact_url(ref.page_url or ""), utcnow(),
            ),
        )

    def locations(self, document_id: int) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM document_locations WHERE document_id = ? ORDER BY id", (document_id,))

    def documents(self, broker: str | None = None, status: str | None = None, limit: int = 1000) -> list[dict]:
        sql = "SELECT * FROM documents WHERE 1=1"
        params: list[Any] = []
        if broker:
            sql += " AND broker = ?"
            params.append(broker)
        if status:
            sql += " AND download_status = ?"
            params.append(status)
        sql += " ORDER BY COALESCE(doc_date, downloaded_at) DESC LIMIT ?"
        params.append(limit)
        return self.query(sql, tuple(params))

    # ------------------------------------------------------------------ #
    # Quellen-Abgleich
    # ------------------------------------------------------------------ #
    def record_source(self, run_id: int, ref: Any, url_base: str) -> None:
        self.execute(
            """INSERT OR IGNORE INTO source_records(run_id, broker, source, doc_key, title, doc_date, url_base,
                                                   external_id) VALUES (?,?,?,?,?,?,?,?)""",
            (run_id, ref.broker, ref.source, ref.key, ref.title, ref.date or None, redact_url(url_base),
             ref.external_id or None),
        )

    def source_records(self, run_id: int) -> list[dict[str, Any]]:
        return self.query(
            """SELECT s.*, i.status AS item_status, d.sha256 AS sha256, d.id AS document_id
               FROM source_records s
               LEFT JOIN run_results i ON i.run_id = s.run_id AND i.doc_key = s.doc_key
               LEFT JOIN documents d ON d.id = i.document_id
               WHERE s.run_id = ? ORDER BY s.id""",
            (run_id,),
        )
