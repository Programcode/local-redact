"""Tests for EML handler (and MSG conversion path where feasible)."""

from __future__ import annotations

import email
from email import policy
from email.message import EmailMessage

from local_redact.formats.email_fmt import EmlHandler


def _write_eml(path, *, subject, sender, to, body, html=None, attachment=None):
    msg = EmailMessage(policy=policy.default)
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    if attachment:
        name, data = attachment
        msg.add_attachment(data, maintype="text", subtype="plain", filename=name)
    path.write_bytes(msg.as_bytes(policy=policy.SMTP))


def test_extensions():
    assert EmlHandler.extensions == (".eml",)


def test_eml_headers_and_body(tmp_path, stub_engine):
    src = tmp_path / "in.eml"
    dst = tmp_path / "out.eml"
    _write_eml(
        src,
        subject="Update from John Doe",
        sender="John Doe <john@example.com>",
        to="team@example.com",
        body="Please call John Doe tomorrow.",
    )
    engine = stub_engine(
        [
            ("John Doe", "[PERSON_1]"),
            ("john@example.com", "[EMAIL_1]"),
        ]
    )
    report = EmlHandler().redact(src, dst, engine, "in.eml")
    assert dst.exists()
    assert report.status in ("redacted", "partial")
    out = email.message_from_bytes(dst.read_bytes(), policy=policy.default)
    assert "John Doe" not in (out["Subject"] or "")
    assert "[PERSON_1]" in (out["Subject"] or "")
    assert "John Doe" not in (out["From"] or "")
    body = out.get_body(preferencelist=("plain",))
    plain = body.get_content() if body else ""
    assert "John Doe" not in plain
    assert "[PERSON_1]" in plain
    assert report.counts.get("PERSON", 0) >= 1


def test_eml_attachment_txt_redacted(tmp_path, stub_engine):
    src = tmp_path / "att.eml"
    dst = tmp_path / "out.eml"
    _write_eml(
        src,
        subject="files",
        sender="a@b.com",
        to="c@d.com",
        body="see attachment",
        attachment=("note.txt", b"Secret John Doe inside"),
    )
    report = EmlHandler().redact(
        src, dst, stub_engine([("John Doe", "[PERSON_1]")]), "att.eml"
    )
    assert report.status in ("redacted", "partial")
    out = email.message_from_bytes(dst.read_bytes(), policy=policy.default)
    atts = list(out.iter_attachments())
    assert len(atts) == 1
    payload = atts[0].get_payload(decode=True) or b""
    assert b"John Doe" not in payload
    assert b"[PERSON_1]" in payload


def test_eml_unsupported_attachment_dropped(tmp_path, stub_engine):
    src = tmp_path / "drop.eml"
    dst = tmp_path / "out.eml"
    _write_eml(
        src,
        subject="bin",
        sender="a@b.com",
        to="c@d.com",
        body="attached",
        attachment=("blob.bin", b"\x00\x01\x02John Doe"),
    )
    # .bin has no handler → dropped, notes set, partial
    report = EmlHandler().redact(
        src, dst, stub_engine([("John Doe", "[PERSON_1]")]), "drop.eml"
    )
    out = email.message_from_bytes(dst.read_bytes(), policy=policy.default)
    assert list(out.iter_attachments()) == []
    assert report.status == "partial"
    assert any("dropped" in n for n in report.notes)


def test_eml_no_match(tmp_path, stub_engine):
    src = tmp_path / "clean.eml"
    dst = tmp_path / "out.eml"
    _write_eml(
        src,
        subject="hello",
        sender="a@b.com",
        to="c@d.com",
        body="no secrets",
    )
    report = EmlHandler().redact(src, dst, stub_engine([]), "clean.eml")
    assert report.status == "redacted"
    assert report.counts == {}
