"""Synthetische Beispieldaten (keine echten Finanzdaten).

``python -m kest_tool.demo <Zielordner>`` erzeugt eine Demo-Ablage mit Beispielbuchungen, Muster-PDFs und
einer Fondsmeldung. Alle Werte sind frei erfunden und als MUSTER gekennzeichnet.
"""

from __future__ import annotations

import io
import sys
from datetime import date
from pathlib import Path


def _pdf(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("MUSTER")
    y = 800
    for line in lines:
        c.drawString(50, y, line)
        y -= 16
    c.showPage()
    c.save()
    return buf.getvalue()


def tr_buy_pdf() -> bytes:
    return _pdf([
        "Trade Republic Bank GmbH  -  MUSTER / Beispieldokument ohne echte Daten",
        "WERTPAPIERABRECHNUNG",
        "Kauf am 15.03.2024 an der Lang & Schwarz Exchange.",
        "Ausführung 15.03.2024",
        "POSITION ANZAHL PREIS BETRAG",
        "Apple Inc. Registered Shares o.N.",
        "ISIN: US0378331005 10 Stk. 150,25 EUR 1.502,50 EUR",
        "Kurswert 1.502,50 EUR",
        "Fremdkostenzuschlag -1,00 EUR",
        "GESAMT -1.503,50 EUR",
    ])


def tr_dividend_pdf() -> bytes:
    return _pdf([
        "Trade Republic Bank GmbH  -  MUSTER / Beispieldokument ohne echte Daten",
        "DIVIDENDE",
        "Zahltag 16.05.2024",
        "Apple Inc. Registered Shares o.N.",
        "ISIN: US0378331005 10 Stk.",
        "Bruttobetrag 2,40 EUR",
        "Quellensteuer USA -0,36 EUR",
        "Gutschrift 2,04 EUR",
    ])


def sc_sell_pdf() -> bytes:
    return _pdf([
        "Scalable Capital GmbH / Baader Bank  -  MUSTER / Beispieldokument ohne echte Daten",
        "Wertpapierabrechnung Verkauf",
        "Schlusstag 02.09.2024",
        "iShares Core MSCI World UCITS ETF",
        "ISIN IE00B4L5Y983",
        "Stück 20",
        "Kurs 95,00 EUR",
        "Kurswert 1.900,00 EUR",
        "Ordergebühr -0,99 EUR",
        "Endbetrag 1.899,01 EUR",
    ])


def incomplete_pdf() -> bytes:
    return _pdf([
        "MUSTER Bank AG",
        "Wertpapierabrechnung Kauf",
        "Datum 05.06.2024",
        "Irgendein Wertpapier ohne Kennnummer",
        "Kurswert 250,00 EUR",
    ])


def oekb_pdf() -> bytes:
    return _pdf([
        "Oesterreichische Kontrollbank AG - Steuerliche Behandlung (MUSTER, frei erfunden)",
        "ISIN IE00B4L5Y983  iShares Core MSCI World UCITS ETF",
        "Geschäftsjahresende 31.03.2024",
        "Meldedatum 28.06.2024",
        "Ausschüttung je Anteil 0,0000",
        "Ausschüttungsgleiche Erträge je Anteil 1,2345",
        "Anrechenbare ausländische Quellensteuer 0,0456",
        "Korrekturbetrag Anschaffungskosten 1,1000",
        "Währung EUR",
    ])


SAMPLE_CSV = (
    "Datum;Typ;ISIN;Wertpapier;Stück;Kurs;Betrag;Gebühren;Währung;Quellensteuer;Land\n"
    "10.01.2024;Kauf;IE00B4L5Y983;iShares Core MSCI World (MUSTER);20;80,00;1.600,00;1,00;EUR;;\n"
    "15.03.2024;Kauf;US0378331005;Apple Inc. (MUSTER);10;150,25;1.502,50;1,00;EUR;;\n"
    "16.05.2024;Dividende;US0378331005;Apple Inc. (MUSTER);;;2,40;;EUR;0,36;US\n"
    "30.06.2024;Zinsen;;Zinsen Verrechnungskonto (MUSTER);;;12,34;;EUR;;\n"
    "02.09.2024;Verkauf;US0378331005;Apple Inc. (MUSTER);5;140,00;700,00;1,00;EUR;;\n"
)

SAMPLE_OEKB_CSV = (
    "ISIN;Fondsname;Meldungsart;Geschäftsjahresende;Meldedatum;Währung;Ausschüttung je Anteil;"
    "Ausschüttungsgleiche Erträge;Anrechenbare Quellensteuer;Korrekturbetrag Anschaffungskosten;Meldefonds\n"
    "IE00B4L5Y983;iShares Core MSCI World (MUSTER);Jahresmeldung;31.03.2024;28.06.2024;EUR;0;1,2345;0,0456;1,1;ja\n"
)


def write_sample_files(folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    files = {
        "MUSTER_TradeRepublic_Kauf.pdf": tr_buy_pdf(),
        "MUSTER_TradeRepublic_Dividende.pdf": tr_dividend_pdf(),
        "MUSTER_Scalable_Verkauf.pdf": sc_sell_pdf(),
        "MUSTER_unvollstaendig.pdf": incomplete_pdf(),
        "MUSTER_OeKB_Meldung.pdf": oekb_pdf(),
        "MUSTER_Transaktionen.csv": SAMPLE_CSV.encode("utf-8"),
        "MUSTER_OeKB_Fondsdaten.csv": SAMPLE_OEKB_CSV.encode("utf-8"),
    }
    out = []
    for name, data in files.items():
        p = folder / name
        p.write_bytes(data)
        out.append(p)
    return out


def build_demo(base_dir: Path) -> None:
    """Legt eine vollständige Demo-Ablage an (eigener Ordner, nicht die echte Ablage)."""
    from .config import load_settings
    from .context import create_context
    from .importers.csv_importer import ImportOptions, auto_mapping, build_preview, commit_preview, read_table
    from .importers.oekb_importer import commit_fund_previews, preview_fund_table, read_fund_table
    from .models import FundStatus, SecurityIn, SecurityType, TaxClass

    ctx = create_context(load_settings(), base_dir=base_dir)
    repo = ctx.repo
    b = repo.add_broker("Trade Republic", "TradeRepublic", "DE", notes="MUSTER")
    d = repo.add_depot(b, "TR Depot (MUSTER)")
    repo.add_depot(repo.add_broker("Scalable Capital", "ScalableCapital", "DE"), "Scalable Depot (MUSTER)")
    repo.set_depot_tax_settings(d, 2024, "nein", "nein", source="MUSTER-Annahme")
    repo.upsert_security(SecurityIn(isin="US0378331005", name="Apple Inc. (MUSTER)", country="US",
                                    security_type=SecurityType.STOCK, tax_class=TaxClass.KAPITALGESELLSCHAFT))
    repo.upsert_security(SecurityIn(isin="IE00B4L5Y983", name="iShares Core MSCI World (MUSTER)", country="IE",
                                    security_type=SecurityType.ETF_ACC, tax_class=TaxClass.INVESTMENTFONDS,
                                    fund_status=FundStatus.MELDEFONDS))
    data = SAMPLE_CSV.encode()
    doc, _ = repo.add_document(data, "MUSTER_Transaktionen.csv", doc_type="Transaktionsexport (CSV)",
                               source="TradeRepublic", tax_year=2024, broker_id=b)
    df, _ = read_table(data, "MUSTER_Transaktionen.csv")
    rows = build_preview(df, auto_mapping(list(df.columns)), ImportOptions(), d, repo)
    commit_preview(repo, rows, {}, import_type="CSV", depot_id=d, document_id=doc["id"])
    odata = SAMPLE_OEKB_CSV.encode()
    odoc, _ = repo.add_document(odata, "MUSTER_OeKB_Fondsdaten.csv", doc_type="OeKB-Fondsmeldung", source="OeKB",
                                tax_year=2024)
    fdf, fmap = read_fund_table(odata, "MUSTER_OeKB_Fondsdaten.csv")
    commit_fund_previews(repo, preview_fund_table(fdf, fmap, document_id=odoc["id"]), odoc["id"])
    write_sample_files(base_dir / "Beispieldateien")
    ctx.close()


if __name__ == "__main__":  # pragma: no cover
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "KESt-Tool-Demo").resolve()
    build_demo(target)
    print(f"Demo-Ablage erstellt: {target} (Stand {date.today()})")
