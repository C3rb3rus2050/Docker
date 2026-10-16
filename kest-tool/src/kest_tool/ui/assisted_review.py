"""Explicitly requested, source-backed proposals beside the original document."""
from datetime import date

import streamlit as st

from . import common as C

WIDGETS = {'trade_date': 'date', 'value_date': 'valuta', 'security_name': 'name',
           'withholding_tax': 'wht', 'fx_rate': 'fx'}


def assistance(repo, doc, key):
    settings = C.ctx().settings
    with st.expander('Unbekanntes Layout mit lokaler KI prüfen'):
        st.caption('Vorschläge werden nicht automatisch gebucht. Textstellen belegen nur das Vorkommen; '
                   'Bedeutung, Brutto/Netto und Zuordnung müssen am Original geprüft werden.')
        if not settings.get('assistant.enabled', False):
            st.info('Unter Einstellungen → Dokumentenerkennung die lokale KI aktivieren und Ollama einrichten.')
            return
        consent = st.checkbox('Belegtext an meinen eingerichteten Ollama-Dienst senden', key=f'{key}_ai_consent',
            help='Der Dienst erhält Text aus diesem Beleg, möglicherweise einschließlich persönlicher Angaben. '
                 'Keine automatische Übermittlung an einen KI-Anbieter.')
        cache_key = f'{key}_ai_proposals'
        if st.button('KI-Vorschläge ermitteln', key=f'{key}_ai_run', disabled=not consent):
            from ..importers.assisted import suggest, AssistanceError
            from ..importers.pdf_importer import extract_text, _ocr_text, PdfError
            st.session_state.pop(cache_key, None)
            st.session_state.pop(f'{key}_ai_selected', None)
            try:
                with st.spinner('Lokale KI liest den Beleg …'):
                    data = repo.document_path(doc).read_bytes()
                    text, _ = extract_text(data)
                    if not text.strip():
                        text = _ocr_text(data)
                    result = suggest(text, settings.get('assistant.endpoint', 'http://ollama:11434'),
                                     settings.get('assistant.model', 'qwen2.5:7b'))
                st.session_state[cache_key] = result
            except (AssistanceError, PdfError, OSError):
                st.error('KI-Vorschläge konnten nicht erstellt werden. Ollama-Adresse, Modell und lesbaren Belegtext prüfen.')
        result = st.session_state.get(cache_key)
        if not result:
            return
        if result['truncated']:
            st.warning('Nur die ersten 24.000 Textzeichen wurden untersucht.')
        if result['rejected']:
            st.warning('Nicht belegte oder ungültige Vorschläge verworfen: ' + ', '.join(result['rejected']))
        fields = dict(result['fields'])
        if fields.get('currency', {}).get('value') not in (None, *settings.currencies):
            st.warning('Vorgeschlagene Währung ist nicht in den Einstellungen aktiviert; bitte dort ergänzen.')
            fields.pop('currency')
        if not fields:
            st.info('Keine belegbaren Einzelwerte erkannt. Bitte direkt am Original ergänzen.')
            return
        from ..importers.pdf_importer import FIELD_LABELS
        st.dataframe([{'Feld': FIELD_LABELS.get(n, n), 'Vorschlag': str(f['value']), 'Textstelle': f['source']}
                      for n, f in fields.items()], hide_index=True, width='stretch')
        selected = st.multiselect('Verglichene Felder ins Formular übernehmen', list(fields),
                                  format_func=lambda n: FIELD_LABELS.get(n, n), key=f'{key}_ai_selected')
        if st.button('Ausgewählte Vorschläge übernehmen', key=f'{key}_ai_apply', disabled=not selected):
            # Called before review widgets are constructed, so changing their draft state is safe.
            for name in selected:
                value = fields[name]['value']
                if name in {'trade_date', 'value_date'}:
                    value = date.fromisoformat(value)
                st.session_state[f'{key}_{WIDGETS.get(name, name)}'] = value
            st.session_state[f'{key}_confirmed'] = False
            repo.document_event(doc['id'], 'KI-Vorschläge ins Prüfformular übernommen',
                                {'model': result['model'], 'fields': {n: fields[n] for n in selected}})
            st.success('Vorschläge im Formular eingetragen. Vor dem Speichern alle Werte mit dem Original abgleichen.')
