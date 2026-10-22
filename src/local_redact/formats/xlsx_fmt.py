"""XLSX handler (openpyxl).

Redacts literal cell text values only.

CRITICAL: formulas are never rewritten — a redacted formula breaks the
sheet. With data_only=False openpyxl returns the formula string (starting
with "=") for formula cells, and there is no cached-value access without
Excel, so formula cells are passed through byte-identical. Numbers, dates,
booleans and empty cells are also untouched: the engine is text-oriented.

rich_text=True keeps inline rich formatting of untouched cells intact on
round-trip; a redacted cell is written back as a plain string (its inline
formatting is inherently disrupted by replacement anyway).
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from .base import FileReport, Handler


class XlsxHandler(Handler):
    extensions = (".xlsx",)

    def redact(self, src: Path, dst: Path, engine, rel_doc: str) -> FileReport:
        wb = load_workbook(src, rich_text=True)
        counts: dict[str, int] = {}
        try:
            for ws in wb.worksheets:
                for row in ws.iter_rows():
                    for cell in row:
                        value = cell.value
                        if not isinstance(value, str) or value.startswith("="):
                            # Formula, number, date, bool, empty: untouched.
                            continue
                        result = engine.redact_text(value, doc=rel_doc, audit=False)
                        if result.text != value:
                            cell.value = result.text
                        for etype, n in result.counts_by_type.items():
                            counts[etype] = counts.get(etype, 0) + n
            wb.save(dst)
        finally:
            wb.close()
        return FileReport(rel_path=rel_doc, status="redacted", counts=counts)
