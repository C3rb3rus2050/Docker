"""SQLite-Datenbank: Schema, Verbindung, Migration.

Die Datenbank wird beim ersten Zugriff automatisch angelegt. Es werden keine Zugangsdaten
gespeichert. Beträge werden als REAL in Originalwährung und in EUR gespeichert; Rundung
erfolgt erst bei der Darstellung.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 2

# Spalten, die in späteren Versionen ergänzt wurden (für bestehende Datenbanken)
MIGRATIONS: list[tuple[str, str, str]] = [
    ("transactions", "fx_source", "TEXT"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS brokers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    key TEXT NOT NULL DEFAULT 'Other',          -- TradeRepublic | ScalableCapital | Other
    country TEXT,                               -- Sitzstaat des Brokers (Info)
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS depots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker_id INTEGER NOT NULL REFERENCES brokers(id),
    name TEXT NOT NULL,
    account_ref TEXT,                           -- nur Kurzbezeichnung, z. B. letzte 4 Stellen
    currency TEXT NOT NULL DEFAULT 'EUR',
    notes TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(broker_id, name)
);

-- Steuerliche Eigenschaften eines Depots je Steuerjahr (nicht stillschweigend auf andere Jahre übertragen)
CREATE TABLE IF NOT EXISTS depot_tax_settings (
    depot_id INTEGER NOT NULL REFERENCES depots(id) ON DELETE CASCADE,
    tax_year INTEGER NOT NULL,
    kest_withheld TEXT NOT NULL DEFAULT 'unbekannt',      -- ja | nein | unbekannt (österr. KESt-Abzug durch Broker)
    loss_offset_by_broker TEXT NOT NULL DEFAULT 'unbekannt', -- ja | nein | unbekannt
    source TEXT,
    notes TEXT,
    updated_at TEXT,
    PRIMARY KEY (depot_id, tax_year)
);

CREATE TABLE IF NOT EXISTS securities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isin TEXT UNIQUE,
    name TEXT,
    ticker TEXT,
    wkn TEXT,
    currency TEXT,
    country TEXT,                              -- Sitzstaat des Emittenten (ISO-2) für Quellensteuer
    security_type TEXT NOT NULL DEFAULT 'Sonstige',
    tax_class TEXT NOT NULL DEFAULT 'ungeklaert',
    tax_class_source TEXT,
    tax_class_verified INTEGER NOT NULL DEFAULT 0,
    fund_status TEXT NOT NULL DEFAULT 'kein_fonds',   -- kein_fonds | meldefonds | nichtmeldefonds | unbekannt
    fund_status_source TEXT,
    fund_status_verified INTEGER NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'ungeprueft',
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,                 -- relativ zum Ablageordner
    file_type TEXT,
    file_size INTEGER,
    doc_type TEXT NOT NULL DEFAULT 'Unbekannt',
    source TEXT NOT NULL DEFAULT 'Unclassified',   -- TradeRepublic | ScalableCapital | OeKB | Other | Unclassified
    broker_id INTEGER REFERENCES brokers(id),
    tax_year INTEGER,
    imported_at TEXT NOT NULL,
    import_method TEXT,
    status TEXT NOT NULL DEFAULT 'neu',        -- neu | verarbeitet | teilweise | pruefen | fehlgeschlagen | ignoriert
    extraction_json TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS document_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    import_type TEXT NOT NULL,
    document_id INTEGER REFERENCES documents(id),
    depot_id INTEGER REFERENCES depots(id),
    status TEXT NOT NULL DEFAULT 'laufend',
    rows_total INTEGER DEFAULT 0,
    rows_imported INTEGER DEFAULT 0,
    rows_duplicates INTEGER DEFAULT 0,
    rows_skipped INTEGER DEFAULT 0,
    rows_errors INTEGER DEFAULT 0,
    message TEXT
);

CREATE TABLE IF NOT EXISTS import_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_run_id INTEGER NOT NULL REFERENCES import_runs(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    row_no INTEGER,
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    depot_id INTEGER NOT NULL REFERENCES depots(id),
    security_id INTEGER REFERENCES securities(id),
    isin TEXT,
    security_name TEXT,
    tx_type TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    value_date TEXT,
    quantity REAL,
    price REAL,
    currency TEXT NOT NULL DEFAULT 'EUR',
    amount REAL,                     -- Bruttobetrag in Originalwährung (positiv)
    fees REAL DEFAULT 0,             -- Gebühren in Originalwährung (positiv)
    fx_rate REAL,                    -- Einheiten Fremdwährung je 1 EUR
    fx_source TEXT,                  -- Herkunft des Kurses (Beleg, manuell, EZB-Referenzkurs …)
    amount_eur REAL,
    fees_eur REAL DEFAULT 0,
    withholding_tax REAL DEFAULT 0,  -- ausländische Quellensteuer (Originalwährung)
    withholding_tax_eur REAL DEFAULT 0,
    withholding_country TEXT,
    kest_at_eur REAL DEFAULT 0,      -- bereits einbehaltene österreichische KESt
    ratio REAL,                      -- z. B. Splitverhältnis neu/alt
    income_category TEXT NOT NULL DEFAULT 'auto',  -- auto | dividende | sonstige_ausschuettung | kapitalrueckzahlung | ungeklaert
    income_category_verified INTEGER NOT NULL DEFAULT 0,
    document_id INTEGER REFERENCES documents(id),
    import_run_id INTEGER REFERENCES import_runs(id),
    source_type TEXT NOT NULL DEFAULT 'manuell',   -- csv | excel | pdf | manuell | korrektur
    source_ref TEXT,
    fingerprint TEXT,
    review_status TEXT NOT NULL DEFAULT 'ungeprueft',  -- ungeprueft | geprueft | pruefen
    corrects_id INTEGER REFERENCES transactions(id),
    deleted INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tx_depot ON transactions(depot_id);
CREATE INDEX IF NOT EXISTS idx_tx_isin ON transactions(isin);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(trade_date);
CREATE INDEX IF NOT EXISTS idx_tx_fp ON transactions(fingerprint);

CREATE TABLE IF NOT EXISTS document_links (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'beleg',
    created_at TEXT NOT NULL,
    PRIMARY KEY (document_id, transaction_id)
);

-- Steuerliche Fondsdaten (OeKB-Meldungen) je ISIN; Werte je Anteil in Fondswährung bzw. EUR
CREATE TABLE IF NOT EXISTS fund_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isin TEXT NOT NULL,
    fund_name TEXT,
    report_type TEXT NOT NULL DEFAULT 'Jahresmeldung',  -- Jahresmeldung | Ausschuettungsmeldung
    fiscal_year_end TEXT,
    report_date TEXT NOT NULL,               -- Meldedatum = Zuflusszeitpunkt der AgE
    distribution_date TEXT,                  -- Ex-Tag bei Ausschüttungsmeldung
    currency TEXT NOT NULL DEFAULT 'EUR',
    fx_rate REAL,                            -- Fondswährung je 1 EUR (falls nicht EUR)
    distribution_per_unit REAL,
    age_per_unit REAL,                       -- ausschüttungsgleiche Erträge je Anteil
    taxable_distribution_per_unit REAL,      -- steuerpflichtiger Teil der Ausschüttung je Anteil
    creditable_tax_per_unit REAL,            -- anrechenbare ausländische Steuer je Anteil
    ak_correction_per_unit REAL,             -- Korrekturbetrag Anschaffungskosten je Anteil
    kest_per_unit REAL,
    is_meldefonds INTEGER,
    source TEXT NOT NULL,                    -- manuell | import_csv | import_pdf | automatisch
    document_id INTEGER REFERENCES documents(id),
    imported_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    review_status TEXT NOT NULL DEFAULT 'ungeprueft',  -- ungeprueft | geprueft | verworfen
    active INTEGER NOT NULL DEFAULT 1,
    superseded_by INTEGER REFERENCES fund_reports(id),
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_fr_isin ON fund_reports(isin);

-- Kursdaten für Nichtmeldefonds (Pauschalbesteuerung)
CREATE TABLE IF NOT EXISTS nmf_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isin TEXT NOT NULL,
    tax_year INTEGER NOT NULL,
    first_price REAL,
    first_price_date TEXT,
    last_price REAL,
    last_price_date TEXT,
    currency TEXT NOT NULL DEFAULT 'EUR',
    fx_rate_last REAL,
    source TEXT,
    document_id INTEGER REFERENCES documents(id),
    review_status TEXT NOT NULL DEFAULT 'ungeprueft',
    notes TEXT,
    UNIQUE(isin, tax_year)
);

-- Konflikte zwischen Datenquellen (werden nie stillschweigend aufgelöst)
CREATE TABLE IF NOT EXISTS conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    field TEXT,
    existing_ref TEXT,
    existing_value TEXT,
    new_ref TEXT,
    new_value TEXT,
    status TEXT NOT NULL DEFAULT 'offen',   -- offen | bestehend_behalten | neu_uebernommen | beide_behalten
    decision_note TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT,
    action TEXT NOT NULL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS csv_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    mapping_json TEXT NOT NULL,
    options_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    tax_year INTEGER,
    kind TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT,
    notes TEXT
);
"""


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


class Database:
    """Dünne Hülle um sqlite3 mit Thread-Lock (Streamlit nutzt mehrere Threads)."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.init_schema()

    def init_schema(self) -> None:
        with self._lock:
            self.conn.executescript(SCHEMA)
            for table, column, ctype in MIGRATIONS:
                cols = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                if column not in cols:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ctype}")
            cur = self.conn.execute("SELECT value FROM meta WHERE key='schema_version'")
            row = cur.fetchone()
            if row is None:
                self.conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
                self.conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('created_at', ?)", (now_iso(),))
            else:
                self.conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
            self.conn.commit()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        with self._lock:
            r = self.conn.execute(sql, params).fetchone()
            return dict(r) if r else None

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        with self.tx() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    def backup_to(self, target: Path) -> None:
        """Konsistente Kopie per SQLite-Backup-API (auch bei laufender Anwendung)."""
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            dest = sqlite3.connect(str(target))
            try:
                self.conn.backup(dest)
            finally:
                dest.close()

    def close(self) -> None:
        with self._lock:
            self.conn.close()
