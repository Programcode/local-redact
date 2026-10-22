"""Tests for the text/csv format handlers (formats/text_fmt.py).

Sibling format modules (docx_fmt, xlsx_fmt, ...) are owned by other
workstreams and may not exist yet; formats/__init__.py imports all of them
eagerly. To keep these tests self-contained we register minimal stand-ins for
any sibling whose file is genuinely missing. Real modules always win: a
sibling is only stubbed when its .py file is absent, and never when it is
already imported.
"""

from __future__ import annotations

import csv
import sys
import types
from pathlib import Path

import pytest

import local_redact
from local_redact.engine import RedactResult

_FORMATS_DIR = Path(local_redact.__file__).parent / "formats"
_SIBLINGS = {
    "docx_fmt": ("DocxHandler",),
    "xlsx_fmt": ("XlsxHandler",),
    "pptx_fmt": ("PptxHandler",),
    "pdf_fmt": ("PdfHandler",),
    "email_fmt": ("EmlHandler", "MsgHandler"),
}
for _name, _classes in _SIBLINGS.items():
    _full = f"local_redact.formats.{_name}"
    if _full in sys.modules or (_FORMATS_DIR / f"{_name}.py").exists():
        continue
    _mod = types.ModuleType(_full)
    for _cls in _classes:
        setattr(_mod, _cls, type(_cls, (), {"extensions": ()}))
    sys.modules[_full] = _mod

from local_redact import formats  # noqa: E402
from local_redact.formats.text_fmt import CsvHandler, TextHandler  # noqa: E402


# --------------------------------------------------------------------------
# .txt / .md
# --------------------------------------------------------------------------


def test_txt_redacts_targets_keeps_rest(tmp_path, stub_engine):
    engine = stub_engine([("Kovács János", "<<PERSON_1>>")])
    src = tmp_path / "note.txt"
    src.write_text(
        "Kovács János met the team on Tuesday.\nBudget unchanged.\n",
        encoding="utf-8",
    )
    dst = tmp_path / "out" / "note.txt"

    report = TextHandler().redact(src, dst, engine, "note.txt")

    assert report.status == "redacted"
    assert report.rel_path == "note.txt"
    assert report.counts == {"PERSON": 1}
    out = dst.read_text(encoding="utf-8")
    assert "Kovács János" not in out
    assert "<<PERSON_1>>" in out
    assert "Budget unchanged.\n" in out


def test_txt_counts_every_occurrence(tmp_path, stub_engine):
    engine = stub_engine([("Kovács János", "<<PERSON_1>>")])
    src = tmp_path / "twice.txt"
    src.write_text("Kovács János called. Kovács János left.", encoding="utf-8")
    dst = tmp_path / "twice.out.txt"

    report = TextHandler().redact(src, dst, engine, "twice.txt")

    assert report.status == "redacted"
    assert report.counts == {"PERSON": 2}
    assert dst.read_text(encoding="utf-8") == "<<PERSON_1>> called. <<PERSON_1>> left."


def test_md_redacts_and_preserves_markdown(tmp_path, stub_engine):
    engine = stub_engine([("Szabó Ágnes", "<<PERSON_1>>")])
    src = tmp_path / "doc.md"
    src.write_text(
        "# Meeting notes\n\n- Attendee: Szabó Ágnes\n- **Action** items open\n",
        encoding="utf-8",
    )
    dst = tmp_path / "out" / "doc.md"

    report = TextHandler().redact(src, dst, engine, "doc.md")

    assert report.status == "redacted"
    assert report.counts == {"PERSON": 1}
    out = dst.read_text(encoding="utf-8")
    assert "# Meeting notes" in out
    assert "- **Action** items open\n" in out
    assert "Szabó Ágnes" not in out
    assert "<<PERSON_1>>" in out


def test_txt_hungarian_utf8_roundtrip(tmp_path, stub_engine):
    engine = stub_engine([("Ősz Kovács", "<<PERSON_1>>")])
    src = tmp_path / "hungarian.txt"
    src.write_text("áéíóöőúüű — Ősz Kovács Budapesten él.", encoding="utf-8")
    dst = tmp_path / "out.txt"

    report = TextHandler().redact(src, dst, engine, "hungarian.txt")

    assert report.status == "redacted"
    out = dst.read_text(encoding="utf-8")
    assert out == "áéíóöőúüű — <<PERSON_1>> Budapesten él."


def test_txt_utf8_bom_stripped(tmp_path, stub_engine):
    engine = stub_engine([("Kovács János", "<<PERSON_1>>")])
    src = tmp_path / "bom.txt"
    src.write_text("Kovács János\n", encoding="utf-8-sig")
    dst = tmp_path / "out.txt"

    report = TextHandler().redact(src, dst, engine, "bom.txt")

    assert report.status == "redacted"
    raw = dst.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # spec: output is plain UTF-8
    assert dst.read_text(encoding="utf-8") == "<<PERSON_1>>\n"


