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
                                     f"{tx.isin or ''} {tx.trade_date.isoformat()})"
                                     + (f" – {created_note}" if created_note else ""), tid,
                                     action="Dubletten-Verdacht prüfen (Seite Transaktionen)" if dup["possible"] else ""))
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
    """Entpackt ZIP-Archive sicher (nur PDF/CSV/XLSX, keine Pfade, Größenlimits); andere Dateien unverändert."""
    import io
    import zipfile
    from pathlib import PurePosixPath

    if not name.lower().endswith(".zip"):
        return [(name, data)]
    out, total = [], 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            if len(infos) > MAX_ZIP_FILES:
                raise ValueError(f"ZIP enthält zu viele Dateien ({len(infos)})")
            for info in infos:
                base = PurePosixPath(info.filename.replace("\\", "/")).name
                if not base.lower().endswith((".pdf", ".csv", ".xlsx")) or base.startswith("."):
                    continue
                total += info.file_size
                if total > MAX_ZIP_TOTAL:
                    raise ValueError("ZIP-Inhalt ist zu groß")
                out.append((base, zf.read(info)))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"„{name}“ ist kein gültiges ZIP-Archiv") from exc
    return out


@dataclass
class UploadResult:
    pdf_ids: list
    csv_docs: list           # (Dokument, als OeKB erkannt?)
    skipped: list            # (Dateiname, Grund)
    duplicates: int = 0


def store_uploads(repo: Repository, files: list[tuple[str, bytes]], fallback_year: int,
                  engine: str = "auto") -> UploadResult:
    """Legt alle Dateien ab. PDFs werden zur Verarbeitung vorgemerkt, CSV/XLSX gesondert gemeldet."""
    res = UploadResult([], [], [])
    for name, data in files:
        low = name.lower()
        try:
            if low.endswith(".pdf"):
                if not data.startswith(b"%PDF-"):
                    res.skipped.append((name, "keine gültige PDF-Datei"))
                    continue
                doc, _, new = store_pdf(repo, data, name, fallback_year, "upload", engine=engine)
                res.duplicates += int(not new)
                res.pdf_ids.append(doc["id"])
            elif low.endswith((".csv", ".txt", ".xlsx")):
                head = data[:4000].decode("utf-8", errors="ignore").lower()
                is_oekb = "isin" in head and ("meldedatum" in head or "ausschüttungsgleich" in head)
                doc, new = repo.add_document(data, name, doc_type="OeKB-Fondsmeldung" if is_oekb else
                                             "Transaktionsexport (CSV)", source="OeKB" if is_oekb else "Unclassified",
                                             tax_year=fallback_year, import_method="upload", status="pruefen")
                res.duplicates += int(not new)
                res.csv_docs.append((doc, is_oekb))
            else:
                res.skipped.append((name, "Dateityp wird nicht unterstützt (erlaubt: PDF, ZIP, CSV, XLSX)"))
        except PdfError as exc:
            res.skipped.append((name, f"PDF nicht lesbar: {exc}"))
        except OSError as exc:
            res.skipped.append((name, f"Speichern fehlgeschlagen: {exc}"))
    return res
