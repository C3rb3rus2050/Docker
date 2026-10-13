"""CSV-/Excel-Import mit automatischer und manueller Spaltenzuordnung, Vorschau und Dublettenprüfung.

Ablauf: ``read_table`` → ``auto_mapping`` (vom Benutzer änderbar) → ``build_preview`` →
Benutzerentscheidungen je Zeile → ``commit_preview``.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import ValidationError

from ..models import IncomeCategory, ReviewStatus, TransactionIn, TxType
from ..repository import Repository
from .parsing import detect_date_format, detect_decimal_separator, parse_date, parse_number, parse_tx_type

# Zielfeld -> (Bezeichnung, Pflicht, Synonyme in Kleinschreibung)
TARGET_FIELDS: dict[str, tuple[str, bool, tuple[str, ...]]] = {
    "trade_date": ("Buchungs-/Handelsdatum", True, ("datum", "date", "buchungsdatum", "handelstag", "schlusstag",
                                                    "ausführungsdatum", "ausfuehrungsdatum", "trade date",
                                                    "transaction date", "zeitpunkt", "timestamp", "tag")),
    "value_date": ("Valuta", False, ("valuta", "valutadatum", "wertstellung", "value date", "settlement date")),
    "tx_type": ("Buchungsart", True, ("typ", "type", "art", "buchungsart", "transaktionsart", "transaction type",
                                      "vorgang", "geschäftsart", "geschaeftsart", "aktion", "kategorie")),
    "isin": ("ISIN", False, ("isin", "wertpapierkennnummer isin", "isin code")),
    "security_name": ("Wertpapiername", False, ("name", "wertpapier", "bezeichnung", "titel", "security",
                                                "instrument", "produkt", "asset", "wertpapiername", "description")),
    "quantity": ("Stückzahl", False, ("stück", "stueck", "stk", "anzahl", "menge", "quantity", "shares", "units",
                                      "nominale", "stückzahl", "stueckzahl")),
    "price": ("Kurs", False, ("kurs", "preis", "price", "ausführungskurs", "ausfuehrungskurs", "kurs je stück",
                              "share price")),
    "currency": ("Währung", False, ("währung", "waehrung", "currency", "whg", "ccy")),
    "amount": ("Betrag (brutto)", True, ("betrag", "amount", "kurswert", "bruttobetrag", "brutto", "gesamt",
                                         "total", "wert", "value", "ordervolumen", "summe")),
    "fees": ("Gebühren", False, ("gebühren", "gebuehren", "gebühr", "fee", "fees", "provision", "kosten",
                                 "fremdkosten", "transaktionskosten", "commission")),
    "fx_rate": ("Devisenkurs (Währung je EUR)", False, ("devisenkurs", "wechselkurs", "fx rate", "exchange rate",
                                                         "fx", "umrechnungskurs")),
    "withholding_tax": ("Quellensteuer", False, ("quellensteuer", "withholding tax", "withholding", "qst",
                                                 "ausländische steuer", "auslaendische steuer", "foreign tax")),
    "withholding_country": ("Quellenstaat (ISO-2)", False, ("land", "country", "quellenstaat", "herkunftsland")),
    "kest_at_eur": ("Österr. KESt (EUR)", False, ("kest", "kapitalertragsteuer", "kest at", "österreichische kest")),
    "ratio": ("Verhältnis (Split)", False, ("verhältnis", "verhaeltnis", "ratio", "split ratio")),
    "notes": ("Notiz", False, ("notiz", "notes", "bemerkung", "kommentar", "comment", "verwendungszweck")),
}

NUMERIC_FIELDS = ("quantity", "price", "amount", "fees", "fx_rate", "withholding_tax", "kest_at_eur", "ratio")


class ImportError_(ValueError):
    pass


@dataclass
class ImportOptions:
    decimal: str = "auto"                  # auto | , | .
    date_format: str | None = None         # None = automatisch
    date_candidates: list[str] = field(default_factory=lambda: ["%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y",
                                                                "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y"])
    default_currency: str = "EUR"
    default_tx_type: str | None = None     # wenn keine Typspalte vorhanden
    amount_is: str = "brutto"              # brutto | netto
    type_value_map: dict[str, str] = field(default_factory=dict)  # Rohwert -> TxType.value


@dataclass
class PreviewRow:
    row_no: int
    raw: dict
    tx: TransactionIn | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicate: str = "neu"                 # neu | dublette | moeglich | dublette_in_datei
    duplicate_ids: list[int] = field(default_factory=list)

    @property
    def default_decision(self) -> str:
        if self.errors:
            return "ignorieren"
        if self.duplicate in ("dublette", "dublette_in_datei"):
            return "ignorieren"
        if self.duplicate == "moeglich" or self.warnings:
            return "pruefen"
        return "uebernehmen"


# --------------------------------------------------------------------------- #
def _decode(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            if enc == "utf-16" and "\x00" in text:
                continue
            return text, enc
        except UnicodeDecodeError:
            continue
    raise ImportError_("Zeichenkodierung der Datei nicht erkannt")


def _sniff_sep(text: str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        counts = {sep: sample.count(sep) for sep in (";", ",", "\t", "|")}
        return max(counts, key=counts.get)


def read_table(data: bytes, filename: str, sheet: str | int | None = 0) -> tuple[pd.DataFrame, dict]:
    """Liest CSV/TXT/XLSX als DataFrame aus Zeichenketten (keine automatische Typumwandlung)."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        try:
            df = pd.read_excel(io.BytesIO(data), sheet_name=sheet, dtype=str)
        except Exception as exc:
            raise ImportError_(f"Excel-Datei nicht lesbar: {exc}") from exc
        meta = {"format": "excel", "sheet": sheet}
    else:
        text, enc = _decode(data)
        if "\x00" in text:
            raise ImportError_("Datei enthält Binärdaten – keine CSV-Datei")
        sep = _sniff_sep(text)
        try:
            df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False, engine="python",
                             skip_blank_lines=True)
        except Exception as exc:
            raise ImportError_(f"CSV-Datei nicht lesbar: {exc}") from exc
        meta = {"format": "csv", "encoding": enc, "separator": sep}
    df.columns = [str(c).strip() for c in df.columns]
    df = df.fillna("")
    df = df.loc[~(df.astype(str).apply(lambda r: "".join(r).strip(), axis=1) == "")]
    meta["rows"] = len(df)
    return df.reset_index(drop=True), meta


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-./()]+", " ", str(s).strip().lower()).strip()


