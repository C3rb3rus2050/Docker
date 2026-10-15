"""Regression tests for safe and repeatable document processing."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from kest_helpers import ctx, depot, repo  # noqa: F401
from kest_tool import demo
from kest_tool.importers.pdf_importer import PdfError, extract_pdf
from kest_tool.processing import (
    expand_upload, extraction_for, process_documents, resolve_depot, store_pdf, store_uploads,
    transaction_from_extraction,
)


def _zip(items: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in items.items():
            archive.writestr(name, data)
    return output.getvalue()


def test_zip_with_subfolders_and_nested_zip():
    inside = _zip({"nested/abrechnung.pdf": b"%PDF-test", "ignored.exe": b"binary"})
    contents = _zip({"archive.zip": inside, "data/oekb.csv": b"isin,meldedatum\n"})
    assert sorted(expand_upload("sammlung.zip", contents)) == [
        ("abrechnung.pdf", b"%PDF-test"), ("oekb.csv", b"isin,meldedatum\n")
    ]


def test_nested_zip_depth_limit():
    inside = _zip({"test.pdf": b"%PDF-test"})
    for _ in range(3):
        inside = _zip({"inner.zip": inside})
    with pytest.raises(ValueError, match="ZIP-Ebenen"):
        expand_upload("files.zip", inside)


def test_zip_size_limit_without_large_allocation(monkeypatch):
    import kest_tool.processing as processing
    monkeypatch.setattr(processing, "MAX_ZIP_TOTAL", 8)
    with pytest.raises(ValueError, match="500 MB"):
        expand_upload("files.zip", _zip({"big.pdf": b"%PDF-oversize"}))


def test_duplicate_pdf_is_not_queued_twice(repo):
    payload = demo.tr_buy_pdf()
    one = store_uploads(repo, [("rechnung.pdf", payload)], 2024)
    two = store_uploads(repo, [("rechnung-kopie.pdf", payload)], 2024)
    assert len(one.pdf_ids) == 1
    assert two.pdf_ids == [] and two.duplicates == 1


def test_reuses_stored_extraction_without_reparsing(repo, depot, monkeypatch):
    doc, original, new = store_pdf(repo, demo.tr_buy_pdf(), "buy.pdf", 2024, "test")
    assert new and original["complete"]
    def fail(_data, *_args, **_kwargs):
        raise AssertionError("cached PDF was unnecessarily re-parsed")
    monkeypatch.setattr("kest_tool.processing.extract_pdf", fail)
    result = process_documents(repo, [doc["id"]], default_depot=depot)
    assert result[0].status == "angelegt"


def test_explicit_refresh_preserves_previous_cache_on_failure(repo, depot, monkeypatch):
    doc, _, _ = store_pdf(repo, demo.tr_buy_pdf(), "buy.pdf", 2024, "test")
    old_cache = repo.document(doc["id"])["extraction_json"]
    def bad(_data, *_args, **_kwargs):
        raise PdfError("broken PDF")
    monkeypatch.setattr("kest_tool.processing.extract_pdf", bad)
    result = process_documents(repo, [doc["id"]], default_depot=depot, reextract=True)
    assert result[0].status == "fehler"
    assert repo.document(doc["id"])["extraction_json"] == old_cache


def test_invalid_extraction_json_can_be_rebuilt(repo):
    doc, _ = repo.add_document(demo.tr_buy_pdf(), "buy.pdf", tax_year=2024)
    repo.update_document(doc["id"], extraction_json="{invalid json")
    extracted = extraction_for(repo, repo.document(doc["id"]))
    assert extracted["complete"]
    assert json.loads(repo.document(doc["id"])["extraction_json"])["complete"]


def test_default_depot_cannot_cross_known_broker(repo):
    broker = repo.add_broker("Scalable Capital", "ScalableCapital")
    wrong_depot = repo.add_depot(broker, "SC")
    assert resolve_depot(repo, {"broker_id": None, "source": "Unclassified"}, "TradeRepublic",
                         wrong_depot) is None
    assert resolve_depot(repo, {"broker_id": None, "source": "Unclassified"}, "Unclassified",
                         wrong_depot) == wrong_depot


def test_ambiguous_depot_is_marked_for_review(repo):
    broker = repo.add_broker("Trade Republic", "TradeRepublic")
    repo.add_depot(broker, "TR 1")
    repo.add_depot(broker, "TR 2")
    doc, _ = repo.add_document(demo.tr_buy_pdf(), "kauf.pdf", tax_year=2024)
    result = process_documents(repo, [doc["id"]])[0]
    assert result.status == "pruefen"
    assert repo.document(doc["id"])["status"] == "pruefen"
    assert repo.transactions() == []


def test_possible_duplicate_is_not_entered_into_tax_calculation(repo, depot):
    data = demo.tr_buy_pdf()
    doc, _ = repo.add_document(data, "kauf.pdf", tax_year=2024)
    ex = extract_pdf(data).to_dict()
    tx = transaction_from_extraction(ex, depot, doc)
    earlier = tx.model_copy(update={"amount": tx.amount + 0.02, "document_id": None})
    repo.add_transaction(earlier)
    result = process_documents(repo, [doc["id"]], default_depot=depot)[0]
    assert result.status == "pruefen"
    assert repo.document(doc["id"])["status"] == "pruefen"
    assert len(repo.transactions()) == 1
    assert repo.transactions_for_document(doc["id"]) == []


def test_unexpected_document_error_does_not_stop_batch(repo, depot, monkeypatch):
    import kest_tool.processing as processing
    first_bytes, second_bytes = demo.tr_buy_pdf(), demo.tr_dividend_pdf()
    first, _ = repo.add_document(first_bytes, "broken.pdf", tax_year=2024)
    second, _ = repo.add_document(second_bytes, "valid.pdf", tax_year=2024)
    extract = processing.extract_pdf

    def flaky(data, *args, **kwargs):
        if data == first_bytes:
            raise RuntimeError("test failure")
        return extract(data, *args, **kwargs)

    monkeypatch.setattr(processing, "extract_pdf", flaky)
    results = process_documents(repo, [first["id"], second["id"]], default_depot=depot)
    assert [r.status for r in results] == ["fehler", "angelegt"]
    assert repo.document(first["id"])["status"] == "fehlgeschlagen"
    assert repo.document(second["id"])["status"] == "verarbeitet"


def test_document_with_only_deleted_links_returns_to_review(repo, depot):
    from kest_tool.processing import data_status
    from kest_tool.ui.pages_data import _open_documents

    doc, _ = repo.add_document(demo.tr_buy_pdf(), "kauf.pdf", tax_year=2024)
    result = process_documents(repo, [doc["id"]], default_depot=depot)
    assert result[0].status == "angelegt"
    repo.delete_transaction(result[0].transaction_id, "test correction")
    repo.update_document(doc["id"], status="pruefen")
    assert doc["id"] in [item["id"] for item in data_status(repo, 2024)["docs_open"]]
    assert doc["id"] in [item["id"] for item in _open_documents(repo)]
