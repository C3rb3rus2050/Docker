"""Manueller Import steuerlicher Fondsdaten (OeKB-Meldungen) aus CSV/Excel oder PDF.

Automatischer Abruf: Es wurde KEINE öffentlich dokumentierte, frei nutzbare OeKB-Schnittstelle für
steuerliche Fondsmeldungen verifiziert (Stand der Recherche: Oktober 2026). Die OeKB bietet Fondsdaten
über „my.oekb.at“ bzw. vertragliche Datenlieferungen („Fondsdaten Plus“, Fondsdaten-Portal mit
Nutzungsbedingungen) an. Deshalb ist der automatische Weg als Schnittstelle vorbereitet, aber ohne
Anbieter (``NoAutomaticProvider``) – die Oberfläche zeigt das transparent an.

Alle importierten Werte werden als „ungeprüft“ gespeichert. Abweichungen zu bestehenden Meldungen
werden als Konflikt angelegt und nie stillschweigend überschrieben.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from pydantic import ValidationError

from ..models import FundReportIn, isin_checksum_ok
from ..repository import Repository
from .csv_importer import read_table
from .parsing import detect_date_format, detect_decimal_separator, parse_date, parse_number
from .pdf_importer import DATE, ISIN_RX, NUM, _date, _num, extract_text

FUND_FIELDS: dict[str, tuple[str, bool, tuple[str, ...]]] = {
    "isin": ("ISIN", True, ("isin",)),
    "fund_name": ("Fondsname", False, ("fondsname", "name", "fonds", "bezeichnung")),
    "report_type": ("Meldungsart", False, ("meldungsart", "art", "typ", "report type")),
    "fiscal_year_end": ("Geschäftsjahresende", False, ("geschäftsjahresende", "geschaeftsjahresende", "gj-ende",
                                                        "gj ende", "fiscal year end", "geschäftsjahr")),
    "report_date": ("Meldedatum / Zuflussdatum", True, ("meldedatum", "zuflussdatum", "zufluss", "datum der meldung",
                                                       "report date", "meldezeitpunkt")),
    "distribution_date": ("Ausschüttungstag (Ex-Tag)", False, ("ex-tag", "ex tag", "ausschüttungstag",
                                                                "ausschuettungstag", "ex-date")),
    "currency": ("Währung", False, ("währung", "waehrung", "currency")),
    "fx_rate": ("Devisenkurs (Währung je EUR)", False, ("devisenkurs", "fx rate", "wechselkurs")),
    "distribution_per_unit": ("Ausschüttung je Anteil", False, ("ausschüttung", "ausschuettung", "ausschüttung je anteil",
                                                                 "distribution")),
    "age_per_unit": ("Ausschüttungsgleiche Erträge je Anteil", False, ("ausschüttungsgleiche erträge", "age",
                                                                        "ausschuettungsgleiche ertraege",
                                                                        "ausschüttungsgleicher ertrag")),
    "taxable_distribution_per_unit": ("Steuerpflichtiger Teil der Ausschüttung je Anteil", False,
                                      ("steuerpflichtige ausschüttung", "steuerpflichtiger teil",
                                       "davon steuerpflichtig")),
    "creditable_tax_per_unit": ("Anrechenbare ausländische Steuer je Anteil", False,
                                ("anrechenbare quellensteuer", "anrechenbare ausländische steuer",
                                 "anrechenbare steuer", "quellensteuer")),
    "ak_correction_per_unit": ("Korrekturbetrag Anschaffungskosten je Anteil", False,
                               ("korrekturbetrag", "anschaffungskosten korrektur", "ak-korrektur", "ak korrektur",
                                "korrektur anschaffungskosten")),
    "kest_per_unit": ("KESt je Anteil", False, ("kest", "kapitalertragsteuer")),
    "is_meldefonds": ("Meldefonds (ja/nein)", False, ("meldefonds", "steuerlicher vertreter")),
}


class AutomaticProvider:
    """Schnittstelle für einen automatischen Abruf offizieller Fondsdaten."""

    name = "abstract"
    available = False
    reason = ""

    def fetch(self, isin: str, year: int) -> list[FundReportIn]:  # pragma: no cover - Schnittstelle
        raise NotImplementedError


class NoAutomaticProvider(AutomaticProvider):
    name = "keiner"
    available = False
    reason = ("Kein automatischer Abruf: Eine öffentlich dokumentierte, frei nutzbare OeKB-Schnittstelle für "
              "steuerliche Fondsmeldungen konnte nicht verifiziert werden. Die OeKB stellt Fondsdaten über my.oekb.at "
              "bzw. vertragliche Datenlieferungen (Fondsdaten-Portal, „Fondsdaten Plus“) bereit, die Nutzungs-"
              "bedingungen und ggf. Registrierung/Entgelt erfordern. Bitte Meldungen manuell herunterladen und als "
              "CSV/PDF importieren oder manuell erfassen.")

    def fetch(self, isin: str, year: int) -> list[FundReportIn]:
        raise RuntimeError(self.reason)


def get_provider(name: str | None) -> AutomaticProvider:
    # Weitere Anbieter dürfen nur ergänzt werden, wenn ein rechtmäßig nutzbarer, dokumentierter Zugang besteht.
    return NoAutomaticProvider()


@dataclass
class FundPreview:
    row_no: int
    report: FundReportIn | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _auto_map(columns: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {k: None for k in FUND_FIELDS}
    used: set[str] = set()
    norm = {c: re.sub(r"\s+", " ", c.strip().lower()) for c in columns}
    for exact in (True, False):
        for k, (_, _, syns) in FUND_FIELDS.items():
            if out[k]:
                continue
            for c, n in norm.items():
                if c in used:
                    continue
                if (n in syns) if exact else any(s in n for s in syns if len(s) > 3):
                    out[k] = c
                    used.add(c)
                    break
    return out


def read_fund_table(data: bytes, filename: str) -> tuple[pd.DataFrame, dict[str, str | None]]:
    df, _ = read_table(data, filename)
    return df, _auto_map(list(df.columns))


def preview_fund_table(df: pd.DataFrame, mapping: dict[str, str | None], source: str = "import_csv",
                       document_id: int | None = None) -> list[FundPreview]:
    missing = [lbl for k, (lbl, req, _) in FUND_FIELDS.items() if req and not mapping.get(k)]
    if missing:
        raise ValueError("Pflichtspalten nicht zugeordnet: " + ", ".join(missing))
    col = {k: v for k, v in mapping.items() if v}
    num_fields = [k for k in ("fx_rate", "distribution_per_unit", "age_per_unit", "taxable_distribution_per_unit",
                              "creditable_tax_per_unit", "ak_correction_per_unit", "kest_per_unit") if k in col]
    dec = {k: detect_decimal_separator(df[col[k]].tolist()) for k in num_fields}
    cands = ["%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y"]
    dfmt = {k: detect_date_format(df[col[k]].tolist(), cands) for k in ("report_date", "fiscal_year_end",
                                                                        "distribution_date") if k in col}
    out = []
    for idx, rec in df.iterrows():
        row_no = int(idx) + 2
        errors, warnings = [], []
        vals: dict = {"source": source, "document_id": document_id}
        for k in ("isin", "fund_name", "report_type", "currency"):
            if k in col and str(rec[col[k]]).strip():
                vals[k] = str(rec[col[k]]).strip()
        for k, fmt in dfmt.items():
            try:
                vals[k] = parse_date(rec[col[k]], fmt, cands)
            except ValueError as exc:
                errors.append(str(exc))
        for k in num_fields:
            try:
                vals[k] = parse_number(rec[col[k]], dec[k])
            except ValueError as exc:
                errors.append(f"{FUND_FIELDS[k][0]}: {exc}")
        if "is_meldefonds" in col:
            v = str(rec[col["is_meldefonds"]]).strip().lower()
            vals["is_meldefonds"] = True if v in ("ja", "j", "yes", "y", "1", "true", "x") else \
                (False if v in ("nein", "n", "no", "0", "false") else None)
        if vals.get("isin") and not isin_checksum_ok(str(vals["isin"]).upper().replace(" ", "")):
            warnings.append("ISIN-Prüfziffer ungültig")
        if not any(vals.get(k) is not None for k in ("distribution_per_unit", "age_per_unit",
                                                     "ak_correction_per_unit")):
            warnings.append("Keine steuerlichen Werte (Ausschüttung/AgE/Korrekturbetrag) gefunden")
        rep = None
        if not errors:
            try:
                rep = FundReportIn(**vals)
            except ValidationError as exc:
                errors += [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        out.append(FundPreview(row_no, rep, errors, warnings))
    return out


def commit_fund_previews(repo: Repository, previews: list[FundPreview], document_id: int | None = None) -> dict:
    run = repo.start_import("OeKB-Fondsdaten", document_id)
    res = {"neu": 0, "identisch": 0, "konflikt": 0, "fehler": 0}
    for p in previews:
        if p.errors or p.report is None:
            res["fehler"] += 1
            repo.log_import(run, "FEHLER", "; ".join(p.errors), p.row_no)
            continue
        r = repo.add_fund_report(p.report)
        res[r["status"]] += 1
        if r["status"] == "konflikt":
            repo.log_import(run, "WARNUNG", f"Abweichung zu bestehender Meldung ({p.report.isin}) – Entscheidung "
                                            "im Bereich Fonds/OeKB erforderlich", p.row_no)
        for w in p.warnings:
            repo.log_import(run, "WARNUNG", w, p.row_no)
    repo.finish_import(run, "abgeschlossen" if not res["fehler"] else "mit Fehlern",
                       rows_total=len(previews), rows_imported=res["neu"] + res["konflikt"],
                       rows_duplicates=res["identisch"], rows_errors=res["fehler"],
                       message=str(res))
    return {"run_id": run, **res}


# --------------------------------------------------------------------------- #
PDF_LABELS = {
    "report_date": [r"Meldedatum", r"Zuflussdatum", r"Datum der Meldung", r"Meldezeitpunkt"],
    "fiscal_year_end": [r"Geschäftsjahresende", r"Ende des Geschäftsjahres", r"Geschäftsjahr endet"],
    "distribution_date": [r"Ex-Tag", r"Ausschüttungstag"],
    "distribution_per_unit": [r"Ausschüttung(?:\s+je\s+Anteil)?"],
    "age_per_unit": [r"Ausschüttungsgleiche Erträge(?:\s+je\s+Anteil)?", r"ausschüttungsgleicher Ertrag"],
    "creditable_tax_per_unit": [r"[Aa]nrechenbare (?:ausländische )?(?:Quellen)?[Ss]teuer"],
    "ak_correction_per_unit": [r"Korrekturbetrag[^\n]*?Anschaffungskosten", r"Korrekturbetrag"],
}


def extract_fund_pdf(data: bytes) -> dict:
    """Extrahiert Kandidatenwerte aus einem OeKB-PDF. Ergebnis immer „ungeprüft“ – Bestätigung in der Oberfläche."""
    text, engine = extract_text(data)
    found: dict = {"engine": engine, "values": {}, "missing": [], "warnings": [], "text_excerpt": text[:3000]}
    if not text.strip():
        found["warnings"].append("Kein Text extrahierbar – Werte manuell erfassen")
        return found
    isins = [i for i in ISIN_RX.findall(text) if isin_checksum_ok(i)]
    if isins:
        found["values"]["isin"] = isins[0]
        if len(set(isins)) > 1:
            found["warnings"].append("Mehrere ISIN im Dokument – Zuordnung prüfen")
    for key, labels in PDF_LABELS.items():
        for lbl in labels:
            if key.endswith("date") or key == "fiscal_year_end":
                m = re.search(rf"{lbl}[^\n\d]{{0,30}}({DATE})", text)
                if m and _date(m.group(1)):
                    found["values"][key] = _date(m.group(1)).isoformat()
                    break
            else:
                m = re.search(rf"{lbl}[^\n\d-]{{0,40}}({NUM})", text)
                if m and _num(m.group(1)) is not None:
                    found["values"][key] = _num(m.group(1))
                    break
    m = re.search(r"\b(EUR|USD|CHF|GBP|JPY)\b", text)
    if m:
        found["values"]["currency"] = m.group(1)
    for req in ("isin", "report_date"):
        if req not in found["values"]:
            found["missing"].append(FUND_FIELDS[req][0])
    if not any(k in found["values"] for k in ("distribution_per_unit", "age_per_unit", "ak_correction_per_unit")):
        found["missing"].append("steuerliche Werte je Anteil")
    found["warnings"].append("PDF-Werte sind heuristisch extrahiert und müssen gegen das Original geprüft werden")
    return found


def year_of(d: date | str | None) -> int | None:
    if d is None:
        return None
    return int(str(d)[:4])
