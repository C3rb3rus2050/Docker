"""Stapelverarbeitung abgelegter PDF-Dokumente zu Buchungen.

Nur Dokumente mit vollständiger, widerspruchsfreier Extraktion werden automatisch übernommen (Prüfstatus der
Buchung: „ungeprueft“). Alles andere bleibt im Status „pruefen“ und wird mit Grund gemeldet – es wird nichts
geschätzt und kein Dokument als verarbeitet gemeldet, wenn Werte fehlen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError

from .importers.pdf_importer import PdfError, extract_pdf
from .models import ReviewStatus, TransactionIn, TxType
from .repository import Repository


@dataclass
class ProcessResult:
    document_id: int
    filename: str
    status: str          # angelegt | dublette | pruefen | uebersprungen | fehler
    message: str
    transaction_id: int | None = None


def resolve_depot(repo: Repository, doc: dict, broker_key: str | None, default_depot: int | None) -> int | None:
    """Ordnet ein Dokument einem Depot zu: eindeutiges Depot des Brokers, sonst Standarddepot."""
    deps = repo.depots(active_only=True)
    if doc.get("broker_id"):
        cand = [d for d in deps if d["broker_id"] == doc["broker_id"]]
        if len(cand) == 1:
            return cand[0]["id"]
    key = broker_key or doc.get("source")
    cand = [d for d in deps if d["broker_key"] == key]
    if len(cand) == 1:
        return cand[0]["id"]
    return default_depot


def extraction_for(repo: Repository, doc: dict) -> dict:
    if doc.get("extraction_json"):
        return json.loads(doc["extraction_json"])
    ex = extract_pdf(repo.document_path(doc).read_bytes()).to_dict()
    repo.update_document(doc["id"], extraction_json=json.dumps(ex, ensure_ascii=False, default=str))
    return ex


def transaction_from_extraction(ex: dict, depot_id: int, doc: dict) -> TransactionIn:
    f = ex.get("fields", {})

    def v(name, default=None):
        fld = f.get(name)
        return fld.get("value") if fld and fld.get("value") is not None else default

    d = v("trade_date")
    return TransactionIn(
        depot_id=depot_id, tx_type=TxType(ex["tx_type"]),
        trade_date=date.fromisoformat(d) if isinstance(d, str) else d,
        isin=v("isin"), security_name=v("security_name"), quantity=v("quantity"), price=v("price"),
        amount=v("amount"), fees=v("fees", 0.0) or 0.0, currency=v("currency", "EUR") or "EUR",
        fx_rate=v("fx_rate"), withholding_tax=v("withholding_tax", 0.0) or 0.0,
        withholding_country=v("withholding_country"), kest_at_eur=v("kest_at_eur", 0.0) or 0.0,
        source_type="pdf", source_ref=doc["original_filename"], document_id=doc["id"],
        notes="automatisch aus PDF übernommen", review_status=ReviewStatus.UNCHECKED,
    )


def process_documents(repo: Repository, doc_ids: list[int] | None = None, default_depot: int | None = None,
                      reextract: bool = True) -> list[ProcessResult]:
    """Verarbeitet PDF-Dokumente ohne zugeordnete Buchung.

    Standardmäßig wird neu ausgelesen, damit Verbesserungen der Erkennung auch für früher abgelegte Dokumente greifen.
    """
    docs = [repo.document(i) for i in doc_ids] if doc_ids else repo.documents()
    results: list[ProcessResult] = []
    run_id = None
    for doc in docs:
        if not doc or doc.get("file_type") != "pdf":
            continue
        name = doc["original_filename"]
        if repo.transactions_for_document(doc["id"]):
            results.append(ProcessResult(doc["id"], name, "uebersprungen", "hat bereits Buchungen"))
            continue
        if doc["status"] == "ignoriert":
            continue
        try:
            if reextract:
                repo.update_document(doc["id"], extraction_json=None)
                doc = repo.document(doc["id"])
            ex = extraction_for(repo, doc)
        except (PdfError, OSError) as exc:
            repo.update_document(doc["id"], status="fehlgeschlagen")
            results.append(ProcessResult(doc["id"], name, "fehler", str(exc)))
            continue
        if not ex.get("creates_transaction", True):
            results.append(ProcessResult(doc["id"], name, "pruefen",
                                         f"{ex.get('doc_type')}: keine Einzelbuchung – manuell prüfen"))
            continue
        if not ex.get("complete") or ex.get("warnings"):
            reasons = []
            if ex.get("missing"):
                reasons.append("fehlt: " + ", ".join(ex["missing"]))
            reasons += ex.get("warnings", [])
            if not ex.get("tx_type"):
                reasons.append("Buchungsart nicht erkannt")
            repo.update_document(doc["id"], status="pruefen")
            results.append(ProcessResult(doc["id"], name, "pruefen", "; ".join(reasons) or "unvollständig"))
            continue
        depot_id = resolve_depot(repo, doc, ex.get("broker"), default_depot)
        if not depot_id:
            results.append(ProcessResult(doc["id"], name, "pruefen",
                                         "Depot nicht eindeutig – Standarddepot wählen oder Depot anlegen"))
            continue
        try:
            tx = transaction_from_extraction(ex, depot_id, doc)
        except (ValidationError, ValueError, KeyError) as exc:
            repo.update_document(doc["id"], status="pruefen")
            results.append(ProcessResult(doc["id"], name, "pruefen", f"Werte ungültig: {exc}"))
            continue
        dup = repo.find_duplicates(tx)
        if dup["exact"]:
            repo.link_document(doc["id"], dup["exact"][0]["id"], "beleg")
            repo.update_document(doc["id"], status="verarbeitet")
            results.append(ProcessResult(doc["id"], name, "dublette",
                                         f"Buchung existiert bereits (#{dup['exact'][0]['id']}) – als Beleg verknüpft"))
            continue
        if run_id is None:
            run_id = repo.start_import("PDF-Stapelverarbeitung")
        if dup["possible"]:
            tx = tx.model_copy(update={"review_status": ReviewStatus.TO_REVIEW,
                                       "notes": f"automatisch aus PDF; Dublettenverdacht zu "
                                                f"{[r['id'] for r in dup['possible']]}"})
        tid = repo.add_transaction(tx, import_run_id=run_id)
        repo.update_document(doc["id"], status="verarbeitet",
                             tax_year=tx.trade_date.year, doc_type=ex.get("doc_type") or doc["doc_type"])
        repo.log_import(run_id, "INFO", f"{name}: Buchung #{tid} angelegt")
        results.append(ProcessResult(doc["id"], name, "angelegt", f"Buchung #{tid} ({tx.tx_type.value} "
                                     f"{tx.isin or ''} {tx.trade_date.isoformat()})", tid))
    if run_id is not None:
        n = sum(1 for r in results if r.status == "angelegt")
        repo.finish_import(run_id, "abgeschlossen", rows_total=len(results), rows_imported=n,
                           rows_duplicates=sum(1 for r in results if r.status == "dublette"),
                           rows_skipped=sum(1 for r in results if r.status in ("pruefen", "uebersprungen")),
                           rows_errors=sum(1 for r in results if r.status == "fehler"),
                           message=f"{n} Buchungen aus PDFs angelegt")
    return results


def data_status(repo: Repository, year: int) -> dict:
    """Übersicht für „Warum wird nichts berechnet?“."""
    years = repo.db.query("SELECT substr(trade_date,1,4) y, COUNT(*) n FROM transactions WHERE deleted=0 "
                          "GROUP BY y ORDER BY y")
    docs_open = repo.db.query(
        "SELECT d.* FROM documents d WHERE d.status IN ('neu','pruefen','teilweise','fehlgeschlagen') "
        "AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.document_id=d.id AND t.deleted=0) "
        "AND NOT EXISTS (SELECT 1 FROM document_links l WHERE l.document_id=d.id)")
    return {
        "depots": len(repo.depots(active_only=True)),
        "tx_by_year": {int(r["y"]): r["n"] for r in years},
        "tx_year": next((r["n"] for r in years if int(r["y"]) == year), 0),
        "docs_open": docs_open,
        "docs_total": len(repo.documents()),
    }