def test_empty_txt_still_redacted(tmp_path, stub_engine):
    engine = stub_engine([("Kovács János", "<<PERSON_1>>")])
    src = tmp_path / "empty.txt"
    src.write_text("", encoding="utf-8")
    dst = tmp_path / "out.txt"

    report = TextHandler().redact(src, dst, engine, "empty.txt")

    assert report.status == "redacted"
    assert report.counts == {}
    assert dst.exists()
    assert dst.read_text(encoding="utf-8") == ""


# --------------------------------------------------------------------------
# .csv
# --------------------------------------------------------------------------


def test_csv_redacts_cells_preserves_structure(tmp_path, stub_engine):
    engine = stub_engine(
        [("Kovács János", "<<PERSON_1>>"), ("kj@example.com", "<<EMAIL_1>>")]
    )
    src = tmp_path / "people.csv"
    src.write_text(
        'name,email,note\nKovács János,kj@example.com,"met, in person"\n',
        encoding="utf-8",
    )
    dst = tmp_path / "out" / "people.csv"

    report = CsvHandler().redact(src, dst, engine, "people.csv")

    assert report.status == "redacted"
    assert report.counts == {"PERSON": 2}  # StubEngine types everything PERSON

    with dst.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows == [
        ["name", "email", "note"],  # headers untouched
        ["<<PERSON_1>>", "<<EMAIL_1>>", "met, in person"],
    ]
    # comma-containing field stays a single quoted field, no columns invented
    assert '"met, in person"' in dst.read_text(encoding="utf-8")


def test_csv_untouched_columns_byte_identical(tmp_path, stub_engine):
    engine = stub_engine([("Kovács János", "<<PERSON_1>>")])
    src = tmp_path / "mixed.csv"
    src.write_text(
        "id,who,amount\n1,Kovács János,4200\n2,nobody,13\n", encoding="utf-8"
    )
    dst = tmp_path / "out.csv"

    report = CsvHandler().redact(src, dst, engine, "mixed.csv")

    assert report.status == "redacted"
    assert report.counts == {"PERSON": 1}
    with dst.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows == [
        ["id", "who", "amount"],
        ["1", "<<PERSON_1>>", "4200"],
        ["2", "nobody", "13"],
    ]


def test_empty_csv_still_redacted(tmp_path, stub_engine):
    engine = stub_engine([("Kovács János", "<<PERSON_1>>")])
    src = tmp_path / "empty.csv"
    src.write_text("", encoding="utf-8")
    dst = tmp_path / "out.csv"

    report = CsvHandler().redact(src, dst, engine, "empty.csv")

    assert report.status == "redacted"
    assert report.counts == {}
    assert dst.exists()
    assert dst.read_text(encoding="utf-8") == ""


# --------------------------------------------------------------------------
# scoping / fail-closed behaviour
# --------------------------------------------------------------------------


def test_handlers_claim_only_their_extensions():
    assert TextHandler.extensions == (".txt", ".md")
    assert CsvHandler.extensions == (".csv",)


def test_unknown_extension_skipped_not_copied(tmp_path, stub_engine):
    engine = stub_engine([("Kovács János", "<<PERSON_1>>")])
    src = tmp_path / "mystery.xyz"
    src.write_text("Kovács János", encoding="utf-8")
    dst = tmp_path / "out" / "mystery.xyz"

    report = formats.redact_file(src, dst, engine, "mystery.xyz")

    assert report.status == "skipped"
    assert not dst.exists()


def test_corrupt_txt_fails_not_copied(tmp_path, stub_engine):
    engine = stub_engine([("Kovács János", "<<PERSON_1>>")])
    src = tmp_path / "broken.txt"
    src.write_bytes(b"\xff\xfe invalid utf-8 \x93\x94")
    dst = tmp_path / "out" / "broken.txt"

    report = formats.redact_file(src, dst, engine, "broken.txt")

    assert report.status == "failed"
    assert not dst.exists()


def test_engine_called_per_segment_with_doc_and_no_audit(tmp_path):
    class SpyEngine:
        def __init__(self):
            self.calls = []

        def redact_text(self, text, doc=None, toggles=None, audit=True):
            self.calls.append((text, doc, audit))
            return RedactResult(text, [])

    engine = SpyEngine()
    src = tmp_path / "rows.csv"
    src.write_text("a,b\nc,d\n", encoding="utf-8")
    dst = tmp_path / "out.csv"

    report = CsvHandler().redact(src, dst, engine, "sub/rows.csv")

    assert report.status == "redacted"
    assert [c[0] for c in engine.calls] == ["a", "b", "c", "d"]
    assert all(doc == "sub/rows.csv" for _, doc, _ in engine.calls)
    assert all(audit is False for _, _, audit in engine.calls)