def auto_mapping(columns: list[str]) -> dict[str, str | None]:
    """Ordnet Spalten anhand von Synonymen zu. Exakte Treffer haben Vorrang vor Teiltreffern."""
    mapping: dict[str, str | None] = {k: None for k in TARGET_FIELDS}
    used: set[str] = set()
    normed = {c: _norm(c) for c in columns}
    for exact in (True, False):
        for target, (_, _, syns) in TARGET_FIELDS.items():
            if mapping[target]:
                continue
            for col, n in normed.items():
                if col in used:
                    continue
                hit = n in syns if exact else any(re.search(rf"\b{re.escape(s)}\b", n) for s in syns if len(s) > 2)
                if hit:
                    mapping[target] = col
                    used.add(col)
                    break
    return mapping


def missing_required(mapping: dict[str, str | None], options: ImportOptions) -> list[str]:
    missing = []
    for target, (label, required, _) in TARGET_FIELDS.items():
        if required and not mapping.get(target):
            if target == "tx_type" and options.default_tx_type:
                continue
            if target == "amount" and mapping.get("quantity") and mapping.get("price"):
                continue
            missing.append(label)
    return missing


# --------------------------------------------------------------------------- #
def build_preview(df: pd.DataFrame, mapping: dict[str, str | None], options: ImportOptions, depot_id: int,
                  repo: Repository | None = None, fuzzy_days: int = 3) -> list[PreviewRow]:
    miss = missing_required(mapping, options)
    if miss:
        raise ImportError_("Pflichtspalten nicht zugeordnet: " + ", ".join(miss))

    col = {k: v for k, v in mapping.items() if v}
    decimals: dict[str, str] = {}
    for f in NUMERIC_FIELDS:
        if f in col:
            decimals[f] = options.decimal if options.decimal in (",", ".") else \
                detect_decimal_separator(df[col[f]].tolist())
    date_fmt = options.date_format or detect_date_format(df[col["trade_date"]].tolist(), options.date_candidates)
    vdate_fmt = None
    if "value_date" in col:
        vdate_fmt = options.date_format or detect_date_format(df[col["value_date"]].tolist(), options.date_candidates)

    rows: list[PreviewRow] = []
    seen_fp: dict[str, int] = {}
    for idx, rec in df.iterrows():
        row_no = int(idx) + 2  # Kopfzeile = Zeile 1
        raw = {c: rec[c] for c in df.columns}
        errors: list[str] = []
        warnings: list[str] = []
        values: dict[str, Any] = {"depot_id": depot_id, "source_type": "csv", "source_ref": f"Zeile {row_no}"}

        def get(target):
            return rec[col[target]] if target in col else None

        # Datum
        try:
            values["trade_date"] = parse_date(get("trade_date"), date_fmt, options.date_candidates)
            if values["trade_date"] is None:
                errors.append("Datum fehlt")
        except ValueError as exc:
            errors.append(str(exc))
        if "value_date" in col:
            try:
                values["value_date"] = parse_date(get("value_date"), vdate_fmt, options.date_candidates)
            except ValueError as exc:
                warnings.append(f"Valuta: {exc}")
        # Buchungsart
        raw_type = get("tx_type")
        t: TxType | None = None
        if raw_type is not None and str(raw_type).strip():
            mapped = options.type_value_map.get(str(raw_type).strip())
            t = TxType(mapped) if mapped else parse_tx_type(raw_type)
            if t is None:
                errors.append(f"Buchungsart '{raw_type}' unbekannt – bitte zuordnen")
        elif options.default_tx_type:
            t = TxType(options.default_tx_type)
        else:
            errors.append("Buchungsart fehlt")
        if t is not None:
            values["tx_type"] = t
        # Zahlen
        nums: dict[str, float | None] = {}
        for f in NUMERIC_FIELDS:
            if f in col:
                try:
                    nums[f] = parse_number(get(f), decimals[f])
                except ValueError as exc:
                    errors.append(f"{TARGET_FIELDS[f][0]}: {exc}")
        signed_amount = nums.get("amount")
        if nums.get("amount") is None and nums.get("quantity") and nums.get("price"):
            nums["amount"] = abs(nums["quantity"]) * abs(nums["price"])
            warnings.append("Betrag aus Stückzahl × Kurs berechnet")
        for f, v in nums.items():
            if v is not None:
                values[f] = abs(v)
        values["fees"] = values.get("fees") or 0.0
        values["withholding_tax"] = values.get("withholding_tax") or 0.0
        values["kest_at_eur"] = values.get("kest_at_eur") or 0.0
        # Netto -> Brutto
        if options.amount_is == "netto" and values.get("amount") is not None and t is not None:
            a, fees = values["amount"], values["fees"]
            if t in (TxType.BUY, TxType.TRANSFER_IN):
                values["amount"] = a - fees
            elif t == TxType.SELL:
                values["amount"] = a + fees
            elif t in (TxType.DIVIDEND, TxType.DISTRIBUTION, TxType.INTEREST):
                values["amount"] = a + values["withholding_tax"] + values["kest_at_eur"]
            warnings.append("Bruttobetrag aus Nettobetrag zurückgerechnet")
        if signed_amount is not None and t is not None:
            if t == TxType.BUY and signed_amount > 0 and options.amount_is == "netto":
                warnings.append("Kauf mit positivem Betrag – Vorzeichen prüfen")
            if t in (TxType.SELL, TxType.DIVIDEND) and signed_amount < 0:
                warnings.append("Negativer Betrag bei Ertrag/Verkauf – Storno oder Vorzeichenfehler?")
        # Text
        for f in ("isin", "security_name", "withholding_country", "notes"):
            v = get(f)
            if v is not None and str(v).strip() and str(v).strip().lower() != "nan":
                values[f] = str(v).strip()
        cur = get("currency")
        values["currency"] = (str(cur).strip() if cur and str(cur).strip() else options.default_currency)
        if values["currency"] != "EUR" and not values.get("fx_rate"):
            warnings.append(f"Fremdwährung {values['currency']} ohne Devisenkurs – EUR-Betrag fehlt")
        if values.get("withholding_tax") and not values.get("withholding_country"):
            warnings.append("Quellensteuer ohne Quellenstaat – Anrechnung nicht ermittelbar")

        tx = None
        if not errors:
            try:
                values["review_status"] = ReviewStatus.TO_REVIEW if warnings else ReviewStatus.UNCHECKED
                values["income_category"] = IncomeCategory.AUTO
                tx = TransactionIn(**values)
            except ValidationError as exc:
                errors.extend(f"{'.'.join(str(x) for x in e['loc']) or 'Zeile'}: {e['msg']}" for e in exc.errors())
        pr = PreviewRow(row_no=row_no, raw=raw, tx=tx, errors=errors, warnings=warnings)
        if tx is not None:
            fp = Repository.fingerprint(tx)
            if fp in seen_fp:
                pr.duplicate = "dublette_in_datei"
                pr.warnings.append(f"identisch mit Zeile {seen_fp[fp]} dieser Datei")
            else:
                seen_fp[fp] = row_no
            if repo is not None:
                d = repo.find_duplicates(tx, fuzzy_days=fuzzy_days)
                if d["exact"]:
                    pr.duplicate = "dublette"
                    pr.duplicate_ids = [r["id"] for r in d["exact"]]
                elif d["possible"] and pr.duplicate == "neu":
                    pr.duplicate = "moeglich"
                    pr.duplicate_ids = [r["id"] for r in d["possible"]]
        rows.append(pr)
    return rows


