"""Document variants, currency provenance and safe fallbacks (synthetic examples)."""
from datetime import date
import json

import pytest

from kest_helpers import ctx, depot, repo  # noqa: F401
from kest_tool import demo
from kest_tool.fx import FxError, FxService, parse_ecb_csv
from kest_tool.importers.pdf_importer import PdfError, extract_pdf, parse_text
from kest_tool.processing import extraction_for, process_documents

BUY = """Trade Republic
Wertpapierabrechnung Kauf
Ausführungsdatum: 15.03.2024
Wertpapierbezeichnung: Apple Inc.
ISIN: US0378331005
Stückzahl: 10
Kurs: 150,25 EUR
Kurswert: 1.502,50 EUR
Provision: 1,00 EUR
Gesamt: 1.503,50 EUR
Valuta: 18.03.2024
"""
DIV = """Trade Republic
Cash Dividend
Payment Date: 15/03/2024
Security Name: Apple Inc.
ISIN: US0378331005
Gross Amount: 110.00 USD
Withholding Tax: 16.50 USD
Withholding Country: US
Net Amount: 85.00 EUR
"""


def test_wrapped_labels_names_settlement_and_us_numbers():
    text = BUY.replace("Ausführungsdatum: ", "Ausführungsdatum:\n").replace("ISIN: ", "ISIN:\n")
    text = text.replace("Kurswert: 1.502,50 EUR", "Kurswert:\nEUR\n1,502.50")
    ex = parse_text(text)
    assert ex.complete, ex.warnings
    assert ex.value("amount") == 1502.50
    assert ex.value("security_name") == "Apple Inc."
    assert ex.value("trade_date") == date(2024, 3, 15)
    assert ex.value("value_date") == date(2024, 3, 18)


@pytest.mark.parametrize("quote,expected", [
    ("1 EUR = 1.10 USD", 1.1),
    ("1 USD = 0.909090909 EUR", 1.1),
    ("Devisenkurs EUR/USD: 1,10", 1.1),
    ("Devisenkurs USD/EUR: 0,909090909", 1.1),
    ("1.100000 EUR/USD", 1.1),
])
def test_currency_quotes_are_normalized(quote, expected):
    ex = parse_text(DIV + quote)
    assert ex.value("fx_rate") == pytest.approx(expected)
    assert ex.value("amount_eur") == pytest.approx(100)
    assert ex.complete, ex.warnings


def test_unoriented_or_conflicting_rates_need_review():
    for quote in ["Devisenkurs 1,10", "1 EUR = 1.10 USD\n1 EUR = 1.20 USD"]:
        ex = parse_text(DIV + quote)
        assert not ex.complete
        assert any("Devisenkurs" in c["name"] and c["result"] == "warn" for c in ex.checks)


def test_mixed_fee_and_withholding_currencies():
    ex = parse_text(DIV.replace("16.50 USD", "15.00 EUR").replace("85.00 EUR", "83.00 EUR")
                    + "\nFees: 2.00 EUR\n1 EUR = 1.10 USD")
    assert ex.value("withholding_tax") == pytest.approx(16.5)
    assert ex.value("fees") == pytest.approx(2.2)
    assert "15 EUR" in ex.value("withholding_tax_original")
    assert ex.complete, ex.warnings


def test_mixed_amounts_without_fx_are_not_summed_as_same_currency():
    ex = parse_text(DIV + "\nFees 2.00 EUR")
    assert ex.value("fees") is None
    assert not ex.complete
    assert any("umgerechnet" in w for w in ex.warnings)


def test_missing_currency_or_conflicting_gross_is_never_complete():
    ex = parse_text(BUY.replace(" EUR", ""))
    assert not ex.complete
    ex = parse_text(BUY + "\nKurswert 1.600,00 EUR")
    assert not ex.complete
    assert any("Bruttobetrag eindeutig" == c["name"] for c in ex.checks)


def test_calculated_missing_quantity_is_only_a_review_proposal():
    ex = parse_text(BUY.replace("Stückzahl: 10\n", ""))
    assert ex.value("quantity") == pytest.approx(10)
    assert ex.fields["quantity"].confidence < .8
    assert not ex.complete


def test_per_unit_income_can_be_reconstructed_for_review():
    ex = parse_text(DIV.replace("Gross Amount: 110.00 USD", "Quantity 10\nDividend per Share 11.00 USD"))
    assert ex.value("amount") == pytest.approx(110)
    assert not ex.complete


def test_trade_title_beats_income_in_footnote():
    ex = parse_text(BUY + "Hinweis: Dividende wird separat abgerechnet.")
    assert ex.tx_type == "Kauf"


