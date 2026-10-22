"""PDF handler (PyMuPDF).

True redaction pipeline:
  1. Extract page text and run engine.redact_text to discover real values.
  2. For each unique real value, search the page with page.search_for and
     apply redaction annotations that REPLACE the glyphs with the placeholder
     (so the pseudonym survives for later reveal).
  3. Apply redactions so underlying content is removed — not just covered.

If a real value is detected in the concatenated page text but search_for finds
zero hits (ligatures, encoding, complex layout), mark status "partial" with
a note; still write whatever redactions succeeded. Never silently pass through
a PDF that raised an open error — let it bubble as failed.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from .base import FileReport, Handler


class PdfHandler(Handler):
    extensions = (".pdf",)

    def redact(self, src: Path, dst: Path, engine, rel_doc: str) -> FileReport:
        doc = fitz.open(src)
        counts: dict[str, int] = {}
        notes: list[str] = []
        miss_total = 0
        try:
            for page_index, page in enumerate(doc):
                text = page.get_text("text") or ""
                if not text.strip():
                    continue
                result = engine.redact_text(text, doc=rel_doc, audit=False)
                for etype, n in result.counts_by_type.items():
                    counts[etype] = counts.get(etype, 0) + n

                # Deduplicate replacements by real_value so we search once.
                # Map real -> (placeholder, entity types seen)
                by_value: dict[str, str] = {}
                for r in result.replacements:
                    by_value.setdefault(r.real_value, r.placeholder)

                for real, placeholder in by_value.items():
                    rects = page.search_for(real)
                    if not rects:
                        miss_total += 1
                        notes.append(
                            f"page {page_index + 1}: detected '{real[:40]}' "
                            f"but could not locate on page"
                        )
                        continue
                    for rect in rects:
                        # fill with black block, insert placeholder text if it fits
                        page.add_redact_annot(
                            rect,
                            text=placeholder,
                            fill=(0, 0, 0),
                            text_color=(1, 1, 1),
                            fontsize=8,
                        )
                page.apply_redactions()

            doc.save(dst, garbage=4, deflate=True)
        finally:
            doc.close()

        status = "partial" if miss_total else "redacted"
        # Cap notes list so report stays useful
        if len(notes) > 20:
            notes = notes[:20] + [f"...and {len(notes) - 20} more location misses"]
        return FileReport(
            rel_path=rel_doc,
            status=status,
            counts=counts,
            notes=notes,
            reason=f"{miss_total} page-location miss(es)" if miss_total else None,
        )
