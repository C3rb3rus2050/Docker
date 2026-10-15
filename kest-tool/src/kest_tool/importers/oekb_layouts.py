"""OeKB published private-investor layouts (amounts per unit, without option).

Sources and sample URLs: docs/OEKB-MUSTER.md. No totals or tax rates are
substituted for per-unit amounts. Unsupported layouts remain reviewable.
"""
from __future__ import annotations

import io
import re

import pandas as pd

from ..models import isin_checksum_ok
from .parsing import parse_number

VALUE = re.compile(r'(?<![\w.,])[-+−]?(?:\d{1,3}(?:\.\d{3})*|\d+)[,.]\d{4,8}(?![\d.,%])')
DATE = r'(?:\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2})'


def label_field(label: str) -> str | None:
    label = re.sub(r'\s+', ' ', label).strip().lower()
    if re.search(r'^(?:16\.2\s|ausschüttungsgleiche erträge\b)', label):
        return 'age_per_unit'
    if re.search(r'^(?:16\.1\s|ausschüttungen 27[,\.]5)', label):
        return 'taxable_distribution_per_unit'
    if re.search(r'^(?:16\.3\s|anzurechnende ausländische)', label):
        return 'creditable_tax_per_unit'
    if re.search(r'^(?:16\.4\s|die anschaffungskosten des fondsanteils)', label):
        return 'ak_correction_per_unit'
    return None


def _put(values: dict, key: str, value, warnings: list[str]) -> None:
    if key in values and values[key] != value:
        warnings.append(f'Widersprüchliche Werte für {key}; Original prüfen')
    else:
        values[key] = value


def parse_published_report(text: str) -> dict:
    """Parse one ISIN/report group from the published OeKB PDF text layout."""
    values, warnings = {}, []
    found = {'values': values, 'warnings': warnings, 'missing': [], 'engine': 'OeKB-Privatanleger',
             'text_excerpt': text[:3000]}
    def match(pattern):
        return re.search(pattern, text, re.I | re.M)
    isins = set(re.findall(r'\bISIN\s+([A-Z]{2}[A-Z0-9]{9}\d)\b', text))
    if len(isins) == 1 and isin_checksum_ok(next(iter(isins))):
        values['isin'] = next(iter(isins))
    else:
        warnings.append('ISIN nicht eindeutig oder Prüfziffer ungültig')
    for key, pattern in (
        ('report_date', rf'(?:Meldedatum|(?:Jahresdatenmeldung|Ausschüttungsmeldung) vom)\s+({DATE})'),
        ('fiscal_year_end', rf'Geschäftsjahres?[- ]?Ende\s+({DATE})'),
        ('distribution_date', rf'(?:Ausschüttungstag|Ex-Tag)\s+({DATE})'),
        ('currency', r'Währung, in der die Meldung vorgenommen wurde\s+([A-Z]{3})'),
        ('fund_name', r'Name der Anteilsgattung des Fonds[^\S\n]+([^\n]+)'),
    ):
        m = match(pattern)
        if m:
            v = m.group(1).strip()
            if key.endswith('date') or key == 'fiscal_year_end':
                from datetime import datetime
                v = datetime.strptime(v, '%d.%m.%Y' if '.' in v else '%Y-%m-%d').date().isoformat()
            values[key] = v
    if not values.get('currency'):
        m = match(r'^\s*Währung\s+([A-Z]{3})\s*$')
        if m:
            values['currency'] = m.group(1)
    annual = bool(match(r'Jahresmeldung\s+JA|Jahresdatenmeldung vom'))
    distribution = bool(match(r'Ausschüttungsmeldung\s+JA|Ausschüttungsmeldung vom'))
    if annual or distribution:
        values['report_type'] = 'Jahresmeldung' if annual else 'Ausschuettungsmeldung'
    else:
        warnings.append('Meldungsart fehlt')
    if match(r'Art(?: gem FMV 2015)?\s+AIF\b'):
        warnings.append('AIF-Meldung: gesonderte Einkünfte im Original prüfen')
    if not match(r'(?:Privatanleger mit Option\s+Privatanleger ohne Option|PV mit\s+PV ohne)'):
        warnings.append('Anleger-Spalten nicht eindeutig erkannt')
    else:
        for line in text.splitlines():
            if re.match(r'^\s*16\.2\.1\s', line) and any(float(v.replace(',', '.')) != 0 for v in VALUE.findall(line)):
                warnings.append('Nicht gemeldete unterjährige Ausschüttungen gesondert prüfen')
            key = label_field(line)
            if not key:
                continue
            amounts = VALUE.findall(line)
            if len(amounts) >= 2:
                _put(values, key, parse_number(amounts[1].replace('−', '-'),
                                               ',' if ',' in amounts[1] else '.'), warnings)
    for key in ('isin', 'report_date', 'currency'):
        if key not in values:
            found['missing'].append(key)
    for key in ('age_per_unit', 'taxable_distribution_per_unit', 'creditable_tax_per_unit', 'ak_correction_per_unit'):
        if key not in values:
            found['missing'].append(f'Kennzahl je Anteil fehlt: {key}')
    return found


def extract_published_reports(data: bytes) -> list[dict]:
    import pdfplumber
    groups, current = [], []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if len(pdf.pages) > 250:
            raise ValueError('OeKB-Datei hat mehr als 250 Seiten')
        for page in pdf.pages:
            text = page.extract_text() or ''
            if re.search(r'\bISIN\s+[A-Z]{2}[A-Z0-9]{9}\d\b', text) and current:
                groups.append('\n'.join(current))
                current = []
            current.append(text)
    if current:
        groups.append('\n'.join(current))
    return [parse_published_report(text) for text in groups if 'OeKB' in text or 'oekb' in text.lower()]


def pivot_published_table(records: list[list[str]]) -> pd.DataFrame | None:
    """Recognize a metadata + Bezeichnung/Privatanleger export without user mapping."""
    header_index = next((i for i, row in enumerate(records) if any(
        re.fullmatch(r'(?:privatanleger|pv)\s+ohne\s+option', c.strip(), re.I) for c in row)), None)
    if header_index is None:
        return None
    header = records[header_index]
    value_index = next(i for i, c in enumerate(header) if re.fullmatch(
        r'(?:privatanleger|pv)\s+ohne\s+option', c.strip(), re.I))
    values, warnings = {}, []
    meta = {'isin': 'isin', 'meldedatum': 'report_date', 'währung': 'currency',
            'währung, in der die meldung vorgenommen wurde': 'currency',
            'geschäftsjahres-ende': 'fiscal_year_end', 'fondsname': 'fund_name'}
    for row in records[:header_index]:
        if len(row) >= 2 and row[0].strip().lower() in meta:
            _put(values, meta[row[0].strip().lower()], row[1].strip(), warnings)
        if len(row) >= 2 and row[0].strip().lower() == 'jahresmeldung' and row[1].strip().upper() == 'JA':
            values['report_type'] = 'Jahresmeldung'
        if len(row) >= 2 and row[0].strip().lower() == 'ausschüttungsmeldung' and row[1].strip().upper() == 'JA':
            values.setdefault('report_type', 'Ausschuettungsmeldung')
    for row in records[header_index + 1:]:
        if not any(c.strip() for c in row):
            continue
        if len(row) != len(header):
            raise ValueError('OeKB-Tabelle enthält eine abweichende Spaltenzahl')
        key = label_field(row[0])
        if key:
            _put(values, key, row[value_index].strip(), warnings)
    if warnings:
        raise ValueError('; '.join(warnings))
    # Internal names are recognized by _auto_map too.
    return pd.DataFrame([values])
