"""Selectable, validated grids and browser-side original document previews."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date

import pandas as pd
import streamlit as st

from ..models import FundReportIn, TransactionIn
from . import common as C

TX_FIELDS = {'execution_order': 'Reihenfolge am Tag', 'trade_date': 'Datum', 'tx_type': 'Art', 'security_name': 'Wertpapier', 'isin': 'ISIN',
             'quantity': 'Stück', 'price': 'Kurs', 'amount': 'Brutto', 'currency': 'Währung', 'fees': 'Gebühren',
             'withholding_tax': 'Quellensteuer', 'withholding_country': 'Quellenstaat',
             'kest_at_eur': 'Österr. KESt EUR', 'fx_rate': 'Kurs je EUR', 'review_status': 'Prüfstatus', 'notes': 'Notiz'}
FUND_FIELDS = {'report_date': 'Meldedatum', 'isin': 'ISIN', 'fund_name': 'Fonds', 'report_type': 'Art',
               'age_per_unit': 'AgE / Anteil', 'taxable_distribution_per_unit': 'Steuerpfl. Ausschüttung / Anteil',
               'ak_correction_per_unit': 'AK-Korrektur / Anteil', 'creditable_tax_per_unit': 'Anrechenbare Steuer / Anteil',
               'distribution_per_unit': 'Ausschüttung / Anteil', 'currency': 'Währung', 'fx_rate': 'Kurs je EUR',
               'review_status': 'Prüfstatus', 'notes': 'Notiz'}
NUMBERS = {'quantity', 'price', 'amount', 'fees', 'withholding_tax', 'kest_at_eur', 'fx_rate',
           'age_per_unit', 'taxable_distribution_per_unit', 'ak_correction_per_unit',
           'creditable_tax_per_unit', 'distribution_per_unit'}
REVIEW_LABELS = {'ungeprueft': 'Ungeprüft', 'geprueft': 'Geprüft', 'pruefen': 'Zu prüfen', 'verworfen': 'Verworfen'}


def filter_records(rows: list[dict], query: str, review: str, sort: str, kind: str) -> list[dict]:
    words = query.casefold().split()
    visible = [r for r in rows if all(word in ' '.join(str(r.get(k) or '') for k in
        ('isin', 'security_name', 'fund_name', 'notes', 'depot_name', 'original_filename')).casefold() for word in words)]
    if review == 'Offen':
        visible = [r for r in visible if r.get('review_status') in ('pruefen', 'ungeprueft')]
    elif review != 'Alle':
        visible = [r for r in visible if REVIEW_LABELS.get(r.get('review_status')) == review]
    date_key = 'trade_date' if kind == 'transaction' else 'report_date'
    if sort == 'Wertpapier A–Z':
        return sorted(visible, key=lambda r: (str(r.get('security_name') or r.get('fund_name') or '').casefold(), r['id']))
    return sorted(visible, key=lambda r: (str(r.get(date_key) or ''), r['id']), reverse=sort != 'Älteste zuerst')


def _page_rows(rows: list[dict], key: str) -> list[dict]:
    if len(rows) <= 50:
        return rows
    pages = (len(rows) + 49) // 50
    page_key = f'{key}_page_' + hashlib.sha256(json.dumps([r['id'] for r in rows]).encode()).hexdigest()[:10]
    page = min(st.session_state.get(page_key, 1), pages)
    previous, counter, following = st.columns([1, 3, 1])
    if previous.button('← Zurück', key=f'{key}_prev', disabled=page == 1):
        st.session_state[page_key] = page - 1
        st.rerun()
    counter.caption(f'Seite {page} von {pages} · 50 Einträge pro Seite')
    if following.button('Weiter →', key=f'{key}_next', disabled=page == pages):
        st.session_state[page_key] = page + 1
        st.rerun()
    return rows[(page - 1) * 50:page * 50]


def grid_changes(rows: list[dict], edited: list[dict], kind: str) -> list[tuple[int, dict]]:
    """Validate the entire edit set before changing anything; preserve zero vs empty."""
    fields = TX_FIELDS if kind == 'transaction' else FUND_FIELDS
    originals = {r['id']: r for r in rows}
    output = []
    for record in edited:
        rid = int(record['ID'])
        if rid not in originals:
            raise ValueError('Unbekannte Tabellenzeile')
        old, changes = originals[rid], {}
        for key in fields:
            value = record.get(key)
            if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
                value = None
            if isinstance(value, date):
                value = value.isoformat()
            if key in NUMBERS and value is not None and not math.isfinite(float(value)):
                raise ValueError('Beträge und Kurse müssen endliche Zahlen sein')
            if kind == 'transaction' and key in NUMBERS and value is not None and float(value) < 0:
                raise ValueError('Buchungsbeträge und Stückzahlen werden ohne negatives Vorzeichen erfasst')
            if key == 'currency' and not value:
                raise ValueError('Währung darf nicht leer sein')
            if value != old.get(key):
                changes[key] = value
        if not changes:
            continue
        if kind == 'transaction':
            valid = TransactionIn(**{**old, **changes}).model_dump(mode='json')
            changes = {k: valid[k] for k in changes}
        else:
            if not old.get('active'):
                raise ValueError('Inaktive Fondsmeldungen bleiben als Historie erhalten')
            if any(k in changes for k in ('isin', 'report_date', 'report_type')):
                raise ValueError('Für eine andere ISIN oder Meldung eine neue Fondsmeldung anlegen')
            if changes.get('review_status', old['review_status']) not in ('ungeprueft', 'geprueft', 'verworfen'):
                raise ValueError('Ungültiger Prüfstatus')
            valid = FundReportIn(**{**old, **changes}).model_dump(mode='json')
            changes = {k: valid[k] if k in valid else changes[k] for k in changes}
        output.append((rid, changes))
    return output


def document_preview(repo, document_id: int, key: str) -> None:
    doc = repo.document(document_id)
    if not doc:
        st.info('Zugehöriges Dokument nicht mehr vorhanden.')
        return
    path = repo.document_path(doc)
    st.markdown(f"**Beleg: {doc['original_filename']}**")
    try:
        data = path.read_bytes()
    except OSError:
        st.error('Originaldatei ist in der Ablage nicht erreichbar.')
        return
    st.download_button('Original herunterladen', data, file_name=doc['original_filename'], key=f'{key}_download')
    if st.button('Zugehöriges Dokument öffnen', key=f'{key}_open'):
        st.session_state[f'{key}_visible'] = True
    if st.session_state.get(f'{key}_visible'):
        if doc['file_type'] == 'pdf':
            # Native viewer runs in the user's browser, including Docker deployments.
            st.pdf(data, height=650, key=f'{key}_pdf')
        elif doc['file_type'] in ('csv', 'txt', 'xlsx'):
            from ..importers.automatic import automatic_tables
            try:
                for index, frame in enumerate(automatic_tables(data, doc['original_filename'])):
                    st.caption(f'Tabellenabschnitt {index + 1}')
                    st.dataframe(frame, hide_index=True, width='stretch')
            except ValueError:
                from ..importers.csv_importer import _decode
                if doc['file_type'] != 'xlsx':
                    st.code(_decode(data)[0], language=None)
                else:
                    st.info('Vorschau nicht verfügbar; Original herunterladen.')


def record_grid(repo, rows: list[dict], kind: str, key: str) -> list[int]:
    if not rows:
        st.info('Keine Einträge im Filter.')
        return []
    total = len(rows)
    left, middle, right = st.columns([3, 2, 2])
    query = left.text_input('Liste durchsuchen', placeholder='Name, ISIN, Depot oder Notiz', key=f'{key}_search')
    review = middle.selectbox('Prüfstatus', ['Alle', 'Offen', 'Zu prüfen', 'Ungeprüft', 'Geprüft'] +
                              (['Verworfen'] if kind == 'fund' else []), key=f'{key}_status')
    sort = right.selectbox('Sortieren', ['Neueste zuerst', 'Älteste zuerst', 'Wertpapier A–Z'], key=f'{key}_sort')
    rows = filter_records(rows, query, review, sort, kind)
    st.caption(f'{len(rows)} von {total} Einträgen · Offen = ungeprüft oder zu prüfen')
    if not rows:
        st.info('Kein Treffer. Suche oder Prüfstatus oben anpassen.')
        return []
    rows = _page_rows(rows, key)
    fields = TX_FIELDS if kind == 'transaction' else FUND_FIELDS
    revision = hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()[:12]
    table_key = f'{key}_{revision}'
    records = [{'Auswahl': False, 'ID': r['id'], **{f: r.get(f) for f in fields},
                'Beleg': (repo.document(r['document_id']) or {}).get('original_filename', '')
                if r.get('document_id') else '',
                **({'Aktiv': bool(r['active'])} if kind == 'fund' else {})} for r in rows]
    if kind == 'transaction':
        for record, original in zip(records, rows):
            record.update({'Depot': original.get('depot_name', ''), 'Broker': original.get('broker_name', ''),
                           'Brutto EUR': original.get('amount_eur'), 'Kursquelle': original.get('fx_source', '')})
    frame = pd.DataFrame(records)
    for field in NUMBERS & set(fields):
        frame[field] = pd.to_numeric(frame[field], errors='coerce').astype('float64')
    for field in ('trade_date', 'report_date'):
        if field in frame:
            frame[field] = pd.to_datetime(frame[field]).dt.date
    config = {field: st.column_config.NumberColumn(label, format='%.2f' if field in
              ('amount', 'fees', 'withholding_tax', 'kest_at_eur') else '%.6f') if field in NUMBERS
              else st.column_config.TextColumn(label) for field, label in fields.items()}
    config['Auswahl'] = st.column_config.CheckboxColumn('✓', width='small', pinned=True)
    config['ID'] = st.column_config.NumberColumn('ID', width='small', format='%d')
    for field in ('trade_date', 'report_date'):
        if field in fields:
            config[field] = st.column_config.DateColumn(fields[field], format='DD.MM.YYYY', required=True)
    statuses = ['ungeprueft', 'geprueft', 'pruefen'] if kind == 'transaction' else ['ungeprueft', 'geprueft', 'verworfen']
    config['review_status'] = st.column_config.SelectboxColumn('Prüfstatus', options=statuses, required=True,
                                                              format_func=lambda v: REVIEW_LABELS.get(v, v))
    if kind == 'transaction':
        from ..models import TxType
        config['execution_order'] = st.column_config.NumberColumn('Reihenfolge am Tag', min_value=1, step=1, help='Bei taggleichen Bestandsänderungen die tatsächliche Ausführungsreihenfolge je Depot und ISIN eintragen.')
        config['tx_type'] = st.column_config.SelectboxColumn('Art', options=[t.value for t in TxType], required=True)
    st.caption('Zellen direkt bearbeiten. Änderungen werden erst beim Speichern übernommen. '
               'Über „Auswahl“ Belege öffnen; gespeichert werden alle geänderten Zeilen.')
    disabled = ['ID', 'Beleg'] + (['isin', 'report_date', 'report_type', 'Aktiv'] if kind == 'fund' else
                                 ['Depot', 'Broker', 'Brutto EUR', 'Kursquelle'])
    more = st.checkbox('Weitere Spalten anzeigen', key=f'{key}_more')
    core = ['Auswahl'] + (['trade_date', 'tx_type', 'security_name', 'amount', 'currency', 'review_status']
                         if kind == 'transaction' else ['report_date', 'fund_name', 'age_per_unit',
                                                        'ak_correction_per_unit', 'currency', 'review_status'])
    edited = st.data_editor(frame, key=table_key, hide_index=True, width='stretch', height=min(460, 40 + len(rows) * 35),
                            column_config=config, disabled=disabled, num_rows='fixed',
                            column_order=list(frame.columns) if more else core)
    dirty = not frame.drop(columns='Auswahl').equals(edited.drop(columns='Auswahl'))
    if dirty:
        reason = st.text_input('Begründung für Tabellenänderungen', key=f'{key}_reason')
        if st.button('Tabellenänderungen speichern', key=f'{key}_save', type='primary'):
            try:
                changes = grid_changes(rows, edited.to_dict('records'), kind)
                if changes and not reason.strip():
                    raise ValueError('Bitte Änderungen kurz begründen')
                for rid, values in changes:
                    if kind == 'transaction':
                        repo.update_transaction(rid, values, reason)
                    else:
                        repo.correct_fund_report(rid, values, reason)
                if changes:
                    C.invalidate_results()
                    st.rerun()
                st.info('Keine geänderten Werte.')
            except ValueError as exc:
                st.error(str(exc))
    selected = [int(r['ID']) for r in edited.to_dict('records') if r['Auswahl']]
    st.caption(f'{len(selected)} Einträge ausgewählt · {len(rows)} Einträge im Filter')
    if len(selected) == 1:
        row = next(r for r in rows if r['id'] == selected[0])
        st.info(f"Auswahl #{row['id']} · {row.get('isin') or 'ohne ISIN'} · "
                f"{row.get('security_name') or row.get('fund_name') or ''}")
    documents = set()
    for row in rows:
        if row['id'] in selected:
            if row.get('document_id'):
                documents.add(row['document_id'])
            if kind == 'transaction':
                documents.update(d['document_id'] for d in repo.db.query(
                    'SELECT document_id FROM document_links WHERE transaction_id=?', (row['id'],)))
    for did in sorted(documents):
        document_preview(repo, did, f'{key}_doc_{did}')
    if selected and not documents:
        st.info('Für diese Auswahl ist kein Originaldokument verknüpft.')
    return selected


def document_grid(repo, docs: list[dict], key: str) -> list[int]:
    from ..models import DOC_SOURCES, DOC_STATUS, DOC_TYPES
    if not docs:
        st.info('Keine Dokumente im Filter.')
        return []
    docs = _page_rows(docs, key)
    rows = [{'Auswahl': False, 'ID': d['id'], 'Datei': d['original_filename'],
             **{k: d.get(k) for k in ('tax_year', 'source', 'doc_type', 'status', 'notes')}} for d in docs]
    revision = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:12]
    edited = st.data_editor(pd.DataFrame(rows), key=f'{key}_{revision}', hide_index=True, width='stretch', height=min(460, 40 + len(rows) * 35),
        disabled=['ID', 'Datei'], num_rows='fixed', column_config={
            'Auswahl': st.column_config.CheckboxColumn('✓', width='small', pinned=True),
            'tax_year': st.column_config.NumberColumn('Jahr', min_value=2000, max_value=2100, step=1),
            'source': st.column_config.SelectboxColumn('Quelle', options=DOC_SOURCES, required=True,
                        format_func=lambda v: {'TradeRepublic': 'Trade Republic', 'ScalableCapital': 'Scalable Capital',
                                               'Unclassified': 'Nicht erkannt', 'Other': 'Sonstige'}.get(v, v)),
            'doc_type': st.column_config.SelectboxColumn('Dokumentart', options=DOC_TYPES, required=True),
            'status': st.column_config.SelectboxColumn('Status', options=DOC_STATUS, required=True,
                        format_func=lambda v: {'neu': 'Neu', 'pruefen': 'Zu prüfen', 'verarbeitet': 'Erledigt',
                                               'teilweise': 'Teilweise', 'fehlgeschlagen': 'Nicht lesbar', 'ignoriert': 'Ignoriert'}.get(v, v)),
            'notes': st.column_config.TextColumn('Notiz')})
    st.caption('Metadaten direkt bearbeiten und speichern. „Auswahl“ öffnet die Dokumentprüfung darunter.')
    if st.button('Dokumentänderungen speichern', key=f'{key}_save'):
        try:
            updates = []
            originals = {d['id']: d for d in docs}
            for row in edited.to_dict('records'):
                old = originals[int(row['ID'])]
                changes = {k: (None if pd.isna(v) else v) for k, v in row.items()
                           if k in ('tax_year', 'source', 'doc_type', 'status', 'notes')}
                if changes['tax_year'] is not None:
                    changes['tax_year'] = int(changes['tax_year'])
                    if not 2000 <= changes['tax_year'] <= 2100:
                        raise ValueError('Steuerjahr außerhalb des erlaubten Bereichs')
                if changes['source'] not in DOC_SOURCES or changes['doc_type'] not in DOC_TYPES or changes['status'] not in DOC_STATUS:
                    raise ValueError('Ungültige Dokumentzuordnung')
                changes = {k: v for k, v in changes.items() if old.get(k) != v}
                if changes:
                    updates.append((old['id'], changes))
            for did, changes in updates:
                repo.update_document(did, **changes)
            if updates:
                C.invalidate_results()
                st.rerun()
            st.info('Keine geänderten Werte.')
        except (ValueError, OSError) as exc:
            st.error(str(exc))
    return [int(r['ID']) for r in edited.to_dict('records') if r['Auswahl']]
