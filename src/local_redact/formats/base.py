"""Contract shared by all per-format handlers and the batch walker."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileReport:
    """Outcome of redacting one file.

    status:
      "redacted" — fully processed, output written
      "partial"  — output written but with caveats (see notes), e.g. a PDF
                   value that could not be located on-page, or an email
                   attachment dropped because it could not be verified
      "skipped"  — not processed, NOT copied (unsupported format)
      "failed"   — processing error (corrupt file etc.), NOT copied
    Nothing un-redacted ever reaches the output tree.
    """

    rel_path: str
    status: str
    reason: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class Handler:
    """Per-format redaction handler.

    Handlers receive `engine` (local_redact.engine.RedactionEngine) and call
    engine.redact_text(text, doc=rel_doc, audit=False) per text segment.
    Per-file audit logging is the dispatcher's job, not the handler's.
    """

    extensions: tuple[str, ...] = ()

    def redact(self, src: Path, dst: Path, engine, rel_doc: str) -> FileReport:
        raise NotImplementedError
