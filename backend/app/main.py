"""React SPA + FastAPI. All browser writes use the same audited domain services."""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import sqlite3
import zipfile
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError

from kest_tool import __version__
from kest_tool.document_review import save_review
from kest_tool.models import (BROKER_KEYS, DOC_SOURCES, DOC_STATUS, DOC_TYPES, FundReportIn,
                              SecurityIn, TransactionIn, isin_checksum_ok)
from kest_tool.processing import (data_status, expand_upload, extraction_for, process_documents, process_tables,
                                  resolve_depot, store_uploads)
from kest_tool.security_review import review_reasons, save_security_review
from kest_tool.tax.engine import compute
from kest_tool.tax.rules import load_rules

from .runtime import Runtime
from .schemas import Broker, Consent, Decision, Depot, DepotTax, Edit, Nmf, Process, Review, SecurityReview

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / 'frontend' / 'dist'
log = logging.getLogger('kest_tool.api')


def revision(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:24]


def check_revision(row, expected):
    if expected and revision(row) != expected:
        raise HTTPException(409, 'Dieser Eintrag wurde inzwischen geändert. Neu laden und erneut vergleichen.')


def require(row, name='Eintrag'):
    if not row:
        raise HTTPException(404, name + ' nicht gefunden.')
    return row


def clean_doc(doc):
    return {k: v for k, v in doc.items() if k not in {'extraction_json', 'stored_path'}}