def test_reference_fx_is_saved_with_date_source_and_value_date(repo, depot, ctx):
    service = FxService(ctx.store.base)
    service.import_bytes(b"Date,USD,\n2024-03-15,1.10,\n")
    doc, _ = repo.add_document(demo._pdf((DIV + "\nSettlement Date 18/03/2024").splitlines()), "div.pdf", tax_year=2024)
    result = process_documents(repo, [doc["id"]], default_depot=depot, fx_service=service)[0]
    assert result.status == "angelegt", result
    tx = repo.transaction(result.transaction_id)
    assert tx["amount_eur"] == pytest.approx(100)
    assert tx["value_date"] == "2024-03-18"
    assert "EZB-Referenzkurs" in tx["fx_source"] and "2024-03-15" in tx["fx_source"]
    assert "eurofxref-hist.zip" in tx["fx_source"]
    cached = json.loads(repo.document(doc["id"])["extraction_json"])
    assert any(c["name"] == "Online-Umrechnung" for c in cached["checks"])


def test_document_rate_prevents_any_web_access(ctx, monkeypatch):
    svc = FxService(ctx.store.base)
    def unexpected(**kwargs):
        raise AssertionError("must not fetch a reference rate for a document rate")
    monkeypatch.setattr(svc, "rates", unexpected)
    ex = extract_pdf(demo._pdf((DIV + "1 EUR = 1.10 USD").splitlines()), fx_service=svc, allow_download=True)
    assert "Belegkurs" in ex.value("fx_source")


def test_cache_upgrades_and_network_failure_preserves_original_fields(repo, ctx, monkeypatch):
    doc, _ = repo.add_document(demo._pdf(DIV.splitlines()), "div.pdf", tax_year=2024)
    repo.update_document(doc["id"], extraction_json=json.dumps({"fields": {}, "missing": ["old"]}))
    svc = FxService(ctx.store.base)
    def offline(**kwargs):
        raise FxError("offline")
    monkeypatch.setattr(svc, "rates", offline)
    ex = extraction_for(repo, repo.document(doc["id"]), fx_service=svc, allow_download=True)
    assert ex["fields"]["amount"]["value"] == pytest.approx(110)
    assert ex["parser_version"] >= 2
    assert any(c["detail"] == "offline" for c in ex["checks"])


def test_local_ocr_results_always_require_review(monkeypatch):
    import kest_tool.importers.pdf_importer as parser
    monkeypatch.setattr(parser, "extract_text", lambda *args: ("", "keine"))
    monkeypatch.setattr(parser, "_ocr_text", lambda data: BUY)
    ex = parser.extract_pdf(b"%PDF-scan", ocr_enabled=True)
    assert ex.value("isin") == "US0378331005"
    assert ex.engine == "Tesseract (lokal)"
    assert not ex.complete and ex.warnings


def test_oversized_pdf_is_not_silently_partially_processed():
    import pymupdf
    doc = pymupdf.open()
    for _ in range(31):
        doc.new_page()
    with pytest.raises(PdfError, match="30 Seiten"):
        extract_pdf(doc.tobytes())
    doc.close()


def test_non_finite_exchange_rates_are_rejected():
    rates = parse_ecb_csv("Date,USD,CHF,\n2024-03-15,inf,0.9,\n")
    assert rates.lookup("USD", date(2024, 3, 15)) is None


def test_fee_summary_is_not_added_to_its_components():
    text = BUY.replace("Provision: 1,00 EUR", "Provision: 0,60 EUR\nSpesen: 0,40 EUR\nGebühren gesamt: 1,00 EUR")
    ex = parse_text(text)
    assert ex.value("fees") == pytest.approx(1)
    assert ex.complete, ex.warnings


def test_mixed_document_never_guesses_unlabeled_fee_currency():
    ex = parse_text(DIV + "\nFees: 2.00\n1 EUR = 1.10 USD")
    assert ex.value("fees") is None
    assert not ex.complete


def test_failed_download_is_not_repeated_for_every_document(ctx, monkeypatch):
    svc = FxService(ctx.store.base)
    calls = []
    def unavailable():
        calls.append(1)
        raise FxError("offline")
    monkeypatch.setattr(svc, "download", unavailable)
    with pytest.raises(FxError):
        svc.rates(allow_download=True)
    assert svc.rates(allow_download=True) is None
    assert len(calls) == 1


def test_fractional_shares_with_dot_are_not_thousands():
    ex = parse_text(BUY.replace("Stückzahl: 10", "Stückzahl: 0.125").replace("150,25 EUR", "100.00 EUR")
                    .replace("1.502,50 EUR", "12.50 EUR").replace("1.503,50 EUR", "13.50 EUR"))
    assert ex.value("quantity") == pytest.approx(.125)
    assert ex.complete, ex.warnings


def test_tesseract_reads_scan():
    import shutil
    import pymupdf
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract is supplied in the Docker image")
    original = pymupdf.open(stream=demo._pdf(BUY.splitlines()), filetype="pdf")
    scan = pymupdf.open()
    try:
        page = original[0]
        image = page.get_pixmap(dpi=200)
        scan.new_page(width=page.rect.width, height=page.rect.height).insert_image(page.rect, stream=image.tobytes("png"))
        ex = extract_pdf(scan.tobytes(), ocr_enabled=True)
        assert ex.engine == "Tesseract (lokal)", ex.warnings
        assert ex.value("amount") == pytest.approx(1502.50)
        assert ex.value("isin") == "US0378331005"
        assert not ex.complete
    finally:
        scan.close()
        original.close()
