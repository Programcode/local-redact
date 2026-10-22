"""Plain text / markdown / CSV handlers.

CSV is parsed cell-by-cell so structure (quoting, commas) is preserved even
when redaction rewrites a cell. .txt/.md decode as UTF-8 (BOM-tolerant) and
fail closed on undecodable bytes.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from .base import FileReport, Handler


def _read_text_strict(path: Path) -> str:
    raw = path.read_bytes()
    # BOM-tolerant UTF-8; anything else is treated as corrupt (fail-closed).
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    return raw.decode("utf-8")


class TextHandler(Handler):
    extensions = (".txt", ".md")

    def redact(self, src: Path, dst: Path, engine, rel_doc: str) -> FileReport:
        text = _read_text_strict(src)
        result = engine.redact_text(text, doc=rel_doc, audit=False)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(result.text, encoding="utf-8")
        return FileReport(
            rel_path=rel_doc,
            status="redacted",
            counts=dict(result.counts_by_type),
        )


class CsvHandler(Handler):
    extensions = (".csv",)

    def redact(self, src: Path, dst: Path, engine, rel_doc: str) -> FileReport:
        text = _read_text_strict(src)
        counts: dict[str, int] = {}
        # sniffer needs a sample; empty files stay empty.
        if not text:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text("", encoding="utf-8")
            return FileReport(rel_path=rel_doc, status="redacted", counts={})

        reader = csv.reader(io.StringIO(text))
        out_buf = io.StringIO()
        writer = csv.writer(out_buf, lineterminator="\n")
        for row in reader:
            new_row = []
            for cell in row:
                result = engine.redact_text(cell, doc=rel_doc, audit=False)
                new_row.append(result.text)
                for etype, n in result.counts_by_type.items():
                    counts[etype] = counts.get(etype, 0) + n
            writer.writerow(new_row)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(out_buf.getvalue(), encoding="utf-8")
        return FileReport(rel_path=rel_doc, status="redacted", counts=counts)
