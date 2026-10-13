from pathlib import Path

from broker_collector.broker_adapter import DocumentRef, DownloadedFile
from broker_collector.classifier import Classifier
from broker_collector.deduplication import sha256_bytes, sha256_file
from broker_collector.downloader import DocumentStore


def make_store(settings, db):
    return DocumentStore(settings.output_dir, db, Classifier(), settings.max_download_bytes)


def ref(title, url="", broker="trade_republic", date="", source="ui"):
    return DocumentRef(broker=broker, title=title, url=url, date=date, source=source, area="Test")


def test_sha256_helpers(tmp_path, pdf_factory):
    data = pdf_factory("abc")
    p = tmp_path / "a.pdf"
    p.write_bytes(data)
    assert sha256_file(p) == sha256_bytes(data)


def test_identical_content_stored_once(settings, db, pdf_factory):
    store = make_store(settings, db)
    data = pdf_factory("Wertpapierabrechnung Kauf\nDatum: 12.03.2024")
    r1 = store.store(ref("Abrechnung Kauf 12.03.2024", "https://x/a.pdf"), DownloadedFile(data, "a.pdf"))
    r2 = store.store(ref("Kaufabrechnung (anderer Name)", "https://x/b.pdf", date="2024-03-12"),
                     DownloadedFile(data, "andere_datei.pdf"))
    assert r1.status == "downloaded" and r2.status == "duplicate"
    assert r1.document_id == r2.document_id
    files = [p for p in settings.output_dir.rglob("*.pdf")]
    assert len(files) == 1
    locations = db.locations(r1.document_id)
    assert {loc["original_name"] for loc in locations} == {"a.pdf", "andere_datei.pdf"}


def test_same_name_different_content_not_duplicate(settings, db, pdf_factory):
    store = make_store(settings, db)
    r1 = store.store(ref("Kontoauszug", "https://x/1"), DownloadedFile(pdf_factory("Kontoauszug Januar"), "k.pdf"))
    r2 = store.store(ref("Kontoauszug", "https://x/2"), DownloadedFile(pdf_factory("Kontoauszug Februar"), "k.pdf"))
    assert r1.status == r2.status == "downloaded"
    assert r1.sha256 != r2.sha256
    assert r1.local_path != r2.local_path  # keine Überschreibung
    assert Path(r1.local_path).read_bytes() != Path(r2.local_path).read_bytes()


def test_deleted_file_is_restored(settings, db, pdf_factory):
    store = make_store(settings, db)
    data = pdf_factory("Dividende Apple")
    r1 = store.store(ref("Dividende", "https://x/d"), DownloadedFile(data, "d.pdf"))
    Path(r1.local_path).unlink()
    r2 = store.store(ref("Dividende", "https://x/d"), DownloadedFile(data, "d.pdf"))
    assert r2.status == "downloaded" and r2.document_id == r1.document_id
    assert Path(r2.local_path).read_bytes() == data


def test_original_bytes_unchanged(settings, db, pdf_factory):
    store = make_store(settings, db)
    data = pdf_factory("Steuerbescheinigung 2023")
    res = store.store(ref("Jahressteuerbescheinigung 2023", "https://x/s"), DownloadedFile(data, "s.pdf"))
    assert Path(res.local_path).read_bytes() == data
    assert "Steuer" in Path(res.local_path).parts
