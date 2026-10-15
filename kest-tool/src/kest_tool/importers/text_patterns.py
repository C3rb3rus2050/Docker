"""Explainable fallback fingerprints; inferred families always require review.

Patterns are derived from public broker layouts, not from uploaded filenames.
Independent body signals are required when the document title is missing.
"""
from __future__ import annotations

import re
import unicodedata


def normalize_document_text(text: str) -> str:
    text = unicodedata.normalize('NFKC', text).replace('\u00ad', '').replace('\u200b', '')
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('−', '-')
    # OCR sometimes spaces every letter of a heading. Never collapse amounts.
    lines = []
    for line in text.splitlines():
        line = re.sub(r'[ \t]+', ' ', line).strip()
        if re.fullmatch(r'(?:[A-ZÄÖÜ] ){5,}[A-ZÄÖÜ]', line):
            line = line.replace(' ', '')
        lines.append(line)
    text = '\n'.join(lines)
    # Join only known hyphenated headings, never arbitrary body text/numbers.
    text = re.sub(r'(?im)^(Wertpapier|Dividenden|Jahressteuer|Kosten|Zins)-\n(abrechnung|bescheinigung|information)\b',
                  lambda m: m[1] + m[2], text)
    return text


FINGERPRINTS = [
    ('Kaufabrechnung', 'Kauf', (
        r'(?im)^.*(?:Wir haben.*für Sie.*gekauft|We have purchased.*for you).*$',
        r'(?im)^(?:Kurswert|Market Value|Ausführungskurs|Execution price)\b.*\d.*$')),
    ('Verkaufsabrechnung', 'Verkauf', (
        r'(?im)^.*(?:Wir haben.*für Sie.*verkauft|We have sold.*for you).*$',
        r'(?im)^(?:Kurswert|Market Value|Ausführungskurs|Execution price)\b.*\d.*$')),
    ('Jahressteuerbescheinigung', None, (
        r'(?im)^.*Bescheinigung.*(?:§\s*45a|Kapitalerträge).*$',
        r'(?im)^.*(?:Höhe der Kapitalerträge|Summe der Kapitalerträge).*$',
        r'(?im)^.*(?:Zeile\s+\d+.*Anlage KAP|Anlage KAP.*Zeile\s+\d+).*$')),
    ('Kontoauszug', None, (
        r'(?im)^.*(?:Anfangssaldo|Anfangsbestand|Opening balance|Alter Kontostand).*$',
        r'(?im)^.*(?:Endsaldo|Endbestand|Closing balance|Neuer Kontostand).*$',
        r'(?im)^.*(?:Buchungstag.*(?:Valuta|Wertstellung)|Booking date.*Value date).*$')),
    ('Depotauszug', None, (
        r'(?im)^.*(?:Depotbestand zum|Portfolio holdings as of|Bestandsverzeichnis).*$',
        r'(?im)^.*(?:ISIN.*(?:Kurswert|Bewertung)|(?:Kurswert|Bewertung).*ISIN).*$')),
    ('Kosteninformation', None, (
        r'(?im)^.*(?:Voraussichtliche Kosten|Estimated costs|Kosten bei einer Haltedauer).*$',
        r'(?im)^.*(?:Produktkosten|Product costs).*$',
        r'(?im)^.*(?:Dienstleistungskosten|Service costs).*$')),
    ('Dividendenabrechnung', 'Dividende', (
        r'(?im)^(?:Berechtigtes\s*Wertpapier|Entitled security)\s+.+$',
        r'(?im)^.*(?:Ex[- ]Tag.*Zahltag|Ex[- ]date.*Payment date|Dividende pro Stück|Dividend per share).*$')),
    ('Zinsabrechnung', 'Zinsen', (
        r'(?im)^(?:Zinszeitraum|Interest period)\b.*\d.*$',
        r'(?im)^(?:Bruttozinsen|Gross interest|Habenzinsen(?: \(HZ\))? \(brutto\))(?:\s|:).*$',
        r'(?im)^.*(?:Zinssatz|Interest rate).*%.*$')),
]


def text_fingerprint(text: str) -> dict | None:
    """Two or more independent signals; ties are surfaced rather than resolved by order."""
    matches = []
    for family, tx_type, patterns in FINGERPRINTS:
        evidence = [m[0].strip()[:180] for p in patterns if (m := re.search(p, text))]
        if len(evidence) >= 2:
            matches.append({'doc_type': family, 'tx_type': tx_type, 'evidence': evidence,
                            'method': 'Textbausteine', 'confidence': .7})
    if len(matches) == 1:
        return matches[0]
    if matches:
        return {'doc_type': 'Sammelabrechnung', 'tx_type': None,
                'evidence': [f"{m['doc_type']}: {'; '.join(m['evidence'])}" for m in matches],
                'method': 'Widersprüchliche Textbausteine', 'confidence': .4}
    return None