def preview_frame(rows: list[PreviewRow]) -> pd.DataFrame:
    out = []
    for r in rows:
        t = r.tx
        out.append({
            "Zeile": r.row_no,
            "Entscheidung": r.default_decision,
            "Status": "Fehler" if r.errors else ("Warnung" if r.warnings else "OK"),
            "Dublette": r.duplicate,
            "Dubletten-IDs": ", ".join(map(str, r.duplicate_ids)),
            "Datum": t.trade_date.isoformat() if t else "",
            "Art": t.tx_type.value if t else "",
            "ISIN": (t.isin or "") if t else "",
            "Name": (t.security_name or "") if t else "",
            "Stück": t.quantity if t else None,
            "Kurs": t.price if t else None,
            "Währung": t.currency if t else "",
            "Betrag": t.amount if t else None,
            "Gebühren": t.fees if t else None,
            "Quellensteuer": t.withholding_tax if t else None,
            "Meldungen": "; ".join(r.errors + r.warnings),
        })
    return pd.DataFrame(out)


def commit_preview(repo: Repository, rows: list[PreviewRow], decisions: dict[int, str], *, import_type: str,
                   depot_id: int, document_id: int | None = None) -> dict:
    """Übernimmt die Vorschauzeilen gemäß Benutzerentscheidung.

    decisions: Zeilennummer -> uebernehmen | ignorieren | pruefen (übernehmen mit Prüfkennzeichen)
    """
    run_id = repo.start_import(import_type, document_id, depot_id)
    counts = {"rows_total": len(rows), "rows_imported": 0, "rows_duplicates": 0, "rows_skipped": 0, "rows_errors": 0}
    created: list[int] = []
    for r in rows:
        decision = decisions.get(r.row_no, r.default_decision)
        if r.errors:
            counts["rows_errors"] += 1
            repo.log_import(run_id, "FEHLER", "; ".join(r.errors), r.row_no)
            continue
        if r.duplicate != "neu":
            counts["rows_duplicates"] += 1
        if decision == "ignorieren":
            counts["rows_skipped"] += 1
            repo.log_import(run_id, "INFO", f"ignoriert ({r.duplicate})", r.row_no)
            continue
        tx = r.tx.model_copy(update={"document_id": document_id})
        if decision == "pruefen" or r.duplicate != "neu":
            tx = tx.model_copy(update={"review_status": ReviewStatus.TO_REVIEW})
            note = f"Dublettenverdacht zu Buchung(en) {r.duplicate_ids}" if r.duplicate != "neu" else None
            if note:
                tx = tx.model_copy(update={"notes": "; ".join(filter(None, [tx.notes, note]))})
        tid = repo.add_transaction(tx, import_run_id=run_id)
        created.append(tid)
        counts["rows_imported"] += 1
        for w in r.warnings:
            repo.log_import(run_id, "WARNUNG", w, r.row_no)
        if r.duplicate != "neu":
            repo.log_import(run_id, "WARNUNG", f"trotz Dublettenverdacht ({r.duplicate}) übernommen – prüfen",
                            r.row_no)
    status = "abgeschlossen" if counts["rows_errors"] == 0 else "mit Fehlern"
    repo.finish_import(run_id, status, **counts,
                       message=f"{counts['rows_imported']} übernommen, {counts['rows_skipped']} ignoriert, "
                               f"{counts['rows_errors']} fehlerhaft")
    if document_id:
        doc_status = "verarbeitet" if counts["rows_errors"] == 0 and counts["rows_imported"] else \
            ("teilweise" if counts["rows_imported"] else "pruefen")
        repo.update_document(document_id, status=doc_status)
    return {"run_id": run_id, "created": created, **counts}
