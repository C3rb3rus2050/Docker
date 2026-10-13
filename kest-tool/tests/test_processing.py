"""Realitätsnahe Layouts, automatische Stapelverarbeitung und Statusübersicht."""

from __future__ import annotations

import io

import pytest

from kest_helpers import ctx, depot, repo  # noqa: F401
from kest_tool import demo
from kest_tool.importers.pdf_importer import parse_text
from kest_tool.processing import data_status, process_documents
from kest_tool.tax.engine import compute
from realistic_layouts import BAADER, TR_BUY, TR_DIV


def _pdf_from_text(text: str) -> bytes:
    return demo._pdf(text.splitlines())


def test_trade_republic_position_line_layout():
    ex = parse_text(TR_BUY)
    assert ex.complete, (ex.missing, ex.warnings)
    assert ex.value("trade_date").isoformat() == "2020-12-03"       # Ausführung, nicht Belegdatum
    assert ex.value("quantity") == 1 and ex.value("amount") == pytest.approx(497.40)
    assert ex.value("security_name") == "Tesla Inc." and ex.value("fees") == pytest.approx(1.0)


def test_trade_republic_dividend_foreign_currency():
    ex = parse_text(TR_DIV)
    assert ex.complete, (ex.missing, ex.warnings)
    assert ex.value("trade_date").isoformat() == "2024-02-15"       # Zahltag statt Ex-Tag
    assert ex.value("amount") == pytest.approx(0.84) and ex.value("currency") == "USD"
    assert ex.value("withholding_tax") == pytest.approx(0.13) and ex.value("withholding_country") == "US"
    assert ex.value("fx_rate") == pytest.approx(1.0821)


def test_baader_scalable_layout_currency_before_amount():
    ex = parse_text(BAADER)
    assert ex.complete, (ex.missing, ex.warnings)
    assert ex.value("quantity") == 2 and ex.value("price") == pytest.approx(63.15)
    assert ex.value("amount") == pytest.approx(126.30) and ex.value("fees") == pytest.approx(0.99)
    assert ex.value("total") == pytest.approx(127.29)


def test_batch_processing_creates_transactions_and_reports_open(repo):
    tr = repo.add_depot(repo.add_broker("Trade Republic", "TradeRepublic"), "TR")
    repo.add_depot(repo.add_broker("Scalable Capital", "ScalableCapital"), "SC")
    ids = []
    for name, data in [("kauf.pdf", demo.tr_buy_pdf()), ("div.pdf", demo.tr_dividend_pdf()),
                       ("sc.pdf", demo.sc_sell_pdf()), ("unvollstaendig.pdf", demo.incomplete_pdf())]:
        doc, _ = repo.add_document(data, name, source="Unclassified", tax_year=2024)
        ids.append(doc["id"])
    res = {r.filename: r for r in process_documents(repo, ids)}
    assert res["kauf.pdf"].status == "angelegt" and res["div.pdf"].status == "angelegt"
    assert res["sc.pdf"].status == "angelegt"
    assert res["unvollstaendig.pdf"].status == "pruefen" and "ISIN" in res["unvollstaendig.pdf"].message
    txs = repo.transactions(2024)
    assert {t["broker_name"] for t in txs} == {"Trade Republic", "Scalable Capital"}
    assert all(t["depot_id"] == tr for t in txs if t["broker_name"] == "Trade Republic")
    assert repo.document(ids[0])["status"] == "verarbeitet"
    assert repo.document(ids[3])["status"] == "pruefen"
    # zweiter Lauf: nichts doppelt
    again = process_documents(repo, ids)
    assert {r.status for r in again} <= {"uebersprungen", "pruefen"}
    assert len(repo.transactions(2024)) == 3
    # jetzt wird gerechnet
    result = compute(repo, 2024)
    assert result.summary["Dividenden"] == pytest.approx(2.40)
    st = data_status(repo, 2024)
    assert st["tx_year"] == 3 and len(st["docs_open"]) == 1


def test_batch_processing_needs_unique_depot(repo):
    b = repo.add_broker("Trade Republic", "TradeRepublic")
    d1 = repo.add_depot(b, "TR 1")
    repo.add_depot(b, "TR 2")
    doc, _ = repo.add_document(demo.tr_buy_pdf(), "kauf.pdf", tax_year=2024)
    r = process_documents(repo, [doc["id"]])[0]
    assert r.status == "pruefen" and "Depot nicht eindeutig" in r.message
    r = process_documents(repo, [doc["id"]], default_depot=d1)[0]
    assert r.status == "angelegt"


def test_existing_transaction_is_linked_not_duplicated(repo, depot):
    doc, _ = repo.add_document(demo.tr_buy_pdf(), "kauf.pdf", tax_year=2024)
    first = process_documents(repo, [doc["id"]], default_depot=depot)[0]
    assert first.status == "angelegt"
    doc2, _ = repo.add_document(_pdf_from_text(TR_BUY.replace("Max Mustermann", "Kopie")), "kopie.pdf",
                                tax_year=2020)
    tx_buy = process_documents(repo, [doc2["id"]], default_depot=depot)[0]
    assert tx_buy.status == "angelegt"
    doc3, _ = repo.add_document(_pdf_from_text(TR_BUY.replace("Max Mustermann", "Zweitschrift")), "zweit.pdf",
                                tax_year=2020)
    dup = process_documents(repo, [doc3["id"]], default_depot=depot)[0]
    assert dup.status == "dublette"
    assert len(repo.transactions()) == 2
