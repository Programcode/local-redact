"""Batch + CLI tests that use only txt handlers/stub where possible.

Full multi-format batch wait for all format handlers to exist.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from conftest import TEST_PASSPHRASE
from local_redact.batch import batch_redact
from local_redact.cli import main
from local_redact.db import MappingDB
from local_redact.engine import RedactionEngine
from tests.conftest import StubEngine


def test_batch_redacts_txt_and_skips_unknown(tmp_path, stub_engine):
    # Prefer real dispatch once text_fmt exists; if not, skip cleanly.
    try:
        from local_redact.formats import text_fmt  # noqa: F401
    except Exception:
        pytest.skip("text_fmt not available yet")

    eng = stub_engine([("Alice", "PERSON_00000")])
    src = tmp_path / "in"
    dst = tmp_path / "out"
    src.mkdir()
    (src / "a.txt").write_text("Hello Alice", encoding="utf-8")
    (src / "notes.bin").write_bytes(b"\x00\x01secret")
    report = batch_redact(src, dst, eng)
    statuses = {f["source"]: f["status"] for f in report.files}
    assert statuses["a.txt"] in ("redacted", "partial")
    assert (dst / "a.txt").read_text(encoding="utf-8") == "Hello PERSON_00000"
    assert "Alice" not in (dst / "a.txt").read_text(encoding="utf-8")
    # unsupported must not be copied
    assert not (dst / "notes.bin").exists()
    assert statuses["notes.bin"] == "skipped"
    assert (dst / "redaction_report.json").exists()


def test_cli_rejects_unknown_category_state(tmp_path, monkeypatch):
    db_path = tmp_path / "m.db"
    monkeypatch.setenv("LOCAL_REDACT_PASSPHRASE", TEST_PASSPHRASE)
    assert main(["--db", str(db_path), "init"]) == 0
    assert main(["--db", str(db_path), "categories", "--set", "dates", "sometimes"]) == 1
    db = MappingDB(db_path, TEST_PASSPHRASE)
    try:
        assert db.get_toggles()["dates"] is False
    finally:
        db.close()


def test_cli_init_terms_redact_text_reveal_audit(tmp_path, monkeypatch):
    db_path = tmp_path / "m.db"
    env = {**os.environ, "LOCAL_REDACT_PASSPHRASE": TEST_PASSPHRASE}
    monkeypatch.setattr(os, "environ", env)

    assert main(["--db", str(db_path), "init"]) == 0
    assert db_path.exists()
    assert main(["--db", str(db_path), "terms", "--add", "Project Falcon"]) == 0
    assert main(["--db", str(db_path), "categories", "--set", "dates", "on"]) == 0

    # document without needing NLP for custom term — still loads real engine
    # Use a custom-term-only sentence which always works.
    text_in = tmp_path / "in.txt"
    text_out = tmp_path / "out.txt"
    reveal_out = tmp_path / "rev.txt"
    text_in.write_text("Talk about Project Falcon tomorrow.", encoding="utf-8")

    assert main([
        "--db", str(db_path),
        "redact-text", "-i", str(text_in), "-o", str(text_out),
    ]) == 0
    redacted = text_out.read_text(encoding="utf-8")
    assert "Project Falcon" not in redacted
    assert "TERM_" in redacted

    assert main([
        "--db", str(db_path),
        "reveal", "-i", str(text_out), "-o", str(reveal_out),
    ]) == 0
    assert "Project Falcon" in reveal_out.read_text(encoding="utf-8")
    assert main(["--db", str(db_path), "audit"]) == 0
