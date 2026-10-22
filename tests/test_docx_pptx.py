"""Tests for DOCX and PPTX handlers."""

from __future__ import annotations

from docx import Document
from pptx import Presentation
from pptx.util import Inches, Pt

from local_redact.formats.docx_fmt import DocxHandler
from local_redact.formats.pptx_fmt import PptxHandler


def test_docx_extensions():
    assert DocxHandler.extensions == (".docx",)


def test_pptx_extensions():
    assert PptxHandler.extensions == (".pptx",)


def test_docx_paragraph_and_table(tmp_path, stub_engine):
    src = tmp_path / "in.docx"
    dst = tmp_path / "out.docx"
    doc = Document()
    doc.add_paragraph("Hello John Doe")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "John Doe"
    table.cell(0, 1).text = "ok"
    doc.save(src)

    report = DocxHandler().redact(
        src, dst, stub_engine([("John Doe", "[PERSON_1]")]), "in.docx"
    )
    out = Document(str(dst))
    assert "John Doe" not in out.paragraphs[0].text
    assert "[PERSON_1]" in out.paragraphs[0].text
    assert out.tables[0].cell(0, 0).text == "[PERSON_1]"
    assert out.tables[0].cell(0, 1).text == "ok"
    assert report.status == "redacted"
    assert report.counts["PERSON"] >= 2


def test_docx_no_match_writes(tmp_path, stub_engine):
    src = tmp_path / "clean.docx"
    dst = tmp_path / "out.docx"
    doc = Document()
    doc.add_paragraph("plain")
    doc.save(src)
    report = DocxHandler().redact(src, dst, stub_engine([]), "clean.docx")
    assert report.status == "redacted"
    assert report.counts == {}
    assert Document(str(dst)).paragraphs[0].text == "plain"


def test_pptx_shape_text(tmp_path, stub_engine):
    src = tmp_path / "in.pptx"
    dst = tmp_path / "out.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])  # blank
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.paragraphs[0].text = "Meet John Doe today"
    prs.save(src)

    report = PptxHandler().redact(
        src, dst, stub_engine([("John Doe", "[PERSON_1]")]), "in.pptx"
    )
    out = Presentation(str(dst))
    texts = []
    for shape in out.slides[0].shapes:
        if shape.has_text_frame:
            for p in shape.text_frame.paragraphs:
                texts.append(p.text)
    joined = " ".join(texts)
    assert "John Doe" not in joined
    assert "[PERSON_1]" in joined
    assert report.counts == {"PERSON": 1}


def test_pptx_table_cell(tmp_path, stub_engine):
    src = tmp_path / "table.pptx"
    dst = tmp_path / "out.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    table_shape = slide.shapes.add_table(1, 1, Inches(0.5), Inches(0.5), Inches(3), Inches(1))
    cell = table_shape.table.cell(0, 0)
    cell.text = "John Doe"
    prs.save(src)

    PptxHandler().redact(
        src, dst, stub_engine([("John Doe", "[PERSON_1]")]), "table.pptx"
    )
    out = Presentation(str(dst))
    found = False
    for shape in out.slides[0].shapes:
        if shape.has_table:
            assert shape.table.cell(0, 0).text_frame.paragraphs[0].text == "[PERSON_1]"
            found = True
    assert found
