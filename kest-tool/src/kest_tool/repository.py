"""Repository-Schicht: alle Lese-/Schreibzugriffe auf die Datenbank.

Manuelle Änderungen werden im ``audit_log`` protokolliert. Konflikte werden nie stillschweigend
aufgelöst, sondern in ``conflicts`` abgelegt.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from .db import Database, now_iso
from .models import (
    COMPARE_FIELDS_FUND_REPORT,
    FundReportIn,
    SecurityIn,
    TransactionIn,
    TxType,
)
from .storage import DocumentStore, sha256_bytes

TX_COLUMNS = [
    "depot_id", "security_id", "isin", "security_name", "tx_type", "trade_date", "value_date", "quantity",
    "price", "currency", "amount", "fees", "fx_rate", "fx_source", "amount_eur", "fees_eur", "withholding_tax",
    "withholding_tax_eur", "withholding_country", "kest_at_eur", "ratio", "income_category",
    "income_category_verified", "document_id", "import_run_id", "source_type", "source_ref", "fingerprint",
    "review_status", "corrects_id", "notes",
]


def _iso(d: date | str | None) -> str | None:
    if d is None:
        return None
    return d.isoformat() if isinstance(d, date) else str(d)


def tx_fingerprint(depot_id: int, tx_type: str, trade_date: str, isin: str | None, quantity: float | None,
                   amount: float | None, currency: str) -> str:
    """Stabiler Fingerabdruck einer Buchung für die Dublettenerkennung."""
    parts = [
        str(depot_id), str(tx_type), str(trade_date), isin or "-",
        f"{round(abs(quantity), 6):.6f}" if quantity else "-",
        f"{round(abs(amount), 2):.2f}" if amount else "-",
        currency or "EUR",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


class Repository:
    def __init__(self, db: Database, store: DocumentStore):
        self.db = db
        self.store = store

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #
    def audit(self, entity: str, entity_id: Any, action: str, details: Any = None) -> None:
        self.db.execute(
            "INSERT INTO audit_log(ts, entity, entity_id, action, details) VALUES(?,?,?,?,?)",
            (now_iso(), entity, str(entity_id) if entity_id is not None else None, action,
             json.dumps(details, ensure_ascii=False, default=str) if details is not None else None),
        )

    def audit_entries(self, limit: int = 5000) -> list[dict]:
        return self.db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------------ #
    # Broker & Depots
    # ------------------------------------------------------------------ #
    def add_broker(self, name: str, key: str = "Other", country: str | None = None, notes: str | None = None) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("Brokername fehlt")
        existing = self.db.one("SELECT id FROM brokers WHERE name=?", (name,))
        if existing:
            return existing["id"]
        bid = self.db.execute("INSERT INTO brokers(name, key, country, notes, created_at) VALUES(?,?,?,?,?)",
                              (name, key, country, notes, now_iso()))
        self.audit("broker", bid, "angelegt", {"name": name, "key": key})
        return bid

    def brokers(self) -> list[dict]:
        return self.db.query("SELECT * FROM brokers ORDER BY name")

    def broker(self, broker_id: int) -> dict | None:
        return self.db.one("SELECT * FROM brokers WHERE id=?", (broker_id,))

    def add_depot(self, broker_id: int, name: str, account_ref: str | None = None, currency: str = "EUR",
                  notes: str | None = None) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("Depotname fehlt")
        existing = self.db.one("SELECT id FROM depots WHERE broker_id=? AND name=?", (broker_id, name))
        if existing:
            return existing["id"]
        did = self.db.execute(
            "INSERT INTO depots(broker_id, name, account_ref, currency, notes, created_at) VALUES(?,?,?,?,?,?)",
            (broker_id, name, account_ref, currency, notes, now_iso()))
        self.audit("depot", did, "angelegt", {"broker_id": broker_id, "name": name})
        return did

    def depots(self, active_only: bool = False) -> list[dict]:
        sql = ("SELECT d.*, b.name AS broker_name, b.key AS broker_key FROM depots d "
               "JOIN brokers b ON b.id = d.broker_id")
        if active_only:
            sql += " WHERE d.active = 1"
        return self.db.query(sql + " ORDER BY b.name, d.name")

    def depot(self, depot_id: int) -> dict | None:
        return self.db.one("SELECT d.*, b.name AS broker_name, b.key AS broker_key FROM depots d "
                           "JOIN brokers b ON b.id=d.broker_id WHERE d.id=?", (depot_id,))

    def update_depot(self, depot_id: int, **fields) -> None:
        allowed = {"name", "account_ref", "currency", "notes", "active"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        old = self.depot(depot_id)
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE depots SET {sets} WHERE id=?", (*fields.values(), depot_id))
        self.audit("depot", depot_id, "geändert", {"alt": {k: old.get(k) for k in fields}, "neu": fields})

    def set_depot_tax_settings(self, depot_id: int, tax_year: int, kest_withheld: str, loss_offset_by_broker: str,
                               source: str | None = None, notes: str | None = None) -> None:
        for v in (kest_withheld, loss_offset_by_broker):
            if v not in ("ja", "nein", "unbekannt"):
                raise ValueError("Wert muss ja/nein/unbekannt sein")
        old = self.depot_tax_settings(depot_id, tax_year)
        self.db.execute(
            "INSERT INTO depot_tax_settings(depot_id, tax_year, kest_withheld, loss_offset_by_broker, source, notes, "
            "updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(depot_id, tax_year) DO UPDATE SET "
            "kest_withheld=excluded.kest_withheld, loss_offset_by_broker=excluded.loss_offset_by_broker, "
            "source=excluded.source, notes=excluded.notes, updated_at=excluded.updated_at",
            (depot_id, tax_year, kest_withheld, loss_offset_by_broker, source, notes, now_iso()))
        self.audit("depot_tax_settings", f"{depot_id}/{tax_year}", "gesetzt",
                   {"alt": old, "neu": {"kest_withheld": kest_withheld, "loss_offset_by_broker": loss_offset_by_broker,
                                        "source": source}})

    def depot_tax_settings(self, depot_id: int, tax_year: int) -> dict:
        row = self.db.one("SELECT * FROM depot_tax_settings WHERE depot_id=? AND tax_year=?", (depot_id, tax_year))
        return row or {"depot_id": depot_id, "tax_year": tax_year, "kest_withheld": "unbekannt",
                       "loss_offset_by_broker": "unbekannt", "source": None, "notes": None, "_default": True}

    # ------------------------------------------------------------------ #
    # Wertpapiere
    # ------------------------------------------------------------------ #
    def upsert_security(self, sec: SecurityIn, *, overwrite: bool = True, reason: str = "manuell") -> int:
        data = sec.model_dump()
        for k in ("security_type", "tax_class", "fund_status"):
            data[k] = data[k].value if hasattr(data[k], "value") else data[k]
        existing = self.db.one("SELECT * FROM securities WHERE isin=?", (sec.isin,))
        if existing is None:
            cols = list(data.keys()) + ["created_at", "updated_at"]
            sid = self.db.execute(
                f"INSERT INTO securities({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                (*[int(v) if isinstance(v, bool) else v for v in data.values()], now_iso(), now_iso()))
            self.audit("security", sec.isin, "angelegt", {"grund": reason, **data})
            return sid
        if not overwrite:
            return existing["id"]
        changes = {k: v for k, v in data.items()
                   if (int(v) if isinstance(v, bool) else v) != existing.get(k) and v is not None}
        if changes:
            sets = ", ".join(f"{k}=?" for k in changes)
            self.db.execute(f"UPDATE securities SET {sets}, updated_at=? WHERE id=?",
                            (*[int(v) if isinstance(v, bool) else v for v in changes.values()], now_iso(),
                             existing["id"]))
            self.audit("security", sec.isin, "geändert",
                       {"grund": reason, "alt": {k: existing.get(k) for k in changes}, "neu": changes})
        return existing["id"]

    def ensure_security(self, isin: str, name: str | None = None) -> int:
        row = self.db.one("SELECT id, name FROM securities WHERE isin=?", (isin,))
        if row:
            if name and not row["name"]:
                self.db.execute("UPDATE securities SET name=? WHERE id=?", (name, row["id"]))
            return row["id"]
        return self.db.execute(
            "INSERT INTO securities(isin, name, created_at, updated_at) VALUES(?,?,?,?)",
            (isin, name, now_iso(), now_iso()))

    def securities(self, search: str | None = None) -> list[dict]:
        if search:
            like = f"%{search.strip()}%"
            return self.db.query("SELECT * FROM securities WHERE isin LIKE ? OR name LIKE ? OR ticker LIKE ? "
                                 "OR wkn LIKE ? ORDER BY name", (like, like, like, like))
        return self.db.query("SELECT * FROM securities ORDER BY name")

    def security_by_isin(self, isin: str) -> dict | None:
        return self.db.one("SELECT * FROM securities WHERE isin=?", (isin,))

    def set_security_review(self, isin: str, status: str) -> None:
        self.db.execute("UPDATE securities SET review_status=?, updated_at=? WHERE isin=?", (status, now_iso(), isin))
        self.audit("security", isin, "prüfstatus", {"status": status})

    # ------------------------------------------------------------------ #
    # Dokumente
    # ------------------------------------------------------------------ #
    def find_document_by_hash(self, sha: str) -> dict | None:
        return self.db.one("SELECT * FROM documents WHERE sha256=?", (sha,))

    def add_document(self, data: bytes, filename: str, *, doc_type: str = "Unbekannt", source: str = "Unclassified",
                     tax_year: int | None = None, broker_id: int | None = None, import_method: str = "upload",
                     status: str = "neu") -> tuple[dict, bool]:
        """Legt ein Dokument ab. Rückgabe: (Dokumentdatensatz, neu_angelegt).

        Ist eine Datei mit identischem SHA-256 bereits vorhanden, wird keine Kopie angelegt.
        """
        sha = sha256_bytes(data)
        existing = self.find_document_by_hash(sha)
        if existing:
            self.document_event(existing["id"], "erneuter_import_erkannt", {"dateiname": filename})
            return existing, False
        if tax_year:
            self.store.ensure_year(tax_year)
        path = self.store.store_document(data, filename, tax_year, source)
        ext = Path(filename).suffix.lower().lstrip(".")
        did = self.db.execute(
            "INSERT INTO documents(sha256, original_filename, stored_path, file_type, file_size, doc_type, source, "
            "broker_id, tax_year, imported_at, import_method, status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (sha, filename, self.store.relative(path), ext, len(data), doc_type, source, broker_id, tax_year,
             now_iso(), import_method, status))
        self.document_event(did, "importiert", {"methode": import_method, "pfad": self.store.relative(path)})
        return self.document(did), True

    def document(self, doc_id: int) -> dict | None:
        return self.db.one("SELECT * FROM documents WHERE id=?", (doc_id,))

    def documents(self, tax_year: int | None = None, source: str | None = None, doc_type: str | None = None,
                  search: str | None = None, status: str | None = None) -> list[dict]:
        sql = ("SELECT d.*, (SELECT COUNT(*) FROM transactions t WHERE t.document_id=d.id AND t.deleted=0) + "
               "(SELECT COUNT(*) FROM document_links l JOIN transactions t2 ON t2.id=l.transaction_id "
               " WHERE l.document_id=d.id AND t2.deleted=0 AND (t2.document_id IS NULL OR t2.document_id<>d.id)) "
               "AS tx_count FROM documents d WHERE 1=1")
        params: list = []
        if tax_year:
            sql += " AND d.tax_year=?"
            params.append(tax_year)
        if source:
            sql += " AND d.source=?"
            params.append(source)
        if doc_type:
            sql += " AND d.doc_type=?"
            params.append(doc_type)
        if status:
            sql += " AND d.status=?"
            params.append(status)
        if search:
            sql += " AND (d.original_filename LIKE ? OR d.notes LIKE ? OR d.sha256 LIKE ?)"
            params += [f"%{search}%"] * 3
        return self.db.query(sql + " ORDER BY d.imported_at DESC, d.id DESC", tuple(params))

    def document_event(self, doc_id: int, event: str, details: Any = None) -> None:
        self.db.execute("INSERT INTO document_events(document_id, ts, event, details) VALUES(?,?,?,?)",
                        (doc_id, now_iso(), event, json.dumps(details, ensure_ascii=False, default=str)
                         if details is not None else None))

    def document_events(self, doc_id: int) -> list[dict]:
        return self.db.query("SELECT * FROM document_events WHERE document_id=? ORDER BY id", (doc_id,))

    def update_document(self, doc_id: int, **fields) -> None:
        allowed = {"doc_type", "source", "tax_year", "status", "notes", "extraction_json", "broker_id"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        old = self.document(doc_id)
        if ("tax_year" in fields and fields["tax_year"] != old["tax_year"]) or \
                ("source" in fields and fields["source"] != old["source"]):
            new_year = fields.get("tax_year", old["tax_year"])
            if new_year:
                self.store.ensure_year(int(new_year))
            new_path = self.store.move_document(old["stored_path"], new_year, fields.get("source", old["source"]))
            fields["stored_path"] = self.store.relative(new_path)
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE documents SET {sets} WHERE id=?", (*fields.values(), doc_id))
        changed = {k: v for k, v in fields.items() if k != "extraction_json"}
        if changed:
            self.document_event(doc_id, "geändert", {"alt": {k: old.get(k) for k in changed}, "neu": changed})
            self.audit("document", doc_id, "geändert", {"alt": {k: old.get(k) for k in changed}, "neu": changed})

    def document_path(self, doc: dict) -> Path:
        return self.store.absolute(doc["stored_path"])

    def link_document(self, doc_id: int, tx_id: int, link_type: str = "beleg") -> None:
        self.db.execute("INSERT OR IGNORE INTO document_links(document_id, transaction_id, link_type, created_at) "
                        "VALUES(?,?,?,?)", (doc_id, tx_id, link_type, now_iso()))
        self.audit("document_link", f"{doc_id}->{tx_id}", "verknüpft", {"typ": link_type})

    def transactions_for_document(self, doc_id: int) -> list[dict]:
        return self.db.query(
            "SELECT * FROM transactions WHERE deleted=0 AND (document_id=? OR id IN "
            "(SELECT transaction_id FROM document_links WHERE document_id=?)) ORDER BY trade_date", (doc_id, doc_id))

    # ------------------------------------------------------------------ #
    # Transaktionen
    # ------------------------------------------------------------------ #
    def find_duplicates(self, tx: TransactionIn, fuzzy_days: int = 3, tolerance: float = 0.005) -> dict:
        """Liefert {'exact': [...], 'possible': [...]} für eine neue Buchung."""
        fp = self.fingerprint(tx)
        exact = self.db.query("SELECT * FROM transactions WHERE fingerprint=? AND deleted=0", (fp,))
        possible: list[dict] = []
        if tx.isin or tx.amount:
            lo = (tx.trade_date - timedelta(days=fuzzy_days)).isoformat()
            hi = (tx.trade_date + timedelta(days=fuzzy_days)).isoformat()
            rows = self.db.query(
                "SELECT * FROM transactions WHERE deleted=0 AND depot_id=? AND tx_type=? AND trade_date BETWEEN ? AND ? "
                "AND COALESCE(isin,'')=COALESCE(?, '')",
                (tx.depot_id, tx.tx_type.value, lo, hi, tx.isin))
            exact_ids = {r["id"] for r in exact}
            for r in rows:
                if r["id"] in exact_ids:
                    continue
                same_qty = (not tx.quantity or not r["quantity"] or abs((r["quantity"] or 0) - tx.quantity) < 1e-6)
                amt_ok = True
                if tx.amount and r["amount"]:
                    amt_ok = abs(r["amount"] - tx.amount) <= max(0.01, tolerance * abs(tx.amount))
                if same_qty and amt_ok:
                    possible.append(r)
        return {"exact": exact, "possible": possible, "fingerprint": fp}

    @staticmethod
    def fingerprint(tx: TransactionIn) -> str:
        return tx_fingerprint(tx.depot_id, tx.tx_type.value, tx.trade_date.isoformat(), tx.isin, tx.quantity,
                              tx.amount, tx.currency)

    def add_transaction(self, tx: TransactionIn, import_run_id: int | None = None) -> int:
        security_id = self.ensure_security(tx.isin, tx.security_name) if tx.isin else None
        amount_eur = tx.eur(tx.amount)
        fees_eur = tx.eur(tx.fees) or 0.0
        wht_eur = tx.eur(tx.withholding_tax) or 0.0
        row = {
            "depot_id": tx.depot_id, "security_id": security_id, "isin": tx.isin, "security_name": tx.security_name,
            "tx_type": tx.tx_type.value, "trade_date": _iso(tx.trade_date), "value_date": _iso(tx.value_date),
            "quantity": tx.quantity, "price": tx.price, "currency": tx.currency, "amount": tx.amount,
            "fees": tx.fees, "fx_rate": tx.fx_rate, "fx_source": (tx.fx_source or "Beleg/Import") if tx.fx_rate else None,
            "amount_eur": amount_eur, "fees_eur": fees_eur,
            "withholding_tax": tx.withholding_tax, "withholding_tax_eur": wht_eur,
            "withholding_country": tx.withholding_country, "kest_at_eur": tx.kest_at_eur, "ratio": tx.ratio,
            "income_category": tx.income_category.value, "income_category_verified": int(tx.income_category_verified),
            "document_id": tx.document_id, "import_run_id": import_run_id, "source_type": tx.source_type,
            "source_ref": tx.source_ref, "fingerprint": self.fingerprint(tx), "review_status": tx.review_status.value,
            "corrects_id": None, "notes": tx.notes,
        }
        cols = list(row.keys()) + ["created_at"]
        tid = self.db.execute(f"INSERT INTO transactions({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                              (*row.values(), now_iso()))
        if tx.document_id:
            self.link_document(tx.document_id, tid, "ursprung")
        if tx.source_type in ("manuell", "korrektur"):
            self.audit("transaction", tid, "manuell angelegt", row)
        return tid

    def transaction(self, tx_id: int) -> dict | None:
        return self.db.one("SELECT * FROM transactions WHERE id=?", (tx_id,))

    def update_transaction(self, tx_id: int, changes: dict, reason: str) -> None:
        """Manuelle Korrektur einer Buchung – alte und neue Werte werden protokolliert."""
        if not reason.strip():
            raise ValueError("Für manuelle Änderungen ist eine Begründung erforderlich")
        allowed = set(TX_COLUMNS) - {"fingerprint", "import_run_id", "document_id"}
        changes = {k: v for k, v in changes.items() if k in allowed}
        old = self.transaction(tx_id)
        if old is None:
            raise ValueError("Buchung nicht gefunden")
        if "fx_rate" in changes and "fx_source" not in changes and changes["fx_rate"] != old.get("fx_rate"):
            changes["fx_source"] = "manuell erfasst/geändert"
        merged = {**old, **changes}
        # EUR-Werte neu berechnen
        cur = merged.get("currency") or "EUR"
        fx = merged.get("fx_rate")

        def to_eur(v):
            if v is None:
                return None
            return v if cur == "EUR" else (v / fx if fx else None)

        for src, dst in (("amount", "amount_eur"), ("fees", "fees_eur"), ("withholding_tax", "withholding_tax_eur")):
            if src in changes or "fx_rate" in changes or "currency" in changes:
                changes[dst] = to_eur(merged.get(src))
        changes["fingerprint"] = tx_fingerprint(merged["depot_id"], merged["tx_type"], merged["trade_date"],
                                                merged.get("isin"), merged.get("quantity"), merged.get("amount"), cur)
        if "isin" in changes and changes["isin"]:
            changes["security_id"] = self.ensure_security(changes["isin"], merged.get("security_name"))
        sets = ", ".join(f"{k}=?" for k in changes)
        self.db.execute(f"UPDATE transactions SET {sets}, updated_at=? WHERE id=?",
                        (*changes.values(), now_iso(), tx_id))
        self.audit("transaction", tx_id, "manuell geändert",
                   {"begründung": reason, "alt": {k: old.get(k) for k in changes}, "neu": changes})

    def delete_transaction(self, tx_id: int, reason: str) -> None:
        if not reason.strip():
            raise ValueError("Für das Löschen ist eine Begründung erforderlich")
        self.db.execute("UPDATE transactions SET deleted=1, updated_at=? WHERE id=?", (now_iso(), tx_id))
        self.audit("transaction", tx_id, "gelöscht (logisch)", {"begründung": reason})

    def transactions(self, tax_year: int | None = None, depot_id: int | None = None, isin: str | None = None,
                     until: str | None = None, include_deleted: bool = False) -> list[dict]:
        sql = ("SELECT t.*, d.name AS depot_name, b.name AS broker_name, b.key AS broker_key, "
               "doc.original_filename AS document_name, doc.stored_path AS document_path "
               "FROM transactions t JOIN depots d ON d.id=t.depot_id JOIN brokers b ON b.id=d.broker_id "
               "LEFT JOIN documents doc ON doc.id=t.document_id WHERE 1=1")
        params: list = []
        if not include_deleted:
            sql += " AND t.deleted=0"
        if tax_year:
            sql += " AND substr(t.trade_date,1,4)=?"
            params.append(str(tax_year))
        if until:
            sql += " AND t.trade_date<=?"
            params.append(until)
        if depot_id:
            sql += " AND t.depot_id=?"
            params.append(depot_id)
        if isin:
            sql += " AND t.isin=?"
            params.append(isin)
        return self.db.query(sql + " ORDER BY t.trade_date, t.id", tuple(params))

    # ------------------------------------------------------------------ #
    # Importläufe
    # ------------------------------------------------------------------ #
    def start_import(self, import_type: str, document_id: int | None = None, depot_id: int | None = None) -> int:
        return self.db.execute("INSERT INTO import_runs(started_at, import_type, document_id, depot_id) VALUES(?,?,?,?)",
                               (now_iso(), import_type, document_id, depot_id))

    def log_import(self, run_id: int, level: str, message: str, row_no: int | None = None) -> None:
        self.db.execute("INSERT INTO import_log(import_run_id, ts, level, row_no, message) VALUES(?,?,?,?,?)",
                        (run_id, now_iso(), level, row_no, message))

    def finish_import(self, run_id: int, status: str, **counts) -> None:
        allowed = {"rows_total", "rows_imported", "rows_duplicates", "rows_skipped", "rows_errors", "message"}
        counts = {k: v for k, v in counts.items() if k in allowed}
        sets = ", ".join(f"{k}=?" for k in counts)
        sql = "UPDATE import_runs SET status=?, finished_at=?" + (f", {sets}" if sets else "") + " WHERE id=?"
        self.db.execute(sql, (status, now_iso(), *counts.values(), run_id))
        run = self.db.one("SELECT * FROM import_runs WHERE id=?", (run_id,))
        self._write_import_log_file(run)

    def _write_import_log_file(self, run: dict) -> None:
        """Importprotokoll zusätzlich als Textdatei unter imports/<Jahr>/import_logs ablegen."""
        year = int(run["started_at"][:4])
        doc = self.document(run["document_id"]) if run.get("document_id") else None
        if doc and doc.get("tax_year"):
            year = int(doc["tax_year"])
        self.store.ensure_year(year)
        lines = [f"Importlauf {run['id']} – {run['import_type']}", f"Start: {run['started_at']}",
                 f"Ende: {run['finished_at']}", f"Status: {run['status']}",
                 f"Zeilen gesamt: {run['rows_total']}, importiert: {run['rows_imported']}, Dubletten: "
                 f"{run['rows_duplicates']}, übersprungen: {run['rows_skipped']}, Fehler: {run['rows_errors']}",
                 f"Dokument: {doc['original_filename'] if doc else '-'}", "", "Protokoll:"]
        for e in self.import_log(run["id"]):
            lines.append(f"{e['ts']} [{e['level']}] Zeile {e['row_no'] or '-'}: {e['message']}")
        target = self.store.import_dir(year, "import_logs") / f"import_{run['id']:05d}.log"
        target.write_text("\n".join(lines), encoding="utf-8")

    def import_runs(self, limit: int = 200) -> list[dict]:
        return self.db.query(
            "SELECT r.*, doc.original_filename FROM import_runs r LEFT JOIN documents doc ON doc.id=r.document_id "
            "ORDER BY r.id DESC LIMIT ?", (limit,))

    def import_log(self, run_id: int) -> list[dict]:
        return self.db.query("SELECT * FROM import_log WHERE import_run_id=? ORDER BY id", (run_id,))

    # ------------------------------------------------------------------ #
    # Fondsmeldungen (OeKB) & Konflikte
    # ------------------------------------------------------------------ #
    def add_fund_report(self, rep: FundReportIn) -> dict:
        """Speichert eine Fondsmeldung. Abweichungen zu bestehenden Meldungen werden als Konflikt erfasst.

        Rückgabe: {"id", "status": neu|identisch|konflikt, "conflicts": [...]}.
        """
        data = rep.model_dump()
        data["is_meldefonds"] = None if rep.is_meldefonds is None else int(rep.is_meldefonds)
        for k in ("fiscal_year_end", "report_date", "distribution_date"):
            data[k] = _iso(data[k])
        existing = self.db.query(
            "SELECT * FROM fund_reports WHERE isin=? AND report_type=? AND active=1 AND "
            "(report_date=? OR (fiscal_year_end IS NOT NULL AND fiscal_year_end=?))",
            (rep.isin, rep.report_type, data["report_date"], data["fiscal_year_end"]))
        for ex in existing:
            diffs = self._diff_report(ex, data)
            if not diffs:
                if rep.document_id and not ex.get("document_id"):
                    self.db.execute("UPDATE fund_reports SET document_id=? WHERE id=?", (rep.document_id, ex["id"]))
                return {"id": ex["id"], "status": "identisch", "conflicts": []}
        version = (max((e["version"] for e in existing), default=0) + 1)
        cols = list(data.keys()) + ["imported_at", "version", "active"]
        # Bei bestehender abweichender Meldung wird die neue NICHT aktiv geschaltet – Benutzer entscheidet.
        active = 0 if existing else 1
        rid = self.db.execute(f"INSERT INTO fund_reports({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                              (*data.values(), now_iso(), version, active))
        conflicts = []
        for ex in existing:
            for field, (old, new) in self._diff_report(ex, data).items():
                cid = self.db.execute(
                    "INSERT INTO conflicts(entity, entity_key, field, existing_ref, existing_value, new_ref, new_value, "
                    "created_at) VALUES(?,?,?,?,?,?,?,?)",
                    ("fund_report", f"{rep.isin}/{data['report_date']}", field, f"fund_reports:{ex['id']} ({ex['source']})",
                     str(old), f"fund_reports:{rid} ({rep.source})", str(new), now_iso()))
                conflicts.append(cid)
        self.audit("fund_report", rid, "importiert", {"quelle": rep.source, "isin": rep.isin, "aktiv": bool(active),
                                                      "konflikte": len(conflicts)})
        return {"id": rid, "status": "konflikt" if conflicts else "neu", "conflicts": conflicts}

    @staticmethod
    def _diff_report(ex: dict, new: dict) -> dict:
        diffs = {}
        for f in COMPARE_FIELDS_FUND_REPORT:
            a, b = ex.get(f), new.get(f)
            if a is None and b is None:
                continue
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                if abs(a - b) > 1e-6:
                    diffs[f] = (a, b)
            elif (a or None) != (b or None):
                diffs[f] = (a, b)
        return diffs

    def fund_reports(self, isin: str | None = None, active_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM fund_reports WHERE 1=1"
        params: list = []
        if isin:
            sql += " AND isin=?"
            params.append(isin)
        if active_only:
            sql += " AND active=1 AND review_status<>'verworfen'"
        return self.db.query(sql + " ORDER BY isin, report_date, version", tuple(params))

    def set_fund_report_review(self, rid: int, status: str) -> None:
        self.db.execute("UPDATE fund_reports SET review_status=? WHERE id=?", (status, rid))
        self.audit("fund_report", rid, "prüfstatus", {"status": status})

    def conflicts(self, status: str | None = None) -> list[dict]:
        if status:
            return self.db.query("SELECT * FROM conflicts WHERE status=? ORDER BY id", (status,))
        return self.db.query("SELECT * FROM conflicts ORDER BY id")

    def resolve_fund_report_conflict(self, existing_id: int, new_id: int, decision: str, note: str) -> None:
        """decision: bestehend_behalten | neu_uebernommen. Die nicht gewählte Meldung bleibt erhalten (inaktiv)."""
        if decision not in ("bestehend_behalten", "neu_uebernommen"):
            raise ValueError("Unbekannte Entscheidung")
        if not note.strip():
            raise ValueError("Bitte die Entscheidung begründen")
        if decision == "neu_uebernommen":
            self.db.execute("UPDATE fund_reports SET active=0, superseded_by=? WHERE id=?", (new_id, existing_id))
            self.db.execute("UPDATE fund_reports SET active=1 WHERE id=?", (new_id,))
        else:
            self.db.execute("UPDATE fund_reports SET active=0, superseded_by=? WHERE id=?", (existing_id, new_id))
        self.db.execute(
            "UPDATE conflicts SET status=?, decision_note=?, decided_at=? WHERE entity='fund_report' AND status='offen' "
            "AND existing_ref LIKE ? AND new_ref LIKE ?",
            (decision, note, now_iso(), f"fund_reports:{existing_id} %", f"fund_reports:{new_id} %"))
        self.audit("conflict", f"{existing_id}/{new_id}", "entschieden", {"entscheidung": decision, "begründung": note})

    def upsert_nmf_price(self, isin: str, tax_year: int, first_price: float | None, first_date: str | None,
                         last_price: float | None, last_date: str | None, currency: str = "EUR",
                         fx_rate_last: float | None = None, source: str | None = None,
                         document_id: int | None = None) -> dict:
        existing = self.db.one("SELECT * FROM nmf_prices WHERE isin=? AND tax_year=?", (isin, tax_year))
        new = {"first_price": first_price, "first_price_date": first_date, "last_price": last_price,
               "last_price_date": last_date, "currency": currency, "fx_rate_last": fx_rate_last}
        if existing:
            diffs = {k: (existing[k], v) for k, v in new.items() if v is not None and existing[k] != v}
            if diffs:
                for f, (a, b) in diffs.items():
                    self.db.execute(
                        "INSERT INTO conflicts(entity, entity_key, field, existing_ref, existing_value, new_ref, "
                        "new_value, created_at) VALUES(?,?,?,?,?,?,?,?)",
                        ("nmf_price", f"{isin}/{tax_year}", f, f"nmf_prices:{existing['id']} ({existing['source']})",
                         str(a), source or "neu", str(b), now_iso()))
                return {"id": existing["id"], "status": "konflikt", "diffs": diffs}
            return {"id": existing["id"], "status": "identisch", "diffs": {}}
        nid = self.db.execute(
            "INSERT INTO nmf_prices(isin, tax_year, first_price, first_price_date, last_price, last_price_date, "
            "currency, fx_rate_last, source, document_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (isin, tax_year, first_price, first_date, last_price, last_date, currency, fx_rate_last, source,
             document_id))
        self.audit("nmf_price", nid, "angelegt", {"isin": isin, "jahr": tax_year, **new, "quelle": source})
        return {"id": nid, "status": "neu", "diffs": {}}

    def resolve_nmf_conflict(self, conflict_id: int, take_new: bool, note: str) -> None:
        if not note.strip():
            raise ValueError("Bitte die Entscheidung begründen")
        c = self.db.one("SELECT * FROM conflicts WHERE id=?", (conflict_id,))
        if not c or c["entity"] != "nmf_price":
            raise ValueError("Konflikt nicht gefunden")
        if take_new:
            isin, year = c["entity_key"].split("/")
            value: Any = c["new_value"]
            if c["field"] in ("first_price", "last_price", "fx_rate_last"):
                value = float(value)
            self.db.execute(f"UPDATE nmf_prices SET {c['field']}=? WHERE isin=? AND tax_year=?",
                            (value, isin, int(year)))
        self.db.execute("UPDATE conflicts SET status=?, decision_note=?, decided_at=? WHERE id=?",
                        ("neu_uebernommen" if take_new else "bestehend_behalten", note, now_iso(), conflict_id))
        self.audit("conflict", conflict_id, "entschieden", {"neu_übernommen": take_new, "begründung": note})

    def nmf_prices(self, tax_year: int | None = None) -> list[dict]:
        if tax_year:
            return self.db.query("SELECT * FROM nmf_prices WHERE tax_year=? ORDER BY isin", (tax_year,))
        return self.db.query("SELECT * FROM nmf_prices ORDER BY tax_year, isin")

    # ------------------------------------------------------------------ #
    # CSV-Profile & Exporte
    # ------------------------------------------------------------------ #
    def save_csv_profile(self, name: str, mapping: dict, options: dict) -> None:
        self.db.execute("INSERT INTO csv_profiles(name, mapping_json, options_json, created_at) VALUES(?,?,?,?) "
                        "ON CONFLICT(name) DO UPDATE SET mapping_json=excluded.mapping_json, "
                        "options_json=excluded.options_json",
                        (name, json.dumps(mapping, ensure_ascii=False), json.dumps(options, ensure_ascii=False),
                         now_iso()))

    def csv_profiles(self) -> list[dict]:
        rows = self.db.query("SELECT * FROM csv_profiles ORDER BY name")
        for r in rows:
            r["mapping"] = json.loads(r["mapping_json"])
            r["options"] = json.loads(r["options_json"] or "{}")
        return rows

    def record_export(self, tax_year: int | None, kind: str, path: Path, sha: str | None = None,
                      notes: str | None = None) -> int:
        return self.db.execute("INSERT INTO exports(ts, tax_year, kind, stored_path, sha256, notes) VALUES(?,?,?,?,?,?)",
                               (now_iso(), tax_year, kind, self.store.relative(path), sha, notes))

    def exports(self, tax_year: int | None = None) -> list[dict]:
        if tax_year:
            return self.db.query("SELECT * FROM exports WHERE tax_year=? ORDER BY id DESC", (tax_year,))
        return self.db.query("SELECT * FROM exports ORDER BY id DESC")

    # ------------------------------------------------------------------ #
    def stats(self, tax_year: int | None = None) -> dict:
        def count(sql, params=()):
            return (self.db.one(sql, params) or {"n": 0})["n"]

        y = str(tax_year) if tax_year else None
        return {
            "brokers": count("SELECT COUNT(*) n FROM brokers"),
            "depots": count("SELECT COUNT(*) n FROM depots WHERE active=1"),
            "documents": count("SELECT COUNT(*) n FROM documents" + (" WHERE tax_year=?" if y else ""),
                               (int(y),) if y else ()),
            "documents_total": count("SELECT COUNT(*) n FROM documents"),
            "transactions": count("SELECT COUNT(*) n FROM transactions WHERE deleted=0" +
                                  (" AND substr(trade_date,1,4)=?" if y else ""), (y,) if y else ()),
            "open_conflicts": count("SELECT COUNT(*) n FROM conflicts WHERE status='offen'"),
            "docs_to_review": count("SELECT COUNT(*) n FROM documents WHERE status IN ('pruefen','teilweise','neu')"),
        }


def iter_chunks(items: Iterable, n: int):
    buf = []
    for it in items:
        buf.append(it)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf
