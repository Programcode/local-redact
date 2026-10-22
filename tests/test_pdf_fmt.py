"""Tests for the PDF handler (true redaction via PyMuPDF)."""

from __future__ import annotations

import fitz
import pytest

from local_redact.formats.pdf_fmt import PdfHandler


def _make_pdf(path, lines: list[str]) -> None:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 18
    doc.save(path)
    doc.close()


def test_extensions():
    assert PdfHandler.extensions == (".pdf",)


def test_pdf_redacts_text(tmp_path, stub_engine):
    src = tmp_path / "in.pdf"
    dst = tmp_path / "out.pdf"
    _make_pdf(src, ["Contact John Doe for details."])
    report = PdfHandler().redact(
        src, dst, stub_engine([("John Doe", "PERSON_00001")]), "in.pdf"
    )
    assert dst.exists()
    assert report.status in ("redacted", "partial")
    out = fitz.open(dst)
    text = "".join(page.get_text() for page in out)
    out.close()
    assert "John Doe" not in text
    # Placeholder should appear when location succeeded
    if report.status == "redacted":
        assert "PERSON_00001" in text
        assert report.counts.get("PERSON", 0) >= 1


def test_pdf_no_match(tmp_path, stub_engine):
    src = tmp_path / "clean.pdf"
    dst = tmp_path / "out.pdf"
    _make_pdf(src, ["Nothing to see here."])
    report = PdfHandler().redact(src, dst, stub_engine([]), "clean.pdf")
    assert report.status == "redacted"
    assert report.counts == {}
    assert dst.exists()


def test_corrupt_pdf_raises(tmp_path, stub_engine):
    src = tmp_path / "broken.pdf"
    src.write_bytes(b"%PDF-1.4 not really a pdf")
    dst = tmp_path / "out.pdf"
    with pytest.raises(Exception):
        PdfHandler().redact(src, dst, stub_engine([]), "broken.pdf")
