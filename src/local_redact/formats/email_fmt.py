"""EML / MSG handlers.

- .eml: stdlib email package; redact From/To/Cc/Bcc/Subject headers and the
  text/plain (preferred) or text/html body. Attachments are reprocessed via
  formats.redact_bytes (lazy import to avoid circular import with __init__).
- .msg: extract-msg → convert to a synthetic .eml then run EmlHandler so the
  output on disk is always a real .eml (Python cannot write valid binary .msg).
"""

from __future__ import annotations

import email
from email import policy
from email.message import EmailMessage, Message
from email.utils import getaddresses
from pathlib import Path

from bs4 import BeautifulSoup

from .base import FileReport, Handler

_HEADER_FIELDS = ("From", "To", "Cc", "Bcc", "Subject", "Reply-To", "Sender")


def _redact_header_value(value: str, engine, rel_doc: str, counts: dict[str, int]) -> str:
    if not value:
        return value
    # Address headers: redact display names and bare addresses as free text.
    result = engine.redact_text(value, doc=rel_doc, audit=False)
    for etype, n in result.counts_by_type.items():
        counts[etype] = counts.get(etype, 0) + n
    return result.text


def _redact_html(html: str, engine, rel_doc: str, counts: dict[str, int]) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(string=True):
        if not node.parent or node.parent.name in ("script", "style"):
            continue
        original = str(node)
        if not original.strip():
            continue
        result = engine.redact_text(original, doc=rel_doc, audit=False)
        if result.text != original:
            node.replace_with(result.text)
        for etype, n in result.counts_by_type.items():
            counts[etype] = counts.get(etype, 0) + n
    return str(soup)


def _redact_body_part(part: Message, engine, rel_doc: str, counts: dict[str, int]) -> None:
    ctype = part.get_content_type()
    try:
        payload = part.get_content()
    except Exception:
        # fall back to decoded bytes
        raw = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        payload = raw.decode(charset, errors="replace")

    if ctype == "text/html":
        new = _redact_html(payload if isinstance(payload, str) else str(payload), engine, rel_doc, counts)
        part.set_content(new, subtype="html", charset="utf-8")
    else:
        text = payload if isinstance(payload, str) else str(payload)
        result = engine.redact_text(text, doc=rel_doc, audit=False)
        for etype, n in result.counts_by_type.items():
            counts[etype] = counts.get(etype, 0) + n
        part.set_content(result.text, subtype="plain", charset="utf-8")


def _process_attachments(
    msg: EmailMessage,
    engine,
    rel_doc: str,
    counts: dict[str, int],
    notes: list[str],
) -> list[tuple[str, bytes, str]]:
    """Return list of (filename, redacted_bytes, content_type) for kept attachments.

    Failed/unsupported attachments are dropped and noted — never passed through
    un-redacted.
    """
    # Lazy import: formats.__init__ imports email_fmt, so a module-level import
    # of redact_bytes would create a circular import.
    from local_redact.formats import redact_bytes

    kept: list[tuple[str, bytes, str]] = []
    for i, part in enumerate(list(msg.iter_attachments())):
        filename = part.get_filename() or f"attachment-{i}"
        content_type = part.get_content_type() or "application/octet-stream"
        try:
            data = part.get_payload(decode=True) or b""
        except Exception as exc:
            notes.append(f"dropped attachment '{filename}': decode failed ({exc})")
            continue
        if not data:
            notes.append(f"dropped attachment '{filename}': empty payload")
            continue
        att_doc = f"{rel_doc}::att/{filename}"
        out, report = redact_bytes(data, filename, engine, att_doc)
        for etype, n in report.counts.items():
            counts[etype] = counts.get(etype, 0) + n
        if report.status in ("redacted", "partial") and out is not None:
            kept.append((filename, out, content_type))
            if report.status == "partial":
                notes.append(f"attachment '{filename}': partial ({report.reason})")
        else:
            notes.append(
                f"dropped attachment '{filename}': {report.status}"
                + (f" ({report.reason})" if report.reason else "")
            )
    return kept


def _strip_attachments(msg: EmailMessage) -> None:
    """Remove attachment parts in place, keeping body parts."""
    if not msg.is_multipart():
        return
    # Rebuild as multipart/mixed with only non-attachment parts.
    keep = []
    for part in msg.iter_parts():
        disp = (part.get_content_disposition() or "").lower()
        if disp == "attachment" or (
            part.get_filename() and disp != "inline"
            and part.get_content_maintype() not in ("text", "multipart")
        ):
            continue
        if part.get_content_maintype() == "multipart":
            _strip_attachments(part)  # type: ignore[arg-type]
        keep.append(part)
    # Clear and re-add
    for part in list(msg.iter_parts()):
        msg.get_payload().remove(part)  # type: ignore[union-attr]
    for part in keep:
        msg.attach(part)


