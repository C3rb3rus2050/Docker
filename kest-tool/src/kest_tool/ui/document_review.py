"""Original and editable booking in the same card; no document selector or page hop."""
from __future__ import annotations

import streamlit as st

from ..models import DOC_TYPES
from . import common as C

OPEN = {'neu', 'pruefen', 'teilweise', 'fehlgeschlagen'}


def document_cards(repo, docs: list[dict], *, key: str, messages: dict | None = None) -> None:
    notice = st.session_state.pop('document_review_saved', None)
    if notice:
        st.success(notice)
    if not docs:
        st.info('Keine offenen Belege in dieser Ansicht.')
        return
    from .review_pager import review_item
    doc = review_item(docs, key=key, identity='id', label='Beleg')
    _card(repo, doc, f'{key}_{doc["id"]}', (messages or {}).get(doc['id']))


def _card(repo, doc: dict, key: str, message: str | None) -> None:
    from ..processing import extraction_for
    from .pages_import import pdf_review_form
    from .record_tables import record_grid
    did = doc['id']
    with st.container(border=True, key=f'document_card_{key}'):
        st.markdown(f"### {doc['original_filename']}")
        if message and doc['status'] in OPEN:
            st.caption(message)
        left, right = st.columns([1, 1.15], gap='large')
        with left:
            try:
                data = repo.document_path(doc).read_bytes()
                if doc['file_type'] == 'pdf':
                    st.pdf(data, height=500, key=f'{key}_pdf')
                else:
                    from ..importers.automatic import automatic_tables
                    for frame in automatic_tables(data, doc['original_filename']):
                        st.dataframe(frame, hide_index=True, width='stretch')
                st.download_button('Original herunterladen', data, file_name=doc['original_filename'], key=f'{key}_download')
            except (ValueError, OSError) as exc:
                st.warning(f'Originalvorschau nicht verfügbar: {exc}')
        with right:
            if st.button('Beleg erneut bestimmen', key=f'{key}_retry',
                         help='Original neu lesen, einschließlich lokaler OCR. Bestehende Buchungen nicht überschreiben.'):
                from ..processing import process_documents, process_tables
                options = {**C.document_analysis_options(), 'ocr_enabled': True}
                with st.spinner('Original wird erneut gelesen …'):
                    results = process_documents(repo, [did], reextract=True, **options) if doc['file_type'] == 'pdf' else \
                        process_tables(repo, [(doc, doc['doc_type'] == 'OeKB-Fondsmeldung')], **options)
                C.invalidate_results()
                st.session_state['document_review_saved'] = results[0].message if results else 'Beleg erneut geprüft.'
                st.rerun()
            if doc['doc_type'] == 'OeKB-Fondsmeldung':
                from .pages_data import _fund_document_review
                _fund_document_review(repo, doc, key)
            elif doc['file_type'] == 'pdf':
                try:
                    extraction = extraction_for(repo, doc)
                except (ValueError, OSError) as exc:
                    st.warning(f'Automatische Erkennung nicht möglich: {exc}. Werte direkt aus dem Original ergänzen.')
                    extraction = {'fields': {}, 'doc_type': 'Unbekannt'}
                linked = repo.transactions_for_document(did)
                if len(linked) > 1:
                    st.caption('Mehrere Buchungen zu diesem Beleg – Werte direkt in der Tabelle bearbeiten.')
                    record_grid(repo, linked, 'transaction', f'{key}_linked')
                else:
                    from .assisted_review import assistance
                    assistance(repo, doc, key)
                    pdf_review_form(doc, extraction, None, key=key, transaction=linked[0] if linked else None)
            else:
                st.info(doc.get('notes') or 'Die Tabellenwerte stehen links; die automatische Prüfung kann hier erneut gestartet werden.')
            with st.expander('Dokumentart korrigieren / ohne Buchung ablegen'):
                with st.form(f'{key}_classification'):
                    dtype = st.selectbox('Dokumentart', DOC_TYPES,
                        index=DOC_TYPES.index(doc['doc_type']) if doc['doc_type'] in DOC_TYPES else DOC_TYPES.index('Unbekannt'),
                        key=f'{key}_doc_type')
                    note = st.text_input('Begründung', key=f'{key}_class_note')
                    no_booking = st.checkbox('Geprüft: Dieser Beleg benötigt keine zusätzliche Buchung', key=f'{key}_no_booking')
                    if st.form_submit_button('Dokumentzuordnung speichern'):
                        if not note.strip():
                            st.error('Bitte die Einordnung kurz begründen.')
                        else:
                            repo.update_document(did, doc_type=dtype, notes=note,
                                                 **({'status': 'verarbeitet'} if no_booking else {}))
                            repo.document_event(did, 'Dokumentart manuell geprüft', {'typ': dtype, 'notiz': note})
                            C.invalidate_results()
                            st.rerun()
