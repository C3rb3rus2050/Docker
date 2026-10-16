"""Validated, explicit manual completion of a document in its own review card."""
from __future__ import annotations

import json
from datetime import date

from .importers.pdf_importer import REQUIRED
from .models import TransactionIn, TxType, isin_checksum_ok


def save_review(repo, document_id: int, values: dict, *, confirmed: bool,
                transaction_id: int | None = None, reason: str = '',
                duplicate_confirmed: bool = False) -> int:
    if not confirmed:
        raise ValueError('Bitte den Abgleich mit dem Original bestätigen.')
    doc = repo.document(document_id)
    if not doc:
        raise ValueError('Dokument nicht mehr vorhanden.')
    linked = repo.transactions_for_document(document_id)
    if transaction_id is None and linked:
        raise ValueError('Es gibt bereits eine Buchung. Die Ansicht aktualisieren und diese Buchung bearbeiten.')
    if transaction_id is not None:
        if transaction_id not in {t['id'] for t in linked}:
            raise ValueError('Die Buchung gehört nicht zu diesem Beleg.')
        if not reason.strip():
            raise ValueError('Bitte die Änderung kurz begründen.')
    tx = TransactionIn(**{**values, 'document_id': document_id, 'source_type': 'pdf',
                         'source_ref': doc['original_filename'], 'review_status': 'geprueft'})
    if tx.depot_id not in {d['id'] for d in repo.depots(active_only=True)}:
        raise ValueError('Bitte ein aktives Depot zuordnen.')
    special_required = {
        TxType.AGE: ['trade_date', 'isin', 'amount'],
        TxType.TRANSFER_IN: ['trade_date', 'isin', 'quantity', 'amount'],
        TxType.TRANSFER_OUT: ['trade_date', 'isin', 'quantity'],
        TxType.SPLIT: ['trade_date', 'isin', 'ratio'],
        TxType.CORPORATE_ACTION: ['trade_date', 'isin'],
    }
    required = special_required.get(tx.tx_type, REQUIRED.get(tx.tx_type.value, ['trade_date', 'amount']))
    missing = [key for key in required if getattr(tx, key, None) is None]
    if missing:
        from .importers.pdf_importer import FIELD_LABELS
        raise ValueError('Bitte ergänzen: ' + ', '.join(FIELD_LABELS.get(k, k) for k in missing))
    if tx.isin and not isin_checksum_ok(tx.isin):
        raise ValueError('Die ISIN-Prüfziffer stimmt nicht.')
    if tx.trade_date > date.today():
        raise ValueError('Das Buchungsdatum liegt in der Zukunft.')
    if tx.currency != 'EUR' and tx.amount and not tx.fx_rate:
        raise ValueError('Für den Fremdwährungsbetrag fehlt der Devisenkurs (Währung je EUR).')
    duplicates = repo.find_duplicates(tx)
    exact = [r for r in duplicates['exact'] if r['id'] != transaction_id]
    possible = [r for r in duplicates['possible'] if r['id'] != transaction_id]
    if exact:
        raise ValueError('Identische Buchung bereits vorhanden: ' + ', '.join(f"#{r['id']}" for r in exact))
    if possible and not duplicate_confirmed:
        raise ValueError('Mögliche Dublette: ' + ', '.join(f"#{r['id']}" for r in possible)
                         + '. Erst vergleichen, dann die eigenständige Buchung ausdrücklich bestätigen.')
    if transaction_id is None:
        tid = repo.add_transaction(tx)
    else:
        editable = tx.model_dump(mode='json')
        for key in ('document_id', 'source_type', 'source_ref'):
            editable.pop(key, None)
        repo.update_transaction(transaction_id, editable, reason)
        tid = transaction_id
    dtype = {TxType.BUY: 'Kaufabrechnung', TxType.SELL: 'Verkaufsabrechnung',
             TxType.DIVIDEND: 'Dividendenabrechnung', TxType.DISTRIBUTION: 'Ausschüttungsabrechnung',
             TxType.INTEREST: 'Zinsabrechnung'}.get(tx.tx_type, 'Ertragsabrechnung')
    # Preserve parser evidence. Manual completion is distinct from automatic recognition.
    try:
        extraction = json.loads(doc.get('extraction_json') or '{}')
    except (ValueError, TypeError):
        extraction = {}
    if not isinstance(extraction, dict):
        extraction = {}
    extraction['manual_review'] = {'transaction_id': tid, 'confirmed': True,
                                   'reason': reason.strip() or 'Mit Original abgeglichen'}
    repo.update_document(document_id, status='verarbeitet', tax_year=tx.trade_date.year,
                         doc_type=dtype, extraction_json=json.dumps(extraction, ensure_ascii=False))
    repo.document_event(document_id, 'Direkt am Beleg geprüft',
                        {'buchung': tid, 'begründung': reason.strip(), 'dublette_bestaetigt': bool(possible)})
    return tid
