"""Content-based table import; ambiguous values remain in the original document."""
from __future__ import annotations

import csv
import io
import re
import zipfile

import pandas as pd

from .csv_importer import (_decode, _norm, auto_mapping, missing_required,
                           read_table, ImportError_, ImportOptions)


def automatic_tables(data: bytes, filename: str) -> list[pd.DataFrame]:
    """Find transaction headers after preambles and in repeated CSV sections.

    A nonempty malformed row invalidates its section; never silently skip it.
    """
    if filename.lower().endswith('.xlsx'):
        try:
            sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str, keep_default_na=False)
        except zipfile.BadZipFile as exc:
            raise ImportError_('Keine gültige XLSX-Datei') from exc
        from .oekb_layouts import pivot_published_table
        output = []
        for sheet in sheets.values():
            records = [list(map(str, sheet.columns))] + sheet.astype(str).values.tolist()
            pivot = pivot_published_table(records)
            output.append(pivot if pivot is not None else sheet)
        return output
    text, _ = _decode(data)
    candidates = []
    for sep in (';', ',', '\t', '|'):
        try:
            records = list(csv.reader(io.StringIO(text), delimiter=sep, strict=True))
        except csv.Error:
            continue
        from .oekb_layouts import pivot_published_table
        pivot = pivot_published_table(records)
        if pivot is not None:
            return [pivot]
        tables, header, rows = [], None, []
        for record in records:
            if not any(v.strip() for v in record):
                continue
            mapping = auto_mapping(record)
            from .oekb_importer import _auto_map, FUND_FIELDS
            fund_map = _auto_map(record)
            fund_header = all(fund_map.get(k) for k, (_, required, _) in FUND_FIELDS.items() if required)
            is_header = (not missing_required(mapping, ImportOptions()) or fund_header) and len(record) >= 3
            if is_header:
                if header is not None:
                    tables.append(pd.DataFrame(rows, columns=header))
                header, rows = [v.strip() for v in record], []
                if len(set(header)) != len(header):
                    raise ImportError_('Mehrdeutige, doppelte Spaltennamen in der Tabelle')
            elif header is not None:
                if len(record) != len(header):
                    raise ImportError_('Tabellenabschnitt enthält eine abweichende Spaltenzahl; Original zur Prüfung gespeichert')
                rows.append(record)
        if header is not None:
            tables.append(pd.DataFrame(rows, columns=header))
        if tables:
            candidates.append(tables)
    if len(candidates) > 1:
        raise ImportError_('Trennzeichen ist nicht eindeutig erkennbar')
    if candidates:
        return candidates[0]
    # Preserve familiar errors for unsupported tables, including OeKB tables.
    return [read_table(data, filename)[0]]


def table_broker(data: bytes, filename: str) -> str | None:
    # Only explicit broker names; a security named BlackRock is no broker evidence.
    text = filename + '\n' + (_decode(data)[0] if not filename.lower().endswith('.xlsx') else '')
    keys = [key for pattern, key in ((r'trade[ _-]*republic', 'TradeRepublic'),
                                    (r'scalable(?:[ _-]*capital)?', 'ScalableCapital'))
            if re.search(pattern, text, re.I)]
    return keys[0] if len(keys) == 1 else None


def automatic_mapping(columns: list[str]) -> dict:
    mapping = auto_mapping(columns)
    # Prefer explicit gross columns over generic cash amounts, regardless of order.
    gross = [c for c in columns if _norm(c) in ('brutto', 'bruttobetrag', 'gross amount', 'kurswert')]
    if len(gross) == 1:
        mapping['amount'] = gross[0]
    # German capital gains tax must never silently become Austrian KESt.
    tax = mapping.get('kest_at_eur')
    if tax and _norm(tax) not in ('kest at', 'österreichische kest'):
        mapping['kest_at_eur'] = None
    return mapping
