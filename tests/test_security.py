import logging
from pathlib import Path

import pytest

from broker_collector.config import ConfigError, Settings, apply_values
from broker_collector.security import (
    RedactingFilter,
    UnsafePathError,
    UrlPolicy,
    UrlValidationError,
    is_probably_cloud_synced,
    redact,
    redact_url,
    remove_tree,
    safe_join,
    sanitize_filename,
    validate_url,
)


class TestSanitizeFilename:
    @pytest.mark.parametrize("raw,expected", [
        ("../../etc/passwd", "passwd"),
        ("..\\..\\Windows\\system32\\evil.pdf", "evil.pdf"),
        ("C:\\Users\\x\\a.pdf", "a.pdf"),
        ("Abrechnung: Kauf <Apple>?.pdf", "Abrechnung_ Kauf _Apple_.pdf"),
        ("CON.pdf", "_CON.pdf"),
        ("nul", "_nul"),
        ("  .hidden. ", "hidden"),
        ("", "dokument"),
        ("...", "dokument"),
        ("a\x00b\x1fc.pdf", "a_b_c.pdf"),
    ])
    def test_cases(self, raw, expected):
        assert sanitize_filename(raw) == expected

    def test_length_keeps_extension(self):
        name = sanitize_filename("x" * 400 + ".PDF")
        assert len(name) <= 150 and name.endswith(".pdf")

    def test_never_contains_separators(self):
        for raw in ["a/b\\c.pdf", "/abs/path.pdf", "\\\\server\\share\\f.pdf"]:
            out = sanitize_filename(raw)
            assert "/" not in out and "\\" not in out


class TestSafeJoin:
    def test_inside(self, tmp_path):
        assert safe_join(tmp_path, "a", "b.pdf") == (tmp_path / "a" / "b.pdf").resolve()

    @pytest.mark.parametrize("part", ["../x.pdf", "a/../../x.pdf", "/etc/passwd"])
    def test_traversal_blocked(self, tmp_path, part):
        with pytest.raises(UnsafePathError):
            safe_join(tmp_path, part)


class TestValidateUrl:
    policy = UrlPolicy(("traderepublic.com",), (r"[a-z0-9.-]*traderepublic[a-z0-9.-]*\.amazonaws\.com",))

    @pytest.mark.parametrize("url", [
        "https://app.traderepublic.com/profile",
        "https://traderepublic.com/x.pdf",
        "https://traderepublic-docs.s3.eu-central-1.amazonaws.com/a.pdf?X-Amz-Signature=abc",
    ])
    def test_allowed(self, url):
        assert validate_url(url, self.policy) == url

    @pytest.mark.parametrize("url", [
        "http://app.traderepublic.com/",
        "https://evil.com/traderepublic.com",
        "https://traderepublic.com.evil.com/",
        "https://user:pw@app.traderepublic.com/",
        "https://127.0.0.1/",
        "https://localhost/",
        "javascript:alert(1)",
        "file:///C:/Windows/win.ini",
        "https://other-bucket.s3.amazonaws.com/a.pdf",
        "https://app.traderepublic.com/\r\nX: y",
        "",
    ])
    def test_rejected(self, url):
        with pytest.raises(UrlValidationError):
            validate_url(url, self.policy)

    def test_blob(self):
        assert validate_url("blob:https://app.traderepublic.com/123", self.policy, allow_blob=True)
        with pytest.raises(UrlValidationError):
            validate_url("blob:https://app.traderepublic.com/123", self.policy)
        with pytest.raises(UrlValidationError):
            validate_url("blob:https://evil.com/1", self.policy, allow_blob=True)


class TestRedaction:
    def test_url_params(self):
        out = redact_url("https://s3.amazonaws.com/a.pdf?X-Amz-Signature=deadbeef&X-Amz-Credential=AKIA&page=2")
        assert "deadbeef" not in out and "AKIA" not in out and "page=2" in out

    def test_free_text(self):
        text = ('GET https://api.x.com/v1?token=SECRET123&sessionId=abc Cookie: tr_session=XYZ; tr_refresh=QQQ '
                'Authorization: Bearer abc.def.ghi {"password": "hunter2", "sessionToken":"tok"} '
                'jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c '
                'Telefon +49 170 1234567')
        out = redact(text)
        for secret in ("SECRET123", "tr_session=XYZ", "QQQ", "hunter2", "tok\"", "SflKxwRJSMeKKF2QT4fw", "1234567"):
            assert secret not in out, secret

    def test_logging_filter(self, tmp_path):
        logger = logging.getLogger("bdc.test.redact")
        path = tmp_path / "log.txt"
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.addFilter(RedactingFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            logger.info("Download %s fehlgeschlagen", "https://x.traderepublic.com/doc.pdf?sig=SUPERSECRET")
            try:
                raise RuntimeError("cookie: tr_session=TOPSECRET")
            except RuntimeError:
                logger.exception("Fehler")
        finally:
            handler.close()
            logger.removeHandler(handler)
        content = path.read_text(encoding="utf-8")
        assert "SUPERSECRET" not in content and "TOPSECRET" not in content
        assert "doc.pdf" in content and "Fehler" in content


def test_remove_tree_guard(tmp_path):
    inside = tmp_path / "base" / "x"
    inside.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(UnsafePathError):
        remove_tree(other, must_be_inside=[tmp_path / "base"])
    assert remove_tree(inside, must_be_inside=[tmp_path / "base"]) is True
    assert not inside.exists()
    assert remove_tree(inside) is False


def test_cloud_detection():
    assert is_probably_cloud_synced(Path("C:/Users/max/OneDrive/Documents/BrokerDocumentCollector"))
    assert not is_probably_cloud_synced(Path("D:/Daten/BrokerDocumentCollector"))


def test_config_rejects_credentials():
    with pytest.raises(ConfigError):
        apply_values(Settings(), {"password": "x"})
    with pytest.raises(ConfigError):
        apply_values(Settings(), {"broker": {"session_token": "x"}})
    with pytest.raises(ConfigError):
        apply_values(Settings(), {"unknown_key": 1})
    s = apply_values(Settings(), {"ocr_enabled": "ja", "max_download_mb": "5"})
    assert s.ocr_enabled is True and s.max_download_mb == 5
