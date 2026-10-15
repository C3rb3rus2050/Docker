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

from .importers.pdf_importer import PARSER_VERSION, PdfError, extract_pdf
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
INFO_ONLY = {"Informationsdokument", "Vorabpauschale (DE)", "Kontoauszug", "Depotauszug", "Kosteninformation", "Zahlungsbeleg"}


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


def extraction_for(repo: Repository, doc: dict, **analysis_options) -> dict:
    if doc.get("extraction_json"):
        try:
            cached = json.loads(doc["extraction_json"])
            if isinstance(cached, dict) and "fields" in cached and cached.get("parser_version") == PARSER_VERSION:
                fields = cached["fields"]
                needs_fx = (fields.get("currency", {}).get("value") not in (None, "EUR")
                            and not fields.get("fx_rate", {}).get("value")
                            and analysis_options.get("fx_service") is not None)
                needs_ocr = cached.get("missing") and analysis_options.get("ocr_enabled")
                if not needs_fx and not needs_ocr:
                    return cached
        except (json.JSONDecodeError, TypeError):
            log.warning("Invalid extraction cache for document #%s; reading again", doc["id"])
    ex = extract_pdf(repo.document_path(doc).read_bytes(), **analysis_options).to_dict()
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
        value_date=date.fromisoformat(v("value_date")) if isinstance(v("value_date"), str) else v("value_date"),
        isin=v("isin"), security_name=v("security_name"), quantity=v("quantity"), price=v("price"),
        amount=v("amount"), fees=v("fees", 0.0) or 0.0, currency=v("currency", "EUR") or "EUR",
        fx_rate=v("fx_rate"), fx_source=v("fx_source"), withholding_tax=v("withholding_tax", 0.0) or 0.0,
        withholding_country=v("withholding_country"), kest_at_eur=v("kest_at_eur", 0.0) or 0.0,
        source_type="pdf", source_ref=doc["original_filename"], document_id=doc["id"],
        notes="automatisch aus PDF übernommen", review_status=ReviewStatus.UNCHECKED,
    )


