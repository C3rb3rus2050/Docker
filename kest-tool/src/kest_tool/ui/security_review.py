"""Security cards: evidence on the left, independent edit forms on the right."""
from __future__ import annotations

import streamlit as st
from pydantic import ValidationError

from ..models import SecurityType, TaxClass, TAX_CLASS_LABELS, FundStatus, FUND_SECURITY_TYPES
from ..security_review import review_reasons, save_security_review
from . import common as C

FUND_LABELS = {'kein_fonds': 'Kein Fonds', 'meldefonds': 'Meldefonds',
               'nichtmeldefonds': 'Nichtmeldefonds', 'unbekannt': 'Unbekannt'}
REVIEW = {'ungeprueft': 'Ungeprüft', 'pruefen': 'Zu prüfen', 'geprueft': 'Geprüft'}


def security_cards(repo, rows):
    if not rows:
        st.info('Keine Wertpapiere in dieser Ansicht.')
        return
    from .review_pager import review_item
    selected = review_item(rows, key='securities_cards', identity='isin', label='Wertpapier')
    for sec in [selected]:
        key = f'security_{sec["isin"]}'
        with st.container(border=True, key=f'work_card_{key}'):
            st.subheader(sec.get('name') or sec['isin'])
            st.caption(f'{sec["isin"]} · ' + ('Zu prüfen' if review_reasons(sec) else 'Geprüft'))
            left, right = st.columns([1, 1.15], gap='large')
            with left:
                _evidence(repo, sec, key)
            with right:
                security_form(repo, sec, key)


def _evidence(repo, sec, key):
    reasons = review_reasons(sec)
    if reasons:
        st.markdown('**Was noch fehlt**')
        st.caption(' · '.join(reasons))
    else:
        st.success('Stammdaten und Quellen geprüft.')
    st.markdown('**Vorhandene Quellen**')
    st.write('Steuerliche Einstufung: ' + (sec.get('tax_class_source') or 'Noch keine Quelle hinterlegt'))
    st.write('Meldefondsstatus: ' + (sec.get('fund_status_source') or 'Noch keine Quelle hinterlegt'))
    txs = repo.transactions(isin=sec['isin'])
    st.caption(f'{len(txs)} zugehörige Buchungen · alle Jahre')
    docs = []
    seen = set()
    for tx in txs:
        did = tx.get('document_id')
        if did and did not in seen:
            seen.add(did)
            doc = repo.document(did)
            if doc:
                docs.append(doc)
    pdfs = [d for d in docs if d['file_type'] == 'pdf']
    if pdfs:
        doc = pdfs[0]
        st.markdown('**Zugehöriger Originalbeleg**')
        st.caption(doc['original_filename'])
        try:
            st.pdf(repo.document_path(doc).read_bytes(), height=420, key=f'{key}_pdf')
        except (OSError, ValueError):
            st.warning('Originalbeleg konnte nicht angezeigt werden.')
    else:
        st.info('Kein PDF über die Buchungen zugeordnet. Quellenangaben mit Emittentenunterlagen oder OeKB prüfen.')
    st.caption('Ein Brokerbeleg belegt die Buchung; er bestätigt nicht automatisch die steuerliche Einstufung.')
    if docs:
        with st.expander(f'Zugehörige Dateien ({len(docs)})'):
            for doc in docs:
                try:
                    st.download_button(doc['original_filename'], repo.document_path(doc).read_bytes(),
                                       file_name=doc['original_filename'], key=f'{key}_download_{doc["id"]}')
                except (OSError, ValueError):
                    st.caption(doc['original_filename'] + ' – Datei nicht verfügbar')
    if txs:
        with st.expander('Zugehörige Buchungen'):
            C.df([{'Datum': t['trade_date'], 'Art': t['tx_type'], 'Depot': t['depot_name'],
                   'Stück': t['quantity'], 'Betrag': t['amount'], 'Währung': t['currency']} for t in txs])
    with st.expander('Änderungshistorie'):
        C.df(repo.db.query("SELECT * FROM audit_log WHERE entity='security' AND entity_id=? ORDER BY id DESC LIMIT 50",
                           (sec['isin'],)))


