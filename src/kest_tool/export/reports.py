"""CSV-Exporte, PDF-Jahresbericht und E 1kv-Arbeitshilfe."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from ..repository import Repository
from ..storage import DocumentStore, sha256_file
from ..tax.engine import MANUAL, STATUS_TEXT, TaxResult
from ..tax.rules import TaxRules, load_rules


def _write_csv(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".part")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
        if not rows:
            fh.write("Keine Einträge\n")
        else:
            cols = list(dict.fromkeys(k for r in rows for k in r))
            w = csv.DictWriter(fh, fieldnames=cols, delimiter=";")
            w.writeheader()
            for r in rows:
                w.writerow({k: _fmt(r.get(k)) for k in cols})
    tmp.replace(path)


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.6f}".rstrip("0").rstrip(".").replace(".", ",")
    if isinstance(v, (list, tuple)):
        return "; ".join(map(str, v))
    return v


def export_csv(repo: Repository, store: DocumentStore, res: TaxResult, today: date | None = None) -> list[Path]:
    """CSV-Dateien (Semikolon, UTF-8 mit BOM, Dezimalkomma) für Excel-Kompatibilität."""
    today = today or date.today()
    d = store.export_dir(res.tax_year, "csv")
    stamp = f"{res.tax_year}_{today.isoformat()}"
    files = {
        f"Transaktionen_{stamp}.csv": [dict(t) for t in repo.transactions(res.tax_year)],
        f"Steuerpositionen_{stamp}.csv": [{
            "Position": l.line_id, "Datum": l.date, "Kategorie": l.category, "Steuergruppe": l.bucket,
            "Depot": l.depot, "ISIN": l.isin, "Name": l.name, "Ausgangsbetrag": l.gross, "Ansatz": l.amount,
            "Verlustausgleich": l.offset_amount, "Satz": l.rate, "Quellensteuer": l.withholding_tax,
            "anrechenbar": l.creditable_tax_max, "Regeln": ", ".join(l.rule_ids), "Status": STATUS_TEXT[l.status],
            "Schritte": " | ".join(l.steps), "Quellen": " | ".join(l.sources), "Hinweise": " | ".join(l.notes),
        } for l in res.lines],
        f"E1kv_{stamp}.csv": res.e1kv,
        f"Pruefprotokoll_{stamp}.csv": [i.__dict__ for i in res.issues],
    }
    out = []
    for name, rows in files.items():
        p = store.unique_target(d, name)
        _write_csv(p, rows)
        repo.record_export(res.tax_year, "csv", p, sha256_file(p))
        out.append(p)
    return out


def export_e1kv_helper(repo: Repository, store: DocumentStore, res: TaxResult, rules: TaxRules | None = None,
                       today: date | None = None) -> Path:
    """Textbasierte Übertragungshilfe (keine offizielle Einreichung)."""
    rules = rules or load_rules()
    today = today or date.today()
    spec = rules.e1kv(res.tax_year)
    lines = [
        f"E 1kv-ÜBERTRAGUNGSHILFE {res.tax_year}  –  erstellt {datetime.now():%d.%m.%Y %H:%M}",
        "=" * 78,
        "ARBEITSHILFE – KEINE OFFIZIELLE EINREICHUNG. Werte manuell in FinanzOnline übernehmen,",
        "vorher mit Belegen und dem amtlichen Formular des Steuerjahres abgleichen.",
        f"Formulargrundlage: {spec.get('form')}",
        "",
        f"{'KZ':<8}{'Betrag EUR':>14}  {'Kennzahl-Status':<26}Bezeichnung",
        "-" * 78,
    ]
    for r in res.e1kv:
        lines.append(f"{r['Kennzahl']:<8}{r['Betrag EUR']:>14,.2f}  {r['Kennzahl-Status']:<26}{r['Bezeichnung']}")
        lines.append(f"{'':8}Betrag: {r['Betrags-Status']}")
        if r["Hinweise"]:
            lines.append(f"{'':8}Hinweis: {r['Hinweise']}")
    lines += ["", "Hinweise zum Formular:"] + [f"  - {n}" for n in spec.get("notes", [])]
    manual = [l for l in res.lines if l.status == MANUAL]
    lines += ["", f"MANUELL ZU PRÜFEN ({len(manual)} Positionen, NICHT in obigen Beträgen enthalten):"]
    lines += [f"  - {l.line_id} {l.category} {l.isin or ''} {l.gross if l.gross is not None else ''}: "
              f"{'; '.join(l.notes)}" for l in manual]
    errs = [i for i in res.issues if i.severity in ("Fehler", "Warnung")]
    lines += ["", f"OFFENE PUNKTE ({len(errs)}):"] + [f"  - [{i.severity}] {i.message}" for i in errs]
    d = store.export_dir(res.tax_year, "e1kv")
    p = store.unique_target(d, f"E1kv_Uebertragungshilfe_{res.tax_year}_{today.isoformat()}.txt")
    p.write_text("\n".join(lines), encoding="utf-8")
    repo.record_export(res.tax_year, "e1kv", p, sha256_file(p))
    return p


def export_pdf_report(repo: Repository, store: DocumentStore, res: TaxResult, rules: TaxRules | None = None,
                      today: date | None = None) -> Path:
    """PDF-Jahresbericht (reportlab). Wird unter exports/<Jahr>/pdf und als Kopie unter reports/<Jahr> abgelegt."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    rules = rules or load_rules()
    today = today or date.today()
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=7.5, leading=9)
    d = store.export_dir(res.tax_year, "pdf")
    p = store.unique_target(d, f"KESt_Jahresbericht_{res.tax_year}_{today.isoformat()}.pdf")

    def eur(v):
        if v is None:
            return "–"
        return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")

    def table(data, widths=None):
        t = Table([[Paragraph(str(c) if c is not None else "", small) for c in row] for row in data],
                  colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    story = [Paragraph(f"KESt-Jahresbericht {res.tax_year}", styles["Title"]),
             Paragraph(f"Erstellt am {datetime.now():%d.%m.%Y %H:%M}. Arbeitshilfe zur Vorbereitung der "
                       "Einkommensteuererklärung – ersetzt keine Steuerberatung. Positionen mit Status „vorläufig“ "
                       "oder „manuell prüfen“ sind nicht abschließend geprüft.", styles["BodyText"]),
             Spacer(1, 4 * mm), Paragraph("Zusammenfassung", styles["Heading2"])]
    data = [["Kennzahl", "Gesamt (inkl. vorläufig)", "davon gesichert"]]
    for k, v in res.summary.items():
        c = res.summary_confirmed.get(k)
        if k.startswith("Positionen"):
            data.append([k, str(v), str(c)])
        else:
            data.append([k, eur(v), eur(c)])
    story += [table(data, [110 * mm, 45 * mm, 45 * mm]), PageBreak(),
              Paragraph("E 1kv-Übertragungshilfe", styles["Heading2"]),
              Paragraph(rules.e1kv(res.tax_year).get("form", ""), styles["BodyText"])]
    data = [["KZ", "Bezeichnung", "Betrag", "Kennzahl-Status", "Betrags-Status"]]
    data += [[r["Kennzahl"], r["Bezeichnung"], eur(r["Betrag EUR"]), r["Kennzahl-Status"], r["Betrags-Status"]]
             for r in res.e1kv]
    story += [table(data, [16 * mm, 80 * mm, 25 * mm, 30 * mm, 45 * mm]), PageBreak(),
              Paragraph("Rechenpositionen", styles["Heading2"])]
    data = [["Position", "Datum", "Kategorie", "ISIN", "Ansatz", "Status", "Rechenschritte"]]
    for l in res.lines:
        data.append([l.line_id, l.date, l.category, l.isin or "", eur(l.amount), STATUS_TEXT[l.status],
                     " | ".join(l.steps)[:600]])
    story += [table(data, [24 * mm, 18 * mm, 32 * mm, 24 * mm, 20 * mm, 30 * mm, 120 * mm]), PageBreak(),
              Paragraph("Verlustausgleich", styles["Heading2"])]
    data = [["Verlust", "Kategorie", "Betrag", "verrechnet", "verfällt", "Begründung"]]
    data += [[r.loss_line, r.category, eur(r.original_loss), eur(r.offset_total), eur(r.remaining),
              "; ".join(r.reasons)] for r in res.loss_offsets]
    story += [table(data, [24 * mm, 26 * mm, 22 * mm, 22 * mm, 22 * mm, 150 * mm]),
              Paragraph("Prüfprotokoll", styles["Heading2"])]
    data = [["Schweregrad", "Art", "Meldung"]] + [[i.severity, i.kind, i.message] for i in res.issues]
    story += [table(data, [22 * mm, 36 * mm, 210 * mm]), PageBreak(),
              Paragraph("Angewendete Regeln", styles["Heading2"])]
    data = [["Regel", "Rechtsgrundlage", "Status", "Quellen"]]
    data += [[r["Regel-ID"] + ": " + r["Titel"], r["Rechtsgrundlage"], r["Status"], r["Quellen"]]
             for r in res.rules_used]
    story.append(table(data, [80 * mm, 45 * mm, 40 * mm, 103 * mm]))
    tmp = p.with_suffix(".part")
    SimpleDocTemplate(str(tmp), pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                      topMargin=12 * mm, bottomMargin=12 * mm, title=f"KESt-Jahresbericht {res.tax_year}").build(story)
    tmp.replace(p)
    repo.record_export(res.tax_year, "pdf", p, sha256_file(p))
    copy = store.unique_target(store.report_dir(res.tax_year), p.name)
    copy.write_bytes(p.read_bytes())
    return p