def process_documents(repo: Repository, doc_ids: list[int] | None = None, default_depot: int | None = None,
                      reextract: bool = False, **analysis_options) -> list[ProcessResult]:
    """Verarbeitet PDF-Dokumente ohne zugeordnete Buchung.

    Gespeicherte Extraktionen werden standardmäßig wiederverwendet. Mit ``reextract=True`` werden sie
    explizit aktualisiert, ohne den bisherigen Prüfbericht vor erfolgreicher Extraktion zu löschen.
    """
    docs = [repo.document(i) for i in doc_ids] if doc_ids is not None else repo.documents()
    results: list[ProcessResult] = []
    run_id = None
    for doc in docs:
        try:
            if not doc or doc.get("file_type") != "pdf":
                continue
            name = doc["original_filename"]
            linked = repo.transactions_for_document(doc['id'])
            if linked and not reextract:
                results.append(ProcessResult(doc["id"], name, "uebersprungen", "hat bereits Buchungen"))
                continue
            if doc["status"] == "ignoriert":
                continue
            try:
                if reextract:
                    refreshed = extract_pdf(repo.document_path(doc).read_bytes(), **analysis_options).to_dict()
                    repo.update_document(doc["id"], extraction_json=json.dumps(refreshed, ensure_ascii=False, default=str))
                    ex = refreshed
                else:
                    ex = extraction_for(repo, doc, **analysis_options)
            except (PdfError, OSError) as exc:
                repo.update_document(doc["id"], status="fehlgeschlagen")
                results.append(ProcessResult(doc["id"], name, "fehler", f"Datei nicht lesbar: {exc}",
                                             action="Datei im Original öffnen; ist sie beschädigt oder ein Scan ohne Text, "
                                                    "die Werte manuell unter „Transaktionen“ erfassen."))
                continue
            if linked:
                originals = [t for t in linked if t.get('document_id') == doc['id'] and t.get('source_type') == 'pdf']
                differences = []
                if len(originals) == 1:
                    original = originals[0]
                    if not ex.get('creates_transaction', True):
                        differences.append(f"Dokumentart jetzt {ex.get('doc_type')}; keine bestätigte Einzelbuchung")
                    elif ex.get('tx_type') and ex['tx_type'] != original['tx_type']:
                        differences.append(f"Buchungsart: bisher {original['tx_type']}, neu {ex['tx_type']}")
                    for field, label in (('trade_date', 'Datum'), ('isin', 'ISIN'), ('currency', 'Währung'),
                                         ('quantity', 'Stückzahl'), ('amount', 'Bruttobetrag')):
                        candidate = ex.get('fields', {}).get(field, {})
                        value = candidate.get('value')
                        if value is None or candidate.get('confidence', 0) < .8:
                            continue
                        old = original.get(field)
                        changed = abs(float(value) - float(old)) > (.02 if field == 'amount' else 1e-6) \
                            if field in ('quantity', 'amount') and old is not None else str(value) != str(old)
                        if changed:
                            differences.append(f'{label}: bisher {old}, neu {value}')
                    if differences:
                        reason = 'Neue Dokumenterkennung weicht von der bestehenden Buchung ab: ' + '; '.join(differences)
                        repo.update_transaction(original['id'], {'review_status': 'pruefen'}, reason)
                        repo.update_document(doc['id'], status='pruefen', notes=reason, doc_type=ex.get('doc_type') or doc['doc_type'])
                        repo.document_event(doc['id'], 'Abweichende Neuanalyse', {'buchung': original['id'], 'abweichungen': differences})
                        results.append(ProcessResult(doc['id'], name, 'pruefen', reason, original['id'],
                            'Original und bestehende Buchung vergleichen. Finanzielle Werte wurden nicht überschrieben.'))
                        continue
                results.append(ProcessResult(doc['id'], name, 'uebersprungen',
                    'Prüfbericht aktualisiert; bestehende Buchungen bleiben erhalten.'))
                continue
            if not ex.get("creates_transaction", True):
                if ex.get('doc_type') == 'OeKB-Fondsmeldung':
                    results.append(process_fund_pdf(repo, doc, **analysis_options))
                    continue
                msg, action = _problems(ex) if any(c["result"] in ("error", "warn") for c in ex.get("checks", [])) \
                    else (f"{ex.get('doc_type')}: keine Einzelbuchung", "")
                if ex.get("doc_type") in INFO_ONLY and ex.get('classification', {}).get('confidence', 1) >= .8:
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
            from .diagnostics import record_error
            error_id = record_error("pdf_processing", exc)
            if doc_id is not None:
                try:
                    if not repo.transactions_for_document(doc_id):
                        repo.update_document(doc_id, status="fehlgeschlagen")
                except Exception:
                    log.exception("Failed to mark document ID %s as failed", doc_id)
            results.append(ProcessResult(doc_id or 0, (doc or {}).get("original_filename", "Unbekannt"),
                                         "fehler", f"Verarbeitung fehlgeschlagen ({type(exc).__name__}, ID {error_id})",
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
        "ORDER BY d.tax_year DESC, d.id")
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
            raise ValueError(f"„{name}“ ist kein gültiges ZIP-Archiv oder enthält beschädigte Einträge") from exc

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
                if new or doc['status'] in ('pruefen', 'teilweise'):
                    res.pdf_ids.append(doc["id"])
            elif low.endswith((".csv", ".txt", ".xlsx")):
                head = data[:4000].decode("utf-8", errors="ignore").lower()
                is_oekb = "isin" in head and ("meldedatum" in head or "ausschüttungsgleich" in head)
                doc, new = repo.add_document(data, name, doc_type="OeKB-Fondsmeldung" if is_oekb else
                                             "Transaktionsexport (CSV)", source="OeKB" if is_oekb else "Unclassified",
                                             tax_year=fallback_year, import_method=method, status="pruefen")
                res.duplicates += int(not new)
                if new or doc['status'] in ('pruefen', 'teilweise', 'neu'):
                    res.csv_docs.append((doc, is_oekb))
            else:
                res.skipped.append((name, "Dateityp wird nicht unterstützt (erlaubt: PDF, ZIP, CSV, XLSX)"))
        except (PdfError, ValueError) as exc:
            res.skipped.append((name, f"Dokument nicht verarbeitbar: {exc}"))
        except OSError as exc:
            res.skipped.append((name, f"Speichern fehlgeschlagen: {exc}"))
    return res


def process_fund_pdf(repo: Repository, doc: dict, **analysis_options) -> ProcessResult:
    from .importers.oekb_layouts import extract_published_reports
    from .models import FundReportIn
    reports = extract_published_reports(repo.document_path(doc).read_bytes())
    created = pending = 0
    reasons, years = [], set()
    for report in reports:
        values = dict(report['values'])
        if values.get('report_date'):
            years.add(date.fromisoformat(values['report_date']).year)
        reasons.extend(report['warnings'] + report['missing'])
        if report['warnings'] or report['missing']:
            pending += 1
            continue
        if values.get('currency') != 'EUR' and not values.get('fx_rate'):
            service = analysis_options.get('fx_service')
            day = date.fromisoformat(values['report_date'])
            rates = service.rates(allow_download=analysis_options.get('allow_download', False), needed_until=day) \
                if service and day <= date.today() else None
            found = rates.lookup(values['currency'], day) if rates else None
            if found:
                values['fx_rate'] = found[0]
                values['notes'] = f'EZB {found[1].isoformat()}; {service.url}; Privatanleger ohne Option'
        try:
            rep = FundReportIn(**values, document_id=doc['id'], source='OeKB-PDF / Privatanleger ohne Option')
            result = repo.add_fund_report(rep)
            years.add(rep.report_date.year)
            if result['status'] == 'konflikt':
                pending += 1
                reasons.append('Abweichende Fondsmeldung; Konflikt unter Fonds & OeKB prüfen')
            else:
                created += int(result['status'] == 'neu')
        except ValueError as exc:
            pending += 1
            reasons.append(str(exc))
    if not reports:
        pending = 1
        reasons.append('Kein unterstütztes OeKB-Privatanlegerlayout gefunden')
    message = f'{created} neue Fondsmeldungen, {pending} zur Prüfung.'
    message += ' ' + '; '.join(dict.fromkeys(reasons)) if reasons else ''
    # Keep extracted candidates with their warnings for document-side review.
    cache = json.loads(repo.document(doc['id']).get('extraction_json') or '{}')
    cache['fund_reports'] = reports
    repo.update_document(doc['id'], source='OeKB', doc_type='OeKB-Fondsmeldung',
                         status='teilweise' if created and pending else ('pruefen' if pending else 'verarbeitet'),
                         notes=message, extraction_json=json.dumps(cache, ensure_ascii=False),
                         **({'tax_year': years.pop()} if len(years) == 1 else {}))
    return ProcessResult(doc['id'], doc['original_filename'], 'pruefen' if pending else 'angelegt', message,
                         action='Fondsdaten und Original unter Dokumente prüfen.' if pending else '')


def process_tables(repo: Repository, documents: list, **analysis_options) -> list[ProcessResult]:
    """Automatically route saved tables; only unambiguous rows become bookings."""
    from .importers.automatic import automatic_tables, automatic_mapping, table_broker
    from .importers.csv_importer import ImportOptions, build_preview, commit_preview, auto_mapping, _norm
    from .importers.oekb_importer import _auto_map, FUND_FIELDS, preview_fund_table, commit_fund_previews

    results = []
    for doc, _ in documents:
        try:
            data = repo.document_path(doc).read_bytes()
            tables = automatic_tables(data, doc['original_filename'])
            broker = table_broker(data, doc['original_filename'])
            if broker:
                _ensure_broker_depot(repo, broker)
                repo.update_document(doc['id'], source=broker)
            depot_id = resolve_depot(repo, doc, broker, None)
            if not broker and len(repo.depots(active_only=True)) == 1:
                depot_id = repo.depots(active_only=True)[0]['id']
            imported = duplicates = pending = 0
            reasons = []
            years = set()
            for table in tables:
                fund_map = _auto_map(list(table.columns))
                if all(fund_map.get(k) for k, (_, required, _) in FUND_FIELDS.items() if required):
                    if not fund_map.get('currency'):
                        raise ValueError('Währung fehlt in der Fondstabelle; kein EUR-Standard wird geraten')
                    service = analysis_options.get('fx_service')
                    if service and fund_map.get('report_date'):
                        from .importers.parsing import parse_date
                        if not fund_map.get('fx_rate'):
                            table = table.copy()
                            table['_auto_fx'] = ''
                            fund_map['fx_rate'] = '_auto_fx'
                        for index, record in table.iterrows():
                            cur = str(record[fund_map['currency']]).strip().upper()
                            if cur == 'EUR' or str(record[fund_map['fx_rate']]).strip():
                                continue
                            day = parse_date(record[fund_map['report_date']], None,
                                             ['%d.%m.%Y', '%Y-%m-%d', '%d.%m.%y'])
                            rates = service.rates(allow_download=analysis_options.get('allow_download', False), needed_until=day) \
                                if day <= date.today() else None
                            found = rates.lookup(cur, day) if rates else None
                            if found:
                                table.at[index, fund_map['fx_rate']] = str(found[0])
                    previews = preview_fund_table(table, fund_map, document_id=doc['id'])
                    if service and '_auto_fx' in table:
                        for preview in previews:
                            if preview.report and preview.report.fx_rate:
                                preview.report.notes = f'EZB-Referenzkurs zum Meldedatum oder vorherigen Bankarbeitstag; {service.url}'
                    safe = [p for p in previews if not p.errors and not p.warnings and p.report]
                    report = commit_fund_previews(repo, safe, doc['id'])
                    imported += report['neu']
                    duplicates += report['identisch']
                    pending += len(previews) - len(safe) + report['konflikt']
                    reasons.extend(e for p in previews for e in p.errors + p.warnings)
                    repo.update_document(doc['id'], doc_type='OeKB-Fondsmeldung', source='OeKB')
                    continue
                if not depot_id:
                    raise ValueError('Broker/Depot aus dieser Tabelle nicht eindeutig erkennbar')
                mapping = automatic_mapping(list(table.columns))
                rows = build_preview(table, mapping, ImportOptions(), depot_id, repo)
                gross = _norm(mapping.get('amount') or '') in ('brutto', 'bruttobetrag', 'gross amount', 'kurswert')
                # Generic cash amounts may already include taxes/fees. Keep them for review.
                for row in rows:
                    if row.tx and row.tx.currency != 'EUR' and not row.tx.fx_rate and analysis_options.get('fx_service'):
                        service = analysis_options['fx_service']
                        rates = service.rates(allow_download=analysis_options.get('allow_download', False),
                                              needed_until=row.tx.trade_date)
                        found = rates.lookup(row.tx.currency, row.tx.trade_date) if rates else None
                        if found:
                            rate, rate_day = found
                            row.tx = row.tx.model_copy(update={'fx_rate': rate,
                                'fx_source': f'EZB {rate_day.isoformat()}; {service.url}'})
                            row.warnings = [w for w in row.warnings if not w.startswith('Fremdwährung ')]
                    tax_col = auto_mapping(list(table.columns)).get('kest_at_eur')
                    if tax_col and not mapping.get('kest_at_eur'):
                        row.warnings.append('Kapitalertragsteuer ohne eindeutige österreichische Zuordnung')
                    if not gross:
                        row.warnings.append('Betrag ist nicht ausdrücklich als Brutto/Kurswert gekennzeichnet')
                    if not mapping.get('currency'):
                        row.warnings.append('Währung fehlt in der Tabelle')
                decisions = {r.row_no: ('uebernehmen' if not r.errors and not r.warnings and r.duplicate == 'neu'
                                        else 'ignorieren') for r in rows}
                for row in rows:
                    if decisions[row.row_no] == 'uebernehmen':
                        row.tx = row.tx.model_copy(update={'review_status': ReviewStatus.UNCHECKED})
                result = commit_preview(repo, rows, decisions, import_type='Automatischer Tabellenimport',
                                        depot_id=depot_id, document_id=doc['id'])
                imported += result['rows_imported']
                duplicates += sum(r.duplicate in ('dublette', 'dublette_in_datei') for r in rows)
                pending += sum(decisions[r.row_no] == 'ignorieren' and r.duplicate not in ('dublette', 'dublette_in_datei')
                               for r in rows)
                reasons.extend(e for r in rows if r.duplicate not in ('dublette', 'dublette_in_datei')
                               for e in r.errors + r.warnings)
                years.update(r.tx.trade_date.year for r in rows if r.tx)
            if not any(len(t) for t in tables):
                raise ValueError('Keine Datenzeilen gefunden')
            message = f'{imported} übernommen, {duplicates} Dubletten, {pending} zur Prüfung.'
            if reasons:
                message += ' ' + '; '.join(dict.fromkeys(reasons))
            repo.update_document(doc['id'], status='teilweise' if pending and imported else
                                 ('pruefen' if pending else 'verarbeitet'), notes=message,
                                 **({'tax_year': years.pop()} if len(years) == 1 else {}))
            results.append(ProcessResult(doc['id'], doc['original_filename'], 'pruefen' if pending else 'angelegt',
                                         message, action='Original und Importprotokoll unter Dokumente prüfen.' if pending else ''))
        except (ValueError, OSError) as exc:
            repo.update_document(doc['id'], status='pruefen', notes=str(exc))
            results.append(ProcessResult(doc['id'], doc['original_filename'], 'pruefen', str(exc),
                                         action='Original unter Dokumente prüfen; Datei bleibt vollständig erhalten.'))
    return results
