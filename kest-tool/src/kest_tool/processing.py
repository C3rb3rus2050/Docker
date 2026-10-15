"""Stapelverarbeitung abgelegter PDF-Dokumente zu Buchungen.

Nur Dokumente mit vollständiger, widerspruchsfreier Extraktion werden automatisch übernommen (Prüfstatus der
Buchung: „ungeprueft“). Alles andere bleibt im Status „pruefen“ und wird mit Grund gemeldet – es wird nichts
geschätzt und kein Dokument als verarbeitet gemeldet, wenn Werte fehlen.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError

from .importers.pdf_importer import PdfError, extract_pdf
from .models import ReviewStatus, TransactionIn, TxType
from .repository import Repository

log = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    document_id: int
    filename: str
    status: str          # angelegt | dublette | beleg | pruefen | uebersprungen | fehler
    message: str
    transaction_id: int | None = None
    action: str = ""     # Was tun? (verständlicher nächster Schritt)


BROKER_NAMES = {"TradeRepublic": "Trade Republic", "ScalableCapital": "Scalable Capital"}
INFO_ONLY = {"Informationsdokument", "Vorabpauschale (DE)"}


def _problems(ex: dict) -> tuple[str, str]:
    """Fehler/Warnungen des Prüfberichts als (Meldung, Was tun)."""
    probs = [c for c in ex.get("checks", []) if c["result"] in ("error", "warn")]
    if not probs:
        msg = "; ".join(ex.get("warnings", [])) or "unvollständig"
        return msg, "Dokument unter „Dokumente“ öffnen und die Werte im Prüfformular ergänzen."
    msg = "; ".join(c["detail"] for c in probs)
    actions = list(dict.fromkeys(c["action"] for c in probs if c.get("action")))
    return msg, " ".join(actions)


def _ensure_broker_depot(repo: Repository, broker_key: str) -> tuple[int | None, str]:
    """Legt für einen erkannten Broker ohne Depot automatisch Broker + Depot an."""
    if broker_key not in BROKER_NAMES:
        return None, ""
    deps = [d for d in repo.depots(active_only=True) if d["broker_key"] == broker_key]
    if deps:
        return None, ""
    name = BROKER_NAMES[broker_key]
    bid = repo.add_broker(name, broker_key)
    did = repo.add_depot(bid, f"{name} Depot")
    return did, f"Depot „{name} Depot“ automatisch angelegt"


def humanize_validation(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        texts = {"Kauf/Verkauf benötigt eine Stückzahl": "Stückzahl fehlt",
                 "Kauf/Verkauf benötigt eine ISIN": "ISIN fehlt"}
        out = []
        for e in exc.errors():
            msg = str(e.get("msg", "")).replace("Value error, ", "")
            out.append(texts.get(msg, msg))
        return "; ".join(out)
    return str(exc)


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
    if default_depot is None:
        return None
    selected = next((d for d in deps if d["id"] == default_depot), None)
    if selected is None:
        return None
    # Never silently assign an identifiable broker's document to a different broker.
    if doc.get("broker_id") and selected["broker_id"] != doc["broker_id"]:
        return None
    if key in BROKER_NAMES and selected["broker_key"] != key:
        return None
    return default_depot


def extraction_for(repo: Repository, doc: dict) -> dict:
    if doc.get("extraction_json"):
        try:
            cached = json.loads(doc["extraction_json"])
            if isinstance(cached, dict) and "fields" in cached:
                return cached
        except (json.JSONDecodeError, TypeError):
            log.warning("Invalid extraction cache for document #%s; reading again", doc["id"])
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
                      reextract: bool = False) -> list[ProcessResult]:
    """Verarbeitet PDF-Dokumente ohne zugeordnete Buchung.

    Gespeicherte Extraktionen werden standardmäßig wiederverwendet. Mit ``reextract=True`` werden sie
    explizit aktualisiert, ohne den bisherigen Prüfbericht vor erfolgreicher Extraktion zu löschen.
    """
    docs = [repo.document(i) for i in doc_ids] if doc_ids else repo.documents()
    results: list[ProcessResult] = []
    run_id = None
    for doc in docs:
        try:
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
                    refreshed = extract_pdf(repo.document_path(doc).read_bytes()).to_dict()
                    repo.update_document(doc["id"], extraction_json=json.dumps(refreshed, ensure_ascii=False, default=str))
                    ex = refreshed
                else:
                    ex = extraction_for(repo, doc)
            except (PdfError, OSError) as exc:
                repo.update_document(doc["id"], status="fehlgeschlagen")
                results.append(ProcessResult(doc["id"], name, "fehler", f"Datei nicht lesbar: {exc}",
                                             action="Datei im Original öffnen; ist sie beschädigt oder ein Scan ohne Text, "
                                                    "die Werte manuell unter „Transaktionen“ erfassen."))
                continue
            if not ex.get("creates_transaction", True):
                msg, action = _problems(ex) if any(c["result"] in ("error", "warn") for c in ex.get("checks", [])) \
                    else (f"{ex.get('doc_type')}: keine Einzelbuchung", "")
                if ex.get("doc_type") in INFO_ONLY:
                    repo.update_document(doc["id"], status="verarbeitet", doc_type=ex.get("doc_type"))
                    info = next((c for c in ex.get("checks", []) if c["name"] == "Dokumentart"), {})
                    results.append(ProcessResult(doc["id"], name, "beleg", info.get("detail") or msg,
                                                 action=info.get("action", "")))
                else:
                    repo.update_document(doc["id"], status="pruefen", doc_type=ex.get("doc_type") or doc["doc_type"])
                    info = next((c for c in ex.get("checks", []) if c["name"] == "Dokumentart"), {})
                    results.append(ProcessResult(doc["id"], name, "pruefen", info.get("detail") or msg,
                                                 action=info.get("action") or action))
                continue
            if not ex.get("complete") or ex.get("warnings"):
                msg, action = _problems(ex)
                repo.update_document(doc["id"], status="pruefen")
                results.append(ProcessResult(doc["id"], name, "pruefen", msg, action=action))
                continue
            depot_id = resolve_depot(repo, doc, ex.get("broker"), default_depot)
            created_note = ""
            if not depot_id:
                depot_id, created_note = _ensure_broker_depot(repo, ex.get("broker") or "")
            if not depot_id:
                repo.update_document(doc["id"], status="pruefen")
                known = BROKER_NAMES.get(ex.get("broker") or "")
                results.append(ProcessResult(
                    doc["id"], name, "pruefen",
                    f"Depot nicht eindeutig ({known + ' hat mehrere Depots' if known else 'Broker nicht erkannt'})",
                    action="Oben ein Standarddepot auswählen und erneut verarbeiten – oder das Dokument unter „Dokumente“ "
                           "einzeln übernehmen."))
                continue
            try:
                tx = transaction_from_extraction(ex, depot_id, doc)
            except (ValidationError, ValueError, KeyError) as exc:
                repo.update_document(doc["id"], status="pruefen")
                results.append(ProcessResult(doc["id"], name, "pruefen", f"Werte ungültig: {humanize_validation(exc)}",
                                             action="Dokument unter „Dokumente“ öffnen und die Werte korrigieren."))
                continue
            dup = repo.find_duplicates(tx)
            if dup["exact"]:
                repo.link_document(doc["id"], dup["exact"][0]["id"], "beleg")
                repo.update_document(doc["id"], status="verarbeitet")
                results.append(ProcessResult(doc["id"], name, "dublette",
                                             f"Buchung existiert bereits (#{dup['exact'][0]['id']}) – als Beleg verknüpft"))
                continue
            if dup["possible"]:
                # Suspected duplicates must not enter tax calculations before human review.
                repo.update_document(doc["id"], status="pruefen")
                ids = [r["id"] for r in dup["possible"]]
                results.append(ProcessResult(doc["id"], name, "pruefen",
                                             f"Ähnliche Buchung(en) bereits vorhanden: {ids}",
                                             action="Unter Dokumente die Buchungen vergleichen und den Beleg "
                                                    "zuordnen oder die Buchung manuell übernehmen."))
                continue
            if run_id is None:
                run_id = repo.start_import("PDF-Stapelverarbeitung")
            tid = repo.add_transaction(tx, import_run_id=run_id)
            repo.update_document(doc["id"], status="verarbeitet",
                                 tax_year=tx.trade_date.year, doc_type=ex.get("doc_type") or doc["doc_type"])
            repo.log_import(run_id, "INFO", f"{name}: Buchung #{tid} angelegt")
            results.append(ProcessResult(doc["id"], name, "angelegt", f"Buchung #{tid} ({tx.tx_type.value} "
                                         f"{tx.isin or ''} {tx.trade_date.isoformat()})"
                                         + (f" – {created_note}" if created_note else ""), tid,
                                         action=""))
        except Exception as exc:  # continue with remaining documents even after an unexpected failure
            doc_id = doc.get("id") if doc else None
            log.exception("PDF processing failed for document ID %s", doc_id)
            if doc_id is not None:
                try:
                    if not repo.transactions_for_document(doc_id):
                        repo.update_document(doc_id, status="fehlgeschlagen")
                except Exception:
                    log.exception("Failed to mark document ID %s as failed", doc_id)
            results.append(ProcessResult(doc_id or 0, (doc or {}).get("original_filename", "Unbekannt"),
                                         "fehler", f"Verarbeitung fehlgeschlagen ({type(exc).__name__})",
                                         action="Dokument unter Dokumente prüfen; bei Bedarf den "
                                                "Diagnosebericht unter Einstellungen exportieren."))
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
        "AND NOT EXISTS (SELECT 1 FROM document_links l JOIN transactions lt ON lt.id=l.transaction_id "
        "WHERE l.document_id=d.id AND lt.deleted=0)")
    return {
        "depots": len(repo.depots(active_only=True)),
        "tx_by_year": {int(r["y"]): r["n"] for r in years},
        "tx_year": next((r["n"] for r in years if int(r["y"]) == year), 0),
        "docs_open": docs_open,
        "docs_total": len(repo.documents()),
    }


# --------------------------------------------------------------------------- #
# Ablage beliebiger hochgeladener Dateien (PDF, ZIP, CSV)
STATUS_TEXT = {"vollstaendig": "alle Pflichtwerte erkannt – trotzdem prüfen",
               "unvollstaendig": "unvollständig/unsicher – manuelle Prüfung erforderlich",
               "pruefen": "Beleg ohne Einzelbuchung – manuell prüfen",
               "fehlgeschlagen": "keine Werte erkannt"}
MAX_ZIP_FILES = 2000
MAX_ZIP_TOTAL = 500 * 1024 * 1024


def store_pdf(repo: Repository, data: bytes, name: str, fallback_year: int, method: str,
              fallback_source: str = "Unclassified", engine: str = "auto") -> tuple[dict, dict, bool]:
    """Legt ein PDF ab (Jahr/Quelle aus dem Inhalt) und speichert das Extraktionsergebnis."""
    from .models import DOC_SOURCES

    ex = extract_pdf(data, engine)
    exd = ex.to_dict()
    exd["status_text"] = STATUS_TEXT[ex.status]
    year = ex.value("trade_date").year if ex.value("trade_date") else fallback_year
    source = ex.broker if ex.broker in DOC_SOURCES else fallback_source
    doc, new = repo.add_document(data, name, doc_type=ex.doc_type, source=source, tax_year=year,
                                 import_method=method, status="pruefen" if ex.status != "vollstaendig" else "neu")
    if new:
        repo.update_document(doc["id"], extraction_json=json.dumps(exd, ensure_ascii=False, default=str))
    return repo.document(doc["id"]), exd, new


def expand_upload(name: str, data: bytes) -> list[tuple[str, bytes]]:
    """Expand nested ZIPs with bounded memory, recursion and file counts.

    Archived paths are deliberately discarded; uploaded documents are stored
    by sanitized filename and content hash, never by archive path.
    """
    import io
    import zipfile
    from pathlib import PurePosixPath

    if not name.lower().endswith(".zip"):
        return [(name, data)]

    max_entry = 50 * 1024 * 1024
    allowed = (".pdf", ".csv", ".txt", ".xlsx")
    output: list[tuple[str, bytes]] = []
    total_bytes = 0
    entry_count = 0

    def unpack(blob: bytes, depth: int) -> None:
        nonlocal total_bytes, entry_count
        if depth > 2:
            raise ValueError("ZIP-Archive dürfen höchstens zwei weitere ZIP-Ebenen enthalten")
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    entry_count += 1
                    if entry_count > MAX_ZIP_FILES:
                        raise ValueError(f"ZIP enthält mehr als {MAX_ZIP_FILES} Dateien")
                    filename = PurePosixPath(info.filename.replace("\\", "/")).name
                    if not filename or filename.startswith("."):
                        continue
                    if not filename.lower().endswith(allowed + (".zip",)):
                        continue
                    if info.flag_bits & 1:
                        raise ValueError("Passwortgeschützte ZIP-Dateien werden nicht unterstützt")
                    if info.file_size > max_entry:
                        raise ValueError(f"ZIP-Eintrag „{filename}“ ist größer als 50 MB")
                    if total_bytes + info.file_size > MAX_ZIP_TOTAL:
                        raise ValueError("ZIP-Inhalt ist größer als 500 MB")
                    with archive.open(info) as source:
                        content = source.read(max_entry + 1)
                    if len(content) > max_entry or len(content) != info.file_size:
                        raise ValueError(f"ZIP-Eintrag „{filename}“ hat eine ungültige Größe")
                    total_bytes += len(content)
                    if filename.lower().endswith(".zip"):
                        unpack(content, depth + 1)
                    else:
                        output.append((filename, content))
        except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, RuntimeError) as exc:
            raise ValueError(f"„{name}“ enthält beschädigte oder nicht lesbare ZIP-Daten") from exc

    unpack(data, 0)
    return output

@dataclass
class UploadResult:
    pdf_ids: list
    csv_docs: list           # (Dokument, als OeKB erkannt?)
    skipped: list            # (Dateiname, Grund)
    duplicates: int = 0


def store_uploads(repo: Repository, files: list[tuple[str, bytes]], fallback_year: int,
                  engine: str = "auto", method: str = "upload") -> UploadResult:
    """Legt alle Dateien ab. PDFs werden zur Verarbeitung vorgemerkt, CSV/XLSX gesondert gemeldet."""
    res = UploadResult([], [], [])
    for name, data in files:
        low = name.lower()
        try:
            if low.endswith(".pdf"):
                if not data.startswith(b"%PDF-"):
                    res.skipped.append((name, "keine gültige PDF-Datei"))
                    continue
                doc, _, new = store_pdf(repo, data, name, fallback_year, method, engine=engine)
                res.duplicates += int(not new)
                if new:
                    res.pdf_ids.append(doc["id"])
            elif low.endswith((".csv", ".txt", ".xlsx")):
                head = data[:4000].decode("utf-8", errors="ignore").lower()
                is_oekb = "isin" in head and ("meldedatum" in head or "ausschüttungsgleich" in head)
                doc, new = repo.add_document(data, name, doc_type="OeKB-Fondsmeldung" if is_oekb else
                                             "Transaktionsexport (CSV)", source="OeKB" if is_oekb else "Unclassified",
                                             tax_year=fallback_year, import_method=method, status="pruefen")
                res.duplicates += int(not new)
                if new:
                    res.csv_docs.append((doc, is_oekb))
            else:
                res.skipped.append((name, "Dateityp wird nicht unterstützt (erlaubt: PDF, ZIP, CSV, XLSX)"))
        except (PdfError, ValueError) as exc:
            res.skipped.append((name, f"Dokument nicht verarbeitbar: {exc}"))
        except OSError as exc:
            res.skipped.append((name, f"Speichern fehlgeschlagen: {exc}"))
    return res