def security_form(repo, sec: dict, key: str):
    def val(name, default=''):
        return sec.get(name) or default

    with st.form(f'{key}_form'):
        isin = sec.get('isin')
        if not sec:
            isin = st.text_input('ISIN', key=f'{key}_isin')
        a, b = st.columns(2)
        name = a.text_input('Name', val('name'), key=f'{key}_name')
        types = [t.value for t in SecurityType]
        stype = b.selectbox('Wertpapierart', types, index=types.index(val('security_type', 'Sonstige')),
                            key=f'{key}_type')
        classes = [t.value for t in TaxClass]
        tc = st.selectbox('Einstufung', classes, index=classes.index(val('tax_class', 'ungeklaert')),
            format_func=lambda v: TAX_CLASS_LABELS[TaxClass(v)], key=f'{key}_tax_class')
        tc_src = st.text_input('Quelle der Einstufung', val('tax_class_source'),
                               placeholder='Emittentenunterlage, Datum / Fundstelle', key=f'{key}_tax_source')
        tc_ver = st.checkbox('Einstufung anhand der Quelle geprüft', bool(sec.get('tax_class_verified')),
                             key=f'{key}_tax_verified')
        with st.expander('Meldefondsstatus (für Fonds / ETFs)',
                         expanded=val('security_type') in {t.value for t in FUND_SECURITY_TYPES}
                         or val('tax_class') == 'investmentfonds'):
            statuses = list(FUND_LABELS)
            fs = st.selectbox('Meldefondsstatus', statuses, index=statuses.index(val('fund_status', 'kein_fonds')),
                               format_func=FUND_LABELS.get, key=f'{key}_fund_status')
            fs_src = st.text_input('Quelle Meldefondsstatus', val('fund_status_source'),
                                   placeholder='OeKB-Abfrage mit Datum', key=f'{key}_fund_source')
            fs_ver = st.checkbox('Meldefondsstatus anhand der Quelle geprüft', bool(sec.get('fund_status_verified')),
                                 key=f'{key}_fund_verified')
        with st.expander('Weitere Stammdaten und Notizen'):
            a, b = st.columns(2)
            ticker = a.text_input('Ticker', val('ticker'), key=f'{key}_ticker')
            wkn = b.text_input('WKN', val('wkn'), key=f'{key}_wkn')
            a, b = st.columns(2)
            country = a.text_input('Sitzstaat Emittent (ISO-2)', val('country'), max_chars=2, key=f'{key}_country')
            currency = b.text_input('Handelswährung (ISO-3)', val('currency'), max_chars=3, key=f'{key}_currency')
            symbol = st.text_input('Kurssymbol beim Kursdienst', val('price_symbol'), key=f'{key}_symbol')
            notes = st.text_area('Notizen', val('notes'), key=f'{key}_notes')
        review = st.selectbox('Prüfstatus', list(REVIEW), index=list(REVIEW).index(val('review_status', 'ungeprueft')),
                               format_func=REVIEW.get, key=f'{key}_review')
        st.caption('„Geprüft“ setzt vollständige Stammdaten und geprüfte Quellen voraus. Offene Angaben lassen sich als Entwurf speichern.')
        save = st.form_submit_button('Änderungen speichern' if sec else 'Wertpapier anlegen', type='primary',
                                     use_container_width=True)
    if save:
        try:
            identifier = save_security_review(repo, dict(isin=isin, name=name or None, ticker=ticker or None,
                wkn=wkn or None, country=country or None, currency=currency or None, security_type=stype,
                tax_class=tc, tax_class_source=tc_src or None, tax_class_verified=tc_ver,
                fund_status=fs, fund_status_source=fs_src or None, fund_status_verified=fs_ver, notes=notes or None),
                existing_isin=sec.get('isin'), review=review, price_symbol=symbol)
            C.invalidate_results()
            st.session_state['security_review_saved'] = f'{identifier}: Änderungen gespeichert.'
            st.rerun()
        except ValidationError as exc:
            C.form_error(exc)
        except ValueError as exc:
            st.error(str(exc))