def create_app(runtime: Runtime | None = None, dist: Path = DIST):
    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime = runtime or Runtime()
        yield
        if runtime is None:
            app.state.runtime.close()

    api = FastAPI(title='KESt Manager API', version=__version__, lifespan=lifespan)
    if runtime:
        api.state.runtime = runtime

    @api.middleware('http')
    async def browser_boundary(request: Request, call_next):
        # A custom header prevents cross-site HTML form writes without weakening
        # origin checks behind HTTPS proxies. No permissive CORS configuration.
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            length = request.headers.get('content-length', '')
            if length.isdigit() and int(length) > 210 * 1024 * 1024:
                return JSONResponse({'detail': 'Upload zu groß (maximal 200 MB).'}, status_code=413)
            if request.headers.get('x-kest-request') != '1' or request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'detail': 'Anfrage aus dieser Anwendung erforderlich.'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Cache-Control'] = 'no-store' if '/api/' in request.url.path else 'no-cache'
        return response

    @api.exception_handler(ValueError)
    async def value_error(request, exc):
        if isinstance(exc, ValidationError):
            message = '; '.join(str(e['msg']).replace('Value error, ', '') for e in exc.errors())
        else:
            message = str(exc)
        return JSONResponse({'detail': message}, status_code=422)

    @api.exception_handler(sqlite3.IntegrityError)
    async def database_conflict(request, exc):
        return JSONResponse({'detail': 'Eintrag bereits vorhanden oder ungültige Zuordnung.'}, status_code=409)

    @api.exception_handler(OSError)
    async def file_error(request, exc):
        log.exception('Dateioperation fehlgeschlagen')
        return JSONResponse({'detail': 'Datei nicht erreichbar. Ablage und Serverprotokoll prüfen.'}, status_code=422)

    from kest_tool.backup import BackupError
    from kest_tool.fx import FxError
    from kest_tool.prices import PriceError

    @api.exception_handler(BackupError)
    async def backup_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=422)

    @api.exception_handler(zipfile.BadZipFile)
    async def invalid_archive(request, exc):
        return JSONResponse({'detail': 'Keine gültige ZIP-Sicherung.'}, status_code=422)

    async def reference_error(request, exc):
        return JSONResponse({'detail': 'Referenzdaten nicht verfügbar. Verbindung und Kursdienst-Einstellungen prüfen.'}, status_code=422)

    api.add_exception_handler(FxError, reference_error)
    api.add_exception_handler(PriceError, reference_error)

    def rt():
        return api.state.runtime

    @api.get('/api/health')
    def health():
        rt().context.db.one('SELECT 1')
        return {'status': 'ok', 'frontend': dist.joinpath('index.html').is_file(), 'version': __version__}

    @api.get('/api/meta')
    def meta():
        with rt().use() as c:
            years = sorted(set(c.settings.tax_years) | {int(r['y']) for r in c.db.query(
                "SELECT DISTINCT substr(trade_date,1,4) y FROM transactions WHERE deleted=0")})
            latest = c.db.one("SELECT MAX(substr(trade_date,1,4)) y FROM transactions WHERE deleted=0")
            default_year = int(latest['y']) if latest and latest['y'] else c.settings.default_tax_year
            return {'version': __version__, 'years': years, 'default_year': default_year,
                    'brokers': c.repo.brokers(), 'depots': c.repo.depots(), 'doc_types': DOC_TYPES,
                    'doc_sources': DOC_SOURCES, 'doc_status': DOC_STATUS, 'broker_keys': BROKER_KEYS,
                    'schemas': {name: model.model_json_schema() for name, model in
                                [('transaction', TransactionIn), ('security', SecurityIn), ('fund', FundReportIn)]}}

    @api.get('/api/dashboard')
    def dashboard(year: int):
        with rt().use() as c:
            return {'stats': c.repo.stats(year), 'status': data_status(c.repo, year),
                    'recent_imports': c.repo.import_runs(5),
                    'pending': [clean_doc(d) for d in c.repo.documents() if d['status'] in
                                {'neu', 'pruefen', 'teilweise', 'fehlgeschlagen'}][:8]}

    @api.get('/api/documents')
    def documents(year: int | None = None, q: str = '', view: str = 'all'):
        with rt().use() as c:
            docs = c.repo.documents(tax_year=year, search=q or None)
            if view == 'open':
                docs = [d for d in docs if d['status'] in {'neu', 'pruefen', 'teilweise', 'fehlgeschlagen'}]
            elif view == 'done':
                docs = [d for d in docs if d['status'] in {'verarbeitet', 'ignoriert'}]
            return [clean_doc(d) for d in docs]

    @api.get('/api/documents/{did}')
    def document(did: int):
        with rt().use() as c:
            d = require(c.repo.document(did), 'Beleg')
            extraction = json.loads(d.get('extraction_json') or '{}')
            # Reading an existing report never initiates external network access.
            if d['file_type'] == 'pdf' and not extraction:
                extraction = extraction_for(c.repo, d, ocr_enabled=bool(c.settings.get('pdf.ocr_enabled')))
                d = c.repo.document(did)
            return {'document': clean_doc(d), 'revision': revision(d), 'extraction': extraction,
                    'transactions': c.repo.transactions_for_document(did), 'events': c.repo.document_events(did),
                    'suggested_depot': resolve_depot(c.repo, d, extraction.get('broker'), None)}

    @api.get('/api/documents/{did}/original')
    def original(did: int, download: bool = False):
        with rt().use() as c:
            d = require(c.repo.document(did), 'Beleg')
            path = c.repo.document_path(d)
            if not path.is_file():
                raise HTTPException(404, 'Originaldatei fehlt in der Ablage.')
            media = 'application/pdf' if d['file_type'] == 'pdf' else 'application/octet-stream'
            return FileResponse(path, media_type=media, filename=d['original_filename'],
                                content_disposition_type='attachment' if download or media != 'application/pdf' else 'inline')

    @api.get('/api/documents/{did}/preview')
    def table_preview(did: int):
        from kest_tool.importers.automatic import automatic_tables
        import pandas as pd
        with rt().use() as c:
            d = require(c.repo.document(did), 'Beleg')
            if d['file_type'] not in {'csv', 'txt', 'xlsx'}:
                raise ValueError('Für diesen Dateityp ist keine Tabellenansicht verfügbar.')
            result = []
            for frame in automatic_tables(c.repo.document_path(d).read_bytes(), d['original_filename'])[:5]:
                limited = frame.head(300).astype(object)
                result.append({'columns': list(frame.columns), 'total': len(frame),
                               'rows': limited.where(pd.notna(limited), None).to_dict('records')})
            return jsonable_encoder(result)

    @api.patch('/api/documents/{did}')
    def update_document(did: int, edit: Edit):
        with rt().use() as c:
            d = require(c.repo.document(did))
            check_revision(d, edit.revision)
            allowed = {'status', 'notes', 'doc_type', 'source', 'tax_year'}
            if set(edit.values) - allowed:
                raise ValueError('Nicht bearbeitbare Belegfelder.')
            for key, choices in [('status', DOC_STATUS), ('doc_type', DOC_TYPES), ('source', DOC_SOURCES)]:
                if key in edit.values and edit.values[key] not in choices:
                    raise ValueError('Ungültiger Wert: ' + key)
            c.repo.update_document(did, **edit.values)
            c.repo.document_event(did, 'Metadaten über API geändert', {'grund': edit.reason, 'neu': edit.values})
            return {'ok': True}

    @api.post('/api/import')
    def upload(files: list[UploadFile] = File(...), year: int = Form(...), depot_id: int | None = Form(None)):
        if len(files) > 200:
            raise HTTPException(413, 'Höchstens 200 Dateien pro Import.')
        items, total = [], 0
        try:
            for f in files:
                data = f.file.read(50 * 1024 * 1024 + 1)
                total += len(data)
                if len(data) > 50 * 1024 * 1024 or total > 200 * 1024 * 1024:
                    raise HTTPException(413, 'Datei maximal 50 MB; gesamter Import maximal 200 MB.')
                expanded = expand_upload(f.filename or 'datei', data)
                if sum(len(b) for _, b in items) + sum(len(b) for _, b in expanded) > 200 * 1024 * 1024:
                    raise HTTPException(413, 'Entpackter Import überschreitet 200 MB.')
                items.extend(expanded)
            with rt().use() as c:
                stored = store_uploads(c.repo, items, year)
                results = process_documents(c.repo, stored.pdf_ids, depot_id, **rt().analysis())
                results += process_tables(c.repo, stored.csv_docs, default_depot=depot_id, **rt().analysis())
                return {'upload': asdict(stored), 'results': jsonable_encoder(results)}
        finally:
            for f in files:
                f.file.close()

    @api.post('/api/documents/process')
    def reanalyse(body: Process):
        with rt().use() as c:
            docs = [require(c.repo.document(i)) for i in body.ids]
            results = process_documents(c.repo, body.ids, body.depot_id, reextract=True, **rt().analysis())
            tables = [(d, d['source'] == 'OeKB') for d in docs if d['file_type'] in {'csv', 'xlsx', 'txt'}
                      and d['status'] not in {'verarbeitet', 'ignoriert'}]
            results += process_tables(c.repo, tables, default_depot=body.depot_id, **rt().analysis())
            return jsonable_encoder(results)

    @api.post('/api/documents/{did}/review')
    def review(did: int, body: Review):
        with rt().use() as c:
            check_revision(require(c.repo.document(did)), body.revision)
            tid = save_review(c.repo, did, body.values, confirmed=body.confirmed,
                              transaction_id=body.transaction_id, reason=body.reason,
                              duplicate_confirmed=body.duplicate_confirmed)
            return {'id': tid}

    @api.post('/api/documents/{did}/fund-review')
    def fund_review(did: int, body: Review):
        if not body.confirmed:
            raise ValueError('Fondswerte mit dem Original abgleichen und bestätigen.')
        with rt().use() as c:
            d = require(c.repo.document(did))
            check_revision(d, body.revision)
            rep = FundReportIn(**{**body.values, 'document_id': did})
            if not isin_checksum_ok(rep.isin):
                raise ValueError('ISIN-Prüfziffer stimmt nicht.')
            result = c.repo.add_fund_report(rep)
            cached = json.loads(d.get('extraction_json') or '{}')
            multiple = len(cached.get('fund_reports', [])) > 1
            status = 'pruefen' if result['status'] == 'konflikt' else ('teilweise' if multiple else 'verarbeitet')
            c.repo.update_document(did, doc_type='OeKB-Fondsmeldung', status=status, tax_year=rep.report_date.year)
            c.repo.document_event(did, 'Fondsmeldung am Original geprüft', {'meldung': result['id'], 'status': result['status']})
            return result

    @api.post('/api/documents/{did}/link/{tid}')
    def link(did: int, tid: int):
        with rt().use() as c:
            require(c.repo.document(did)); require(c.repo.transaction(tid))
            c.repo.link_document(did, tid)
            return {'ok': True}

    @api.post('/api/documents/{did}/assistant')
    def assistant(did: int, body: Consent):
        from kest_tool.importers.assisted import AssistanceError, suggest
        from kest_tool.importers.pdf_importer import extract_text, _ocr_text
        with rt().use() as c:
            if not body.confirmed or not c.settings.get('assistant.enabled'):
                raise ValueError('KI aktivieren und Übermittlung dieses Belegtexts bestätigen.')
            d = require(c.repo.document(did))
            if d['file_type'] != 'pdf':
                raise ValueError('KI-Vorschläge sind für PDF-Belege verfügbar.')
            data = c.repo.document_path(d).read_bytes()
            text, _ = extract_text(data)
            if not text.strip() and c.settings.get('pdf.ocr_enabled'):
                text = _ocr_text(data)
            try:
                result = suggest(text, c.settings.get('assistant.endpoint'), c.settings.get('assistant.model'))
            except AssistanceError:
                raise HTTPException(422, 'KI-Dienst nicht erreichbar oder Antwort nicht gültig. Adresse und Modell prüfen.')
            c.repo.document_event(did, 'KI-Vorschläge angefordert', {'model': result['model']})
            return result

    @api.get('/api/transactions')
    def transactions(year: int | None = None, depot_id: int | None = None, isin: str | None = None):
        with rt().use() as c:
            return c.repo.transactions(year, depot_id, isin)

    @api.get('/api/transactions/{tid}')
    def transaction(tid: int):
        with rt().use() as c:
            t = require(c.repo.transaction(tid))
            links = c.db.query('SELECT document_id FROM document_links WHERE transaction_id=?', (tid,))
            ids = {r['document_id'] for r in links} | ({t['document_id']} if t['document_id'] else set())
            return {'transaction': t, 'revision': revision(t),
                    'documents': [clean_doc(c.repo.document(i)) for i in sorted(ids)]}

    def validate_tx(c, values, tid=None, duplicate_confirmed=False):
        values = {k: v for k, v in values.items() if k in TransactionIn.model_fields}
        values['source_type'] = 'manuell' if tid is None else 'korrektur'
        tx = TransactionIn(**values)
        if tx.trade_date > date.today() or tx.depot_id not in {d['id'] for d in c.repo.depots(active_only=True)}:
            raise ValueError('Datum oder Depot ist ungültig.')
        if tx.isin and not isin_checksum_ok(tx.isin):
            raise ValueError('ISIN-Prüfziffer stimmt nicht.')
        dup = c.repo.find_duplicates(tx)
        if any(d['id'] != tid for d in dup['exact']):
            raise HTTPException(409, 'Identische Buchung bereits vorhanden.')
        return tx

    @api.post('/api/transactions')
    def add_transaction(body: Edit):
        with rt().use() as c:
            tx = validate_tx(c, body.values)
            return {'id': c.repo.add_transaction(tx)}

    @api.patch('/api/transactions/{tid}')
    def edit_transaction(tid: int, body: Edit):
        with rt().use() as c:
            old = require(c.repo.transaction(tid))
            check_revision(old, body.revision)
            if not body.reason.strip():
                raise ValueError('Änderung bitte begründen.')
            allowed = set(TransactionIn.model_fields) - {'source_type', 'source_ref', 'document_id'}
            if set(body.values) - allowed:
                raise ValueError('Nicht bearbeitbare Buchungsfelder.')
            tx = validate_tx(c, {**old, **body.values}, tid)
            valid = tx.model_dump(mode='json')
            c.repo.update_transaction(tid, {k: valid[k] for k in body.values}, body.reason)
            return {'ok': True}

    @api.delete('/api/transactions/{tid}')
    def delete_transaction(tid: int, body: Edit):
        with rt().use() as c:
            check_revision(require(c.repo.transaction(tid)), body.revision)
            c.repo.delete_transaction(tid, body.reason)
            return {'ok': True}

    @api.get('/api/securities')
    def securities(q: str = ''):
        with rt().use() as c:
            return [{**s, 'review_reasons': review_reasons(s)} for s in c.repo.securities(q or None)]

    @api.get('/api/securities/{isin}')
    def security(isin: str):
        with rt().use() as c:
            s = require(c.repo.security_by_isin(isin), 'Wertpapier')
            ids = {t['document_id'] for t in c.repo.transactions(isin=isin) if t.get('document_id')}
            # Also find evidence from imported files which have not become bookings.
            ids.update(d['id'] for d in c.repo.documents(search=isin))
            return {'security': s, 'revision': revision(s), 'review_reasons': review_reasons(s),
                    'documents': [clean_doc(c.repo.document(i)) for i in sorted(ids)]}

    def save_security(c, body, isin=None):
        if isin:
            check_revision(require(c.repo.security_by_isin(isin)), body.revision)
        return {'isin': save_security_review(c.repo, body.values, existing_isin=isin,
                       review=body.review, price_symbol=body.price_symbol)}

    @api.post('/api/securities')
    def create_security(body: SecurityReview):
        with rt().use() as c:
            return save_security(c, body)

    @api.patch('/api/securities/{isin}')
    def update_security(isin: str, body: SecurityReview):
        with rt().use() as c:
            return save_security(c, body, isin)

    @api.get('/api/funds')
    def funds():
        with rt().use() as c:
            return c.repo.fund_reports()

    @api.post('/api/funds')
    def create_fund(body: FundReportIn):
        if not isin_checksum_ok(body.isin):
            raise ValueError('ISIN-Prüfziffer stimmt nicht.')
        with rt().use() as c:
            return c.repo.add_fund_report(body)

    @api.patch('/api/funds/{rid}')
    def update_fund(rid: int, body: Edit):
        with rt().use() as c:
            old = require(c.db.one('SELECT * FROM fund_reports WHERE id=?', (rid,)))
            allowed = set(FundReportIn.model_fields) | {'review_status'}
            if set(body.values) - allowed:
                raise ValueError('Unzulässiges Meldungsfeld.')
            FundReportIn(**{**old, **body.values})
            if 'review_status' in body.values and body.values['review_status'] not in {'ungeprueft', 'geprueft', 'verworfen'}:
                raise ValueError('Ungültiger Prüfstatus.')
            c.repo.correct_fund_report(rid, body.values, body.reason)
            return {'ok': True}

    @api.get('/api/conflicts')
    def conflicts():
        with rt().use() as c:
            return c.repo.conflicts('offen')

    @api.post('/api/conflicts/fund')
    def resolve_fund(body: Decision):
        with rt().use() as c:
            require(c.db.one("SELECT id FROM conflicts WHERE entity='fund_report' AND status='offen' "
                             "AND existing_ref LIKE ? AND new_ref LIKE ?", (
                             f'fund_reports:{body.existing_id} %', f'fund_reports:{body.new_id} %')), 'Offener Konflikt')
            c.repo.resolve_fund_report_conflict(body.existing_id, body.new_id, body.decision, body.note)
            return {'ok': True}

    @api.post('/api/conflicts/{cid}/nmf')
    def resolve_nmf(cid: int, body: Edit):
        with rt().use() as c:
            c.repo.resolve_nmf_conflict(cid, bool(body.values.get('take_new')), body.reason)
            return {'ok': True}

    @api.get('/api/nmf-prices')
    def nmf_prices(year: int):
        with rt().use() as c:
            return c.repo.nmf_prices(year)

    @api.post('/api/nmf-prices')
    def nmf_price(body: Nmf):
        if not isin_checksum_ok(body.isin):
            raise ValueError('ISIN-Prüfziffer stimmt nicht.')
        with rt().use() as c:
            return c.repo.upsert_nmf_price(**body.model_dump())

    @api.post('/api/brokers')
    def broker(body: Broker):
        with rt().use() as c:
            return {'id': c.repo.add_broker(**body.model_dump())}

    @api.post('/api/depots')
    def depot(body: Depot):
        with rt().use() as c:
            require(c.repo.broker(body.broker_id), 'Broker')
            fields = body.model_dump(exclude={'active'})
            return {'id': c.repo.add_depot(**fields)}

    @api.patch('/api/depots/{did}')
    def update_depot(did: int, body: Depot):
        with rt().use() as c:
            require(c.repo.depot(did), 'Depot')
            require(c.repo.broker(body.broker_id), 'Broker')
            c.repo.update_depot(did, **body.model_dump(exclude={'broker_id'}))
            return {'ok': True}

    @api.get('/api/depots/{did}/tax/{year}')
    def depot_tax(did: int, year: int):
        with rt().use() as c:
            require(c.repo.depot(did), 'Depot')
            return c.repo.depot_tax_settings(did, year)

    @api.put('/api/depots/{did}/tax/{year}')
    def update_depot_tax(did: int, year: int, body: DepotTax):
        with rt().use() as c:
            require(c.repo.depot(did), 'Depot')
            c.repo.set_depot_tax_settings(did, year, **body.model_dump())
            return {'ok': True}

    @api.get('/api/tax/{year}')
    def tax(year: int):
        with rt().use() as c:
            return jsonable_encoder(compute(c.repo, year, load_rules()))

    @api.get('/api/exports')
    def exports(year: int):
        with rt().use() as c:
            return c.repo.exports(year)

    @api.post('/api/exports/{year}/{kind}')
    def export(year: int, kind: str):
        from kest_tool.export.excel import export_excel
        from kest_tool.export.reports import export_csv, export_e1kv_helper, export_pdf_report
        funcs = {'excel': export_excel, 'csv': export_csv, 'pdf': export_pdf_report, 'e1kv': export_e1kv_helper}
        if kind not in funcs:
            raise HTTPException(404, 'Exportart unbekannt.')
        with rt().use() as c:
            funcs[kind](c.repo, c.store, compute(c.repo, year, load_rules()))
            return c.repo.exports(year)

    @api.get('/api/exports/{eid}/download')
    def download_export(eid: int):
        with rt().use() as c:
            e = require(c.db.one('SELECT * FROM exports WHERE id=?', (eid,)), 'Export')
            p = c.store.absolute(e['stored_path'])
            if not p.is_file():
                raise HTTPException(404, 'Exportdatei fehlt.')
            return FileResponse(p, filename=p.name)

    @api.get('/api/settings')
    def settings():
        with rt().use() as c:
            # Config forbids secrets; API keys themselves are never returned.
            import os
            return {'pdf': c.settings.get('pdf'), 'fx': c.settings.get('fx'),
                    'assistant': c.settings.get('assistant'), 'prices': c.settings.get('prices'),
                    'eodhd_configured': bool(os.environ.get('EODHD_API_KEY')),
                    'tax_years': c.settings.tax_years}

    @api.put('/api/settings')
    def update_settings(body: Edit):
        allowed = {'pdf', 'fx', 'assistant', 'prices', 'tax_years', 'default_tax_year'}
        if set(body.values) - allowed:
            raise ValueError('Diese Einstellungen können hier nicht geändert werden.')
        assistant = body.values.get('assistant')
        for key in ('pdf', 'fx', 'assistant', 'prices'):
            if key in body.values and not isinstance(body.values[key], dict):
                raise ValueError('Ungültige Einstellungen für ' + key)
        for section, key in [('pdf', 'ocr_enabled'), ('fx', 'auto_fetch'), ('assistant', 'enabled')]:
            if key in body.values.get(section, {}) and not isinstance(body.values[section][key], bool):
                raise ValueError('Ja/Nein-Wert erforderlich: ' + key)
        if 'tax_years' in body.values:
            years = body.values['tax_years']
            if not isinstance(years, list) or not years or any(type(y) is not int or not 2000 <= y <= 2100 for y in years):
                raise ValueError('Ungültige Steuerjahre.')
        if assistant:
            from kest_tool.importers.assisted import endpoint_url
            endpoint_url(assistant.get('endpoint', ''))
            if not isinstance(assistant.get('model'), str) or not assistant['model'].strip():
                raise ValueError('Modellname fehlt.')
        with rt().use() as c:
            c.settings.save_local(body.values)
            from kest_tool.config import load_settings
            c.settings = load_settings()
            c.repo.audit('settings', 'api', 'Einstellungen gespeichert')
            return {'ok': True}

    @api.put('/api/settings/eodhd')
    def api_key(body: Edit):
        from kest_tool.config import save_env_var
        with rt().use() as c:
            save_env_var('EODHD_API_KEY', str(body.values.get('key', '')))
            return {'ok': True}

    @api.post('/api/fx/{year}')
    def fx(year: int):
        from kest_tool.fx import FxService, fill_missing_fx
        with rt().use() as c:
            return jsonable_encoder(fill_missing_fx(c.repo, FxService(c.store.base), year,
                                                   allow_download=bool(c.settings.get('fx.auto_fetch'))))

    @api.post('/api/prices/{year}')
    def prices(year: int):
        from kest_tool.prices import PriceService, fill_nmf_prices, fill_year_end_prices
        with rt().use() as c:
            svc = PriceService(c.repo)
            return jsonable_encoder(fill_nmf_prices(c.repo, svc, year) + fill_year_end_prices(c.repo, svc, year))

    @api.post('/api/reference-import/{kind}')
    def reference_import(kind: str, file: UploadFile = File(...), isin: str | None = Form(None),
                         currency: str = Form('EUR'), redemption: bool = Form(False)):
        try:
            data = file.file.read(50 * 1024 * 1024 + 1)
            if len(data) > 50 * 1024 * 1024:
                raise HTTPException(413, 'Datei größer als 50 MB.')
            with rt().use() as c:
                if kind == 'fx':
                    from kest_tool.fx import FxService
                    rates = FxService(c.store.base).import_bytes(data)
                    return {'message': f'EZB-Datei eingelesen; letzter Tag: {rates.last_date}'}
                if kind == 'prices':
                    from kest_tool.prices import PriceService, import_price_csv
                    n = import_price_csv(c.repo, PriceService(c.repo), data, file.filename or 'preise.csv',
                                         isin=isin, currency=currency, redemption=redemption)
                    return {'message': f'{n} Kurse importiert.'}
                raise HTTPException(404, 'Referenzimport unbekannt.')
        finally:
            file.file.close()

    @api.get('/api/audit')
    def audit():
        with rt().use() as c:
            return {'audit': c.repo.audit_entries(500), 'imports': c.repo.import_runs()}

    @api.post('/api/backup')
    def backup():
        from kest_tool.backup import create_backup
        with rt().use() as c:
            p = create_backup(c.db, c.store)
            return FileResponse(p, filename=p.name)

    @api.post('/api/backup/restore')
    def restore(file: UploadFile = File(...), confirmed: bool = Form(False)):
        import tempfile
        import zipfile
        from kest_tool.backup import create_backup, restore_backup, verify_backup
        from kest_tool.context import create_context, shutdown_logging
        from kest_tool.config import load_settings
        if not confirmed:
            raise ValueError('Wiederherstellung und Sicherung des bisherigen Datenstands ausdrücklich bestätigen.')
        try:
            with rt().use() as c:
                data = file.file.read(200 * 1024 * 1024 + 1)
                if len(data) > 200 * 1024 * 1024:
                    raise HTTPException(413, 'Sicherung größer als 200 MB.')
                with tempfile.NamedTemporaryFile(suffix='.zip', dir=c.base_dir / 'backups', delete=False) as temp:
                    path = Path(temp.name)
                    temp.write(data)
                try:
                    with zipfile.ZipFile(path) as archive:
                        infos = archive.infolist()
                        if len(infos) > 20000 or sum(i.file_size for i in infos) > 1024 * 1024 * 1024:
                            raise ValueError('Entpackte Sicherung überschreitet die Wiederherstellungsgrenze.')
                    verify_backup(path)
                    create_backup(c.db, c.store)
                    base = c.base_dir
                    c.close()
                    shutdown_logging()
                    try:
                        result = restore_backup(path, base, move_existing=True)
                    finally:
                        rt().context = create_context(load_settings())
                    return {'ok': True, 'files': result['files'], 'created_at': result['created_at']}
                finally:
                    path.unlink(missing_ok=True)
        finally:
            file.file.close()

    @api.get('/{path:path}', include_in_schema=False)
    def spa(path: str):
        if path.startswith('api/'):
            raise HTTPException(404, 'API-Endpunkt nicht gefunden.')
        candidate = (dist / path).resolve()
        if dist.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        if path.startswith('assets/') or Path(path).suffix:
            raise HTTPException(404, 'Datei nicht gefunden.')
        if not dist.joinpath('index.html').is_file():
            return JSONResponse({'detail': 'Frontend noch nicht gebaut: cd frontend && npm ci && npm run build'}, status_code=503)
        return FileResponse(dist / 'index.html', headers={'Cache-Control': 'no-cache'})

    return api


def application(runtime=None, dist=DIST):
    inner = create_app(runtime, dist)
    # Explicit mount preserves the deployed /steuer/ prefix end to end. Lifespan
    # belongs to the inner app and must be run by the outer server as well.
    @asynccontextmanager
    async def lifespan(outer):
        async with inner.router.lifespan_context(inner):
            yield
    outer = FastAPI(lifespan=lifespan, docs_url=None, openapi_url=None)
    @outer.get('/', include_in_schema=False)
    def root():
        return RedirectResponse('/steuer/')
    outer.mount('/steuer', inner)
    return outer


app = application()
