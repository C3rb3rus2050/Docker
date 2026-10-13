"""PDF-Import mit synthetischen Muster-PDFs (keine echten Broker-Dokumente)."""

from __future__ import annotations

import pytest

from kest_helpers import ctx, depot, repo  # noqa: F401
from kest_tool import demo
from kest_tool.importers.oekb_importer import (
    NoAutomaticProvider,
    commit_fund_previews,
    extract_fund_pdf,
    get_provider,
    preview_fund_table,
    read_fund_table,
)
from kest_tool.importers.pdf_importer import PdfError, extract_pdf, parse_text
from kest_tool.models import TxType


def test_trade_republic_buy():
    ex = extract_pdf(demo.tr_buy_pdf())
    assert ex.broker == "TradeRepublic" and ex.doc_type == "Kaufabrechnung" and ex.tx_type == TxType.BUY.value
    assert ex.value("isin") == "US0378331005"
    assert ex.value("trade_date").isoformat() == "2024-03-15"
    assert ex.value("quantity") == 10
    assert ex.value("price") == pytest.approx(150.25)
    assert ex.value("amount") == pytest.approx(1502.50)
    assert ex.value("fees") == pytest.approx(1.0)
    assert ex.value("total") == pytest.approx(1503.50)
    assert ex.value("currency") == "EUR"
    assert ex.complete and ex.status == "vollstaendig", ex.warnings


def test_dividend_with_withholding():
    ex = extract_pdf(demo.tr_dividend_pdf())
    assert ex.tx_type == TxType.DIVIDEND.value
    assert ex.value("amount") == pytest.approx(2.40)
    assert ex.value("withholding_tax") == pytest.approx(0.36)
    assert ex.value("withholding_country") == "US"
    assert ex.value("trade_date").isoformat() == "2024-05-16"
    assert ex.complete


def test_scalable_sell():
    ex = extract_pdf(demo.sc_sell_pdf())
    assert ex.broker == "ScalableCapital" and ex.tx_type == TxType.SELL.value
    assert ex.value("quantity") == 20 and ex.value("amount") == pytest.approx(1900.0)
    assert ex.value("fees") == pytest.approx(0.99)
    assert ex.complete, ex.warnings


def test_incomplete_pdf_is_flagged():
    ex = extract_pdf(demo.incomplete_pdf())
    assert not ex.complete
    assert "ISIN" in ex.missing and "Stückzahl" in ex.missing
    assert ex.status == "unvollstaendig"


def test_tax_certificate_creates_no_transaction():
    ex = parse_text("Trade Republic\nJahressteuerbescheinigung 2024\nKapitalerträge 123,45 EUR")
    assert ex.doc_type == "Jahressteuerbescheinigung" and not ex.creates_transaction
    assert ex.status == "pruefen"


def test_inconsistent_values_warn():
    text = ("Wertpapierabrechnung Kauf\nAusführung 01.02.2024\nISIN: US0378331005 10 Stk. 100,00 EUR\n"
            "Kurswert 2.000,00 EUR\n")
    ex = parse_text(text)
    assert any("weicht" in w for w in ex.warnings)
    assert ex.status != "vollstaendig"


def test_non_pdf_rejected():
    with pytest.raises(PdfError):
        extract_pdf(b"<html>keine pdf</html>")


def test_empty_text_pdf_requires_manual():
    ex = parse_text("")
    assert not ex.complete and ex.missing == ["Text"]


def test_oekb_pdf_and_csv(repo):
    found = extract_fund_pdf(demo.oekb_pdf())
    v = found["values"]
    assert v["isin"] == "IE00B4L5Y983" and v["report_date"] == "2024-06-28"
    assert v["age_per_unit"] == pytest.approx(1.2345) and v["ak_correction_per_unit"] == pytest.approx(1.1)
    assert v["creditable_tax_per_unit"] == pytest.approx(0.0456)
    df, mapping = read_fund_table(demo.SAMPLE_OEKB_CSV.encode(), "oekb.csv")
    assert mapping["age_per_unit"] and mapping["report_date"] and mapping["ak_correction_per_unit"]
    prev = preview_fund_table(df, mapping)
    assert not prev[0].errors and prev[0].report.age_per_unit == pytest.approx(1.2345)
    r1 = commit_fund_previews(repo, prev)
    r2 = commit_fund_previews(repo, prev)
    assert r1["neu"] == 1 and r2["identisch"] == 1
    assert len(repo.fund_reports()) == 1


def test_automatic_oekb_provider_is_transparent():
    p = get_provider("irgendwas")
    assert isinstance(p, NoAutomaticProvider) and not p.available
    assert "nicht verifiziert" in p.reason
    with pytest.raises(RuntimeError):
        p.fetch("IE00B4L5Y983", 2024)
