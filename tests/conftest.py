from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from broker_collector.config import Settings  # noqa: E402
from broker_collector.database import Database  # noqa: E402


def make_pdf(text: str = "Testdokument", extra_pages: int = 0) -> bytes:
    """Erzeugt ein kleines, gültiges PDF mit extrahierbarem Text (künstliche Testdatei)."""
    pages = [text] + [f"Seite {i + 2}" for i in range(extra_pages)]
    objects: list[bytes] = []
    n_pages = len(pages)
    font_id = 3 + 2 * n_pages
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    for i, page_text in enumerate(pages):
        content_id = 4 + 2 * i
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>".encode()
        )
        safe = page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines = safe.split("\n")
        ops = "BT /F1 12 Tf 50 780 Td 14 TL " + " ".join(f"({ln}) Tj T*" for ln in lines) + " ET"
        stream = ops.encode("latin-1", errors="replace")
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{idx} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


@pytest.fixture
def pdf_factory():
    return make_pdf


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(output_dir=tmp_path / "out", profile_dir=tmp_path / "profiles")
    s.retry_backoff_s = 0.0
    s.action_delay_ms = 50
    s.login_wait_timeout_s = 2
    s.ensure_dirs()
    return s


@pytest.fixture
def db(settings: Settings):
    database = Database(settings.database_path)
    yield database
    database.close()


@pytest.fixture(scope="session")
def chromium_executable() -> str:
    return os.environ.get("BDC_BROWSER_EXECUTABLE", "")
