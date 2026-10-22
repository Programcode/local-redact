"""Per-format redaction handlers and batch dispatch.

Supported: .txt/.md, .csv, .docx, .xlsx, .pptx, .pdf, .eml, .msg
(msg is redacted into an .eml copy — Python cannot write valid binary .msg).

Fail-closed: files that cannot be processed are marked failed/skipped and are
NOT copied to the output tree. Nothing un-redacted passes through silently.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..util import scrub_file
from .base import FileReport, Handler
from . import docx_fmt, email_fmt, pdf_fmt, pptx_fmt, text_fmt, xlsx_fmt

_HANDLERS: dict[str, Handler] = {}
for _h in (
    text_fmt.TextHandler(),
    text_fmt.CsvHandler(),
    docx_fmt.DocxHandler(),
    xlsx_fmt.XlsxHandler(),
    pptx_fmt.PptxHandler(),
    pdf_fmt.PdfHandler(),
    email_fmt.EmlHandler(),
    email_fmt.MsgHandler(),
):
    for _ext in _h.extensions:
        _HANDLERS[_ext] = _h

SUPPORTED_EXTENSIONS = sorted(_HANDLERS)


def handler_for(path: Path) -> Handler | None:
    return _HANDLERS.get(path.suffix.lower())


def redact_file(src: Path, dst: Path, engine, rel_doc: str) -> FileReport:
    handler = handler_for(src)
    if handler is None:
        return FileReport(
            rel_path=rel_doc,
            status="skipped",
            reason=f"unsupported format '{src.suffix.lower()}'",
        )
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = handler.redact(src, dst, engine, rel_doc)
    except Exception as exc:  # corrupt/encrypted/unsupported-in-practice
        try:
            dst.unlink(missing_ok=True)
        except OSError:
            pass
        report = FileReport(rel_path=rel_doc, status="failed", reason=str(exc))
    engine.db.log_action(
        "redact_file",
        doc=rel_doc,
        detail={
            "status": report.status,
            "reason": report.reason,
            "counts": report.counts,
            "notes": report.notes,
        },
    )
    return report


def redact_bytes(
    data: bytes, filename: str, engine, rel_doc: str
) -> tuple[bytes | None, FileReport]:
    """Redact an attachment held in memory. Uses a scrubbed temp file only
    because handlers work on real paths; intermediates are overwritten and
    deleted on return."""
    ext = Path(filename).suffix.lower()
    handler = _HANDLERS.get(ext)
    if handler is None:
        return None, FileReport(
            rel_path=rel_doc,
            status="skipped",
            reason=f"unsupported attachment format '{ext}'",
        )
    with tempfile.TemporaryDirectory(prefix="local-redact-") as tmp:
        tmp_path = Path(tmp)
        src = tmp_path / ("att" + ext)
        dst = tmp_path / ("att.out" + ext)
        src.write_bytes(data)
        try:
            report = handler.redact(src, dst, engine, rel_doc)
            if report.status in ("redacted", "partial") and dst.exists():
                out = dst.read_bytes()
            else:
                out = None
        except Exception as exc:
            report = FileReport(rel_path=rel_doc, status="failed", reason=str(exc))
            out = None
        scrub_file(src)
        if dst.exists():
            scrub_file(dst)
    return out, report
