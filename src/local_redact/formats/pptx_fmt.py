"""PPTX handler (python-pptx).

Redacts text in shapes (including table cells and grouped shapes) by
replacing each paragraph's text via shape.paragraphs / cell.text_frame.
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from .base import FileReport, Handler


def _redact_text_frame(text_frame, engine, rel_doc: str, counts: dict[str, int]) -> None:
    for paragraph in text_frame.paragraphs:
        original = paragraph.text
        if not original:
            continue
        result = engine.redact_text(original, doc=rel_doc, audit=False)
        if result.text != original:
            # Collapse runs: keep first run's formatting for the new text.
            if paragraph.runs:
                paragraph.runs[0].text = result.text
                for run in paragraph.runs[1:]:
                    run.text = ""
            else:
                # rare empty-run paragraph; assign via text property
                paragraph.text = result.text
        for etype, n in result.counts_by_type.items():
            counts[etype] = counts.get(etype, 0) + n


def _walk_shapes(shapes, engine, rel_doc: str, counts: dict[str, int]) -> None:
    for shape in shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            _walk_shapes(shape.shapes, engine, rel_doc, counts)
            continue
        if getattr(shape, "has_table", False):
            for row in shape.table.rows:
                for cell in row.cells:
                    _redact_text_frame(cell.text_frame, engine, rel_doc, counts)
            continue
        if getattr(shape, "has_text_frame", False):
            _redact_text_frame(shape.text_frame, engine, rel_doc, counts)


class PptxHandler(Handler):
    extensions = (".pptx",)

    def redact(self, src: Path, dst: Path, engine, rel_doc: str) -> FileReport:
        prs = Presentation(str(src))
        counts: dict[str, int] = {}
        for slide in prs.slides:
            _walk_shapes(slide.shapes, engine, rel_doc, counts)
            if slide.has_notes_slide:
                notes_frame = slide.notes_slide.notes_text_frame
                if notes_frame is not None:
                    _redact_text_frame(notes_frame, engine, rel_doc, counts)
        prs.save(str(dst))
        return FileReport(rel_path=rel_doc, status="redacted", counts=counts)