class EmlHandler(Handler):
    extensions = (".eml",)

    def redact(self, src: Path, dst: Path, engine, rel_doc: str) -> FileReport:
        raw = src.read_bytes()
        msg = email.message_from_bytes(raw, policy=policy.default)
        if not isinstance(msg, EmailMessage):
            # policy.default yields EmailMessage; guard anyway
            msg = EmailMessage(policy=policy.default)
            msg.set_content(raw.decode("utf-8", errors="replace"))

        counts: dict[str, int] = {}
        notes: list[str] = []

        for field in _HEADER_FIELDS:
            if field in msg:
                values = msg.get_all(field, [])
                # Replace with redacted versions
                del msg[field]
                for v in values:
                    msg[field] = _redact_header_value(str(v), engine, rel_doc, counts)

        # Attachments first (need original structure), then body
        kept_atts = _process_attachments(msg, engine, rel_doc, counts, notes)

        # Redact body: walk text parts that are not attachments
        if msg.is_multipart():
            for part in msg.walk():
                if part.is_multipart():
                    continue
                disp = (part.get_content_disposition() or "").lower()
                if disp == "attachment":
                    continue
                if part.get_content_maintype() == "text":
                    _redact_body_part(part, engine, rel_doc, counts)
        else:
            if msg.get_content_maintype() == "text":
                _redact_body_part(msg, engine, rel_doc, counts)

        # Rebuild attachments: strip old, attach redacted
        if msg.is_multipart():
            # remove existing attachments
            payload = msg.get_payload()
            if isinstance(payload, list):
                non_atts = []
                for part in payload:
                    disp = (part.get_content_disposition() or "").lower()
                    if disp == "attachment":
                        continue
                    # also drop orphan binary parts with a filename
                    if (
                        part.get_filename()
                        and part.get_content_maintype() not in ("text", "multipart")
                        and disp != "inline"
                    ):
                        continue
                    non_atts.append(part)
                # replace payload list
                msg.set_payload(None)
                for part in non_atts:
                    msg.attach(part)
            for filename, data, content_type in kept_atts:
                main, _, sub = content_type.partition("/")
                msg.add_attachment(
                    data,
                    maintype=main or "application",
                    subtype=sub or "octet-stream",
                    filename=filename,
                )

        dst.write_bytes(msg.as_bytes(policy=policy.SMTP))
        status = "partial" if notes else "redacted"
        return FileReport(
            rel_path=rel_doc,
            status=status,
            counts=counts,
            notes=notes,
            reason="; ".join(notes[:3]) if notes else None,
        )


class MsgHandler(Handler):
    extensions = (".msg",)

    def redact(self, src: Path, dst: Path, engine, rel_doc: str) -> FileReport:
        import extract_msg

        msg_obj = extract_msg.Message(str(src))
        try:
            eml = EmailMessage(policy=policy.default)
            if msg_obj.sender:
                eml["From"] = msg_obj.sender
            if msg_obj.to:
                eml["To"] = msg_obj.to
            if msg_obj.cc:
                eml["Cc"] = msg_obj.cc
            if getattr(msg_obj, "bcc", None):
                eml["Bcc"] = msg_obj.bcc
            if msg_obj.subject:
                eml["Subject"] = msg_obj.subject

            body = msg_obj.body or ""
            html = getattr(msg_obj, "htmlBody", None)
            if html:
                if isinstance(html, bytes):
                    html = html.decode("utf-8", errors="replace")
                eml.set_content(body or " ", subtype="plain", charset="utf-8")
                eml.add_alternative(html, subtype="html", charset="utf-8")
            else:
                eml.set_content(body or "", subtype="plain", charset="utf-8")

            for att in msg_obj.attachments:
                data = att.data if isinstance(att.data, (bytes, bytearray)) else bytes(att.data or b"")
                name = att.longFilename or att.shortFilename or "attachment"
                # guess type from name
                suffix = Path(name).suffix.lower()
                ctype_map = {
                    ".txt": ("text", "plain"),
                    ".md": ("text", "markdown"),
                    ".csv": ("text", "csv"),
                    ".html": ("text", "html"),
                    ".htm": ("text", "html"),
                    ".pdf": ("application", "pdf"),
                    ".docx": (
                        "application",
                        "vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                    ".xlsx": (
                        "application",
                        "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                    ".pptx": (
                        "application",
                        "vnd.openxmlformats-officedocument.presentationml.presentation",
                    ),
                }
                main, sub = ctype_map.get(suffix, ("application", "octet-stream"))
                eml.add_attachment(bytes(data), maintype=main, subtype=sub, filename=name)
        finally:
            msg_obj.close()

        # Write intermediate .eml then run EmlHandler so attachment recursion,
        # header redaction, and body handling stay one implementation.
        tmp_eml = dst.with_suffix(dst.suffix + ".src.eml")
        try:
            tmp_eml.write_bytes(eml.as_bytes(policy=policy.SMTP))
            # idx may remap msg→eml already via batch; ensure dst ends .eml
            if dst.suffix.lower() != ".eml":
                dst = dst.with_suffix(".eml")
            report = EmlHandler().redact(tmp_eml, dst, engine, rel_doc)
            if "converted from .msg" not in report.notes:
                report.notes = list(report.notes) + ["converted from .msg"]
            return report
        finally:
            try:
                tmp_eml.unlink(missing_ok=True)
            except OSError:
                pass
