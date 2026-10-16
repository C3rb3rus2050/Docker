"""Review completeness and validated, audited security edits."""
from __future__ import annotations

import json
import re

from .db import now_iso
from .models import SecurityIn, FUND_SECURITY_TYPES, TaxClass, FundStatus, SecurityType


def review_reasons(sec: dict) -> list[str]:
    reasons = []
    if not (sec.get('name') or '').strip():
        reasons.append('Wertpapiername fehlt')
    if sec.get('security_type') == SecurityType.OTHER.value:
        reasons.append('Wertpapierart noch offen')
    if (sec.get('tax_class') == TaxClass.UNGEKLAERT.value or not sec.get('tax_class_verified')
            or not (sec.get('tax_class_source') or '').strip()):
        reasons.append('Steuerliche Einstufung mit Quelle prüfen')
    is_fund = sec.get('security_type') in {t.value for t in FUND_SECURITY_TYPES} or \
        sec.get('tax_class') == TaxClass.INVESTMENTFONDS.value
    if is_fund and (sec.get('fund_status') not in {FundStatus.MELDEFONDS.value, FundStatus.NICHTMELDEFONDS.value}
                   or not sec.get('fund_status_verified') or not (sec.get('fund_status_source') or '').strip()):
        reasons.append('Meldefondsstatus mit Quelle prüfen')
    if sec.get('review_status') != 'geprueft':
        reasons.append('Gesamtprüfung noch nicht bestätigt')
    return reasons


def save_security_review(repo, values: dict, *, existing_isin: str | None = None,
                         review: str = 'ungeprueft', price_symbol: str = '') -> str:
    sec = SecurityIn(**values)
    if review not in {'ungeprueft', 'pruefen', 'geprueft'}:
        raise ValueError('Ungültiger Prüfstatus.')
    data = sec.model_dump(mode='json')
    for name, pattern in [('country', r'[A-Z]{2}'), ('currency', r'[A-Z]{3}')]:
        value = (data.get(name) or '').strip().upper()
        if value and not re.fullmatch(pattern, value):
            raise ValueError('Sitzstaat benötigt ISO-2, Handelswährung benötigt ISO-3.')
        data[name] = value or None
    data.update(review_status=review, price_symbol=price_symbol.strip() or None)
    if review == 'geprueft':
        problems = review_reasons(data)
        if problems:
            raise ValueError('Noch nicht vollständig geprüft: ' + '; '.join(problems))
    if existing_isin is not None and existing_isin != sec.isin:
        raise ValueError('Die ISIN eines bestehenden Wertpapiers kann hier nicht geändert werden.')
    with repo.db.tx() as conn:
        row = conn.execute('SELECT * FROM securities WHERE isin=?', (sec.isin,)).fetchone()
        old = dict(row) if row else None
        if existing_isin and old is None:
            raise ValueError('Wertpapier nicht mehr vorhanden. Seite neu laden.')
        if not existing_isin and old:
            raise ValueError('Diese ISIN existiert bereits. Die vorhandene Karte bearbeiten.')
        if old:
            conn.execute('UPDATE securities SET ' + ','.join(f'{k}=?' for k in data) + ',updated_at=? WHERE isin=?',
                         (*data.values(), now_iso(), sec.isin))
        else:
            conn.execute('INSERT INTO securities(' + ','.join(data) + ',created_at,updated_at) VALUES('
                         + ','.join('?' for _ in range(len(data) + 2)) + ')',
                         (*data.values(), now_iso(), now_iso()))
        changes = {k: v for k, v in data.items() if not old or old.get(k) != v}
        conn.execute('INSERT INTO audit_log(ts,entity,entity_id,action,details) VALUES(?,?,?,?,?)',
                     (now_iso(), 'security', sec.isin, 'direkt geprüft' if old else 'angelegt',
                      json.dumps({'grund': 'Wertpapierkarte', 'alt': {k: old.get(k) for k in changes} if old else {},
                                  'neu': changes}, ensure_ascii=False)))
    return sec.isin
