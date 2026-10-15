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


# --------------------------------------------------------------------------- #
# Prüfbericht / Sonderfälle
def _check(ex, name):
    return next((c for c in ex.checks if c["name"] == name), None)


def test_check_report_for_complete_document():
    ex = parse_text(TR_BUY)
    assert ex.complete
    assert _check(ex, "Endbetrag stimmt")["result"] == "ok"
    assert _check(ex, "Stück × Kurs = Kurswert")["result"] == "ok"
    assert all(c["result"] in ("ok", "info") for c in ex.checks)


def test_storno_is_never_auto_processed():
    ex = parse_text("STORNO\n" + TR_BUY)
    assert not ex.creates_transaction and not ex.complete
    c = _check(ex, "Dokumentart")
    assert c["result"] == "error" and "Ursprüngliche Buchung" in c["action"]


def test_corporate_action_and_info_documents():
    split = parse_text("Trade Republic\nAKTIENSPLIT\nApple Inc. ISIN: US0378331005\nVerhältnis 4:1\nDatum 31.08.2020")
    assert not split.creates_transaction and _check(split, "Dokumentart")["result"] == "error"
    info = parse_text("Kosteninformation (ex-ante)\nKauf Apple Inc. US0378331005 10 Stk. 150,00 EUR 1.500,00 EUR")
    assert info.doc_type == "Kosteninformation" and not info.creates_transaction
    vorab = parse_text("Vorabpauschale 2024\nIE00B4L5Y983\nDatum 02.01.2024")
    assert _check(vorab, "Dokumentart")["result"] == "info" and not vorab.creates_transaction


def test_german_withholding_taxes_are_flagged_not_taken_as_kest():
    text = TR_BUY.replace("Fremdkostenzuschlag -1,00 EUR", "Fremdkostenzuschlag -1,00 EUR\n"
                          "Kapitalertragsteuer -10,00 EUR\nSolidaritätszuschlag -0,55 EUR").replace("Kauf", "Verkauf")
    ex = parse_text(text)
    c = _check(ex, "Deutsche Steuer")
    assert c and c["result"] == "error" and "Ansässigkeit" in c["action"]
    assert ex.value("kest_at_eur") is None and not ex.complete


def test_reconciliation_and_plausibility_warnings():
    bad_total = TR_BUY.replace("GESAMT -498,40 EUR", "GESAMT -520,00 EUR")
    ex = parse_text(bad_total)
    assert _check(ex, "Endbetrag stimmt")["result"] == "warn"
    assert any("Endbetrag" in w for w in ex.warnings)
    future = TR_BUY.replace("Kauf am 03.12.2020", "Kauf am 03.12.2099")
    assert _check(parse_text(future), "Datum plausibel")["result"] == "error"
    wht = TR_DIV.replace("Quellensteuer für US-Emittent -0,13 USD", "Quellensteuer für US-Emittent -0,90 USD")
    assert _check(parse_text(wht), "Quellensteuer plausibel")["result"] == "error"


def test_dividend_reconciliation_with_fx():
    ex = parse_text(TR_DIV)
    c = _check(ex, "Endbetrag stimmt")
    assert c["result"] == "ok", c                         # (0,84 − 0,13) / 1,0821 ≈ 0,66 EUR


# --------------------------------------------------------------------------- #
# Zentraler Upload / automatische Depots / verständliche Meldungen
def _zip(files: dict[str, bytes]) -> bytes:
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return buf.getvalue()


def test_upload_zip_creates_depots_and_transactions(repo):
    from kest_tool.processing import expand_upload, store_uploads
    data = _zip({"TradeRepublic/Kauf.pdf": demo.tr_buy_pdf(), "../../boese.pdf": demo.tr_dividend_pdf(),
                 "Scalable/Verkauf.pdf": demo.sc_sell_pdf(), "notiz.exe": b"MZ", "oekb.csv": demo.SAMPLE_OEKB_CSV.encode(),
                 "Storno.pdf": _pdf_from_text("STORNO\n" + TR_BUY)})
    items = expand_upload("collector.zip", data)
    assert sorted(n for n, _ in items) == ["Kauf.pdf", "Storno.pdf", "Verkauf.pdf", "boese.pdf", "oekb.csv"]
    up = store_uploads(repo, items, 2024)
    assert len(up.pdf_ids) == 4 and up.csv_docs[0][1] is True              # OeKB-CSV erkannt
    res = {r.filename: r for r in process_documents(repo, up.pdf_ids)}
    assert res["Kauf.pdf"].status == "angelegt" and "automatisch angelegt" in res["Kauf.pdf"].message
    assert res["Verkauf.pdf"].status == "angelegt"
    assert res["Storno.pdf"].status == "pruefen" and "Ursprüngliche Buchung" in res["Storno.pdf"].action
    assert {d["name"] for d in repo.depots()} == {"Trade Republic Depot", "Scalable Capital Depot"}
    for p in repo.store.base.rglob("*"):
        assert p.resolve().is_relative_to(repo.store.base.resolve())


def test_incomplete_document_explains_what_to_do(repo):
    repo.add_depot(repo.add_broker("Trade Republic", "TradeRepublic"), "TR")
    doc, _ = repo.add_document(demo.incomplete_pdf(), "x.pdf", tax_year=2024)
    r = process_documents(repo, [doc["id"]])[0]
    assert r.status == "pruefen"
    assert "ISIN nicht im Dokument gefunden" in r.message
    assert "Prüfformular" in r.action


def test_info_document_is_filed_as_receipt(repo):
    doc, _ = repo.add_document(_pdf_from_text("Kosteninformation ex-ante\nKauf 10 Stk. Apple US0378331005"),
                               "kosten.pdf", tax_year=2024)
    r = process_documents(repo, [doc["id"]])[0]
    assert r.status == "beleg" and repo.document(doc["id"])["status"] == "verarbeitet"
    assert repo.transactions() == []


def test_bad_zip_message():
    from kest_tool.processing import expand_upload
    with pytest.raises(ValueError, match="kein gültiges ZIP"):
        expand_upload("x.zip", b"kein zip")


def test_issue_actions_are_attached(repo, depot):
    from kest_helpers import APPLE, add_tx, stock
    from kest_tool.models import TxType
    stock(repo)
    add_tx(repo, depot, TxType.SELL, "2024-05-01", isin=APPLE, quantity=5, amount=500)
    res = compute(repo, 2024)
    i = next(i for i in res.issues if "Anschaffungskosten unbekannt" in i.message)
    assert "importieren" in i.action and i.page == "import"
