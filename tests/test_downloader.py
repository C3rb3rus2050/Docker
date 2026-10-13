import pytest

from broker_collector.broker_adapter import DocumentRef, DownloadedFile, DownloadError, ScanCancelled
from broker_collector.classifier import Classifier
from broker_collector.downloader import (
    DocumentStore,
    FileValidationError,
    detect_format,
    guess_filename_from_headers,
    is_retryable_http,
    retry_call,
    validate_file,
)

MB = 1024 * 1024


class TestSignature:
    def test_formats(self, pdf_factory):
        assert detect_format(pdf_factory()) == "pdf"
        assert detect_format(b"PK\x03\x04rest") == "zip"
        assert detect_format(b"<!DOCTYPE html><html><body>Login</body></html>") == "html"
        assert detect_format(b"\n\n  <html><head>") == "html"
        assert detect_format("Datum;Betrag;Text\n01.01.2024;12,00;Kauf\n".encode()) == "csv"
        assert detect_format(b'{"error":"unauthorized"}') == "json"
        assert detect_format(b"\x00\x01\x02\x03") == "binary"

    def test_html_as_pdf_rejected(self):
        with pytest.raises(FileValidationError, match="HTML"):
            validate_file(b"<html><body>Bitte anmelden</body></html>", "pdf", MB)

    def test_json_as_pdf_rejected(self):
        with pytest.raises(FileValidationError):
            validate_file(b'{"error": 1}', "pdf", MB)

    def test_empty_rejected(self):
        with pytest.raises(FileValidationError, match="Leere"):
            validate_file(b"", None, MB)

    def test_truncated_pdf_rejected(self, pdf_factory):
        data = pdf_factory("x" * 500)
        with pytest.raises(FileValidationError, match="unvollständig"):
            validate_file(data[: len(data) // 2], "pdf", MB)

    def test_too_large(self, pdf_factory):
        with pytest.raises(FileValidationError, match="zu groß"):
            validate_file(pdf_factory(), None, 100)

    def test_valid(self, pdf_factory):
        assert validate_file(pdf_factory(), "pdf", MB) == "pdf"
        assert validate_file(b"a;b\n1;2\n", None, MB) == "csv"

    def test_text_html_content_type(self):
        with pytest.raises(FileValidationError):
            validate_file(b"Fehler: Sitzung abgelaufen", None, MB, "text/html; charset=utf-8")


class TestRetry:
    def test_retries_then_succeeds(self):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise DownloadError("503", retryable=True)
            return "ok"

        sleeps = []
        assert retry_call(fn, attempts=3, backoff_s=1, sleep=sleeps.append) == "ok"
        assert len(calls) == 3 and len(sleeps) == 2 and sleeps[1] > sleeps[0]

    def test_non_retryable_raises_immediately(self):
        calls = []

        def fn():
            calls.append(1)
            raise DownloadError("403", retryable=False)

        with pytest.raises(DownloadError):
            retry_call(fn, attempts=5, sleep=lambda s: None)
        assert len(calls) == 1

    def test_gives_up(self):
        calls = []

        def fn():
            calls.append(1)
            raise TimeoutError("timeout")

        with pytest.raises(TimeoutError):
            retry_call(fn, attempts=3, sleep=lambda s: None)
        assert len(calls) == 3

    def test_cancel_not_retried(self):
        calls = []

        def fn():
            calls.append(1)
            raise ScanCancelled()

        with pytest.raises(ScanCancelled):
            retry_call(fn, attempts=3, sleep=lambda s: None)
        assert len(calls) == 1

    def test_http_status(self):
        assert is_retryable_http(503) and is_retryable_http(429)
        assert not is_retryable_http(404) and not is_retryable_http(403)


class TestFilenames:
    def test_content_disposition(self):
        assert guess_filename_from_headers({"Content-Disposition": 'attachment; filename="Abrechnung.pdf"'}) == \
            "Abrechnung.pdf"
        assert guess_filename_from_headers(
            {"content-disposition": "attachment; filename*=UTF-8''Kontoauszug%20M%C3%A4rz.pdf"}) == \
            "Kontoauszug März.pdf"

    def test_traversal_in_header(self):
        name = guess_filename_from_headers({"Content-Disposition": 'attachment; filename="../../../evil.pdf"'})
        assert name == "evil.pdf"

    def test_from_url(self):
        assert guess_filename_from_headers({}, "https://x.com/a/b/Report%202024.pdf?sig=1") == "Report 2024.pdf"
        assert guess_filename_from_headers({}, "https://x.com/a/b/", "fallback") == "fallback"


class TestStore:
    def test_category_and_year_folder(self, settings, db, pdf_factory):
        store = DocumentStore(settings.output_dir, db, Classifier(), settings.max_download_bytes)
        ref = DocumentRef("scalable_capital", "Dividendenabrechnung Microsoft", url="https://de.scalable.capital/x.pdf",
                          date="2024-05-02")
        res = store.store(ref, DownloadedFile(pdf_factory("Dividende"), "x.pdf"))
        rel = res.local_path.replace("\\", "/")
        assert "/ScalableCapital/Dividenden/2024/" in rel
        assert rel.endswith("2024-05-02_x.pdf")

    def test_extension_follows_content(self, settings, db):
        store = DocumentStore(settings.output_dir, db, Classifier(), settings.max_download_bytes)
        ref = DocumentRef("trade_republic", "Umsätze Export", url="https://app.traderepublic.com/export")
        res = store.store(ref, DownloadedFile("Datum;Betrag\n2024-01-02;5\n".encode(), "export"))
        assert res.local_path.endswith(".csv")

    def test_html_never_stored(self, settings, db):
        store = DocumentStore(settings.output_dir, db, Classifier(), settings.max_download_bytes)
        ref = DocumentRef("trade_republic", "Abrechnung", url="https://app.traderepublic.com/a.pdf")
        with pytest.raises(FileValidationError):
            store.store(ref, DownloadedFile(b"<html>Login</html>", "a.pdf"), "pdf")
        assert not list(settings.output_dir.rglob("*.pdf"))
