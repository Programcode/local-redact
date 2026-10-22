"""Shared fixtures. Do NOT load spaCy models here — format-handler tests use
the deterministic StubEngine; only test_engine.py / test_recall.py load real
models (they own their own fixtures)."""

from __future__ import annotations

import pytest

from local_redact.db import MappingDB
from local_redact.engine import Detection, RedactResult, Replacement

TEST_PASSPHRASE = "test-passphrase"


@pytest.fixture
def tmp_db(tmp_path):
    db = MappingDB(tmp_path / "mapping.db", TEST_PASSPHRASE)
    yield db
    db.close()


class StubEngine:
    """Deterministic stand-in for RedactionEngine in format tests.

    pairs: list of (real_value, placeholder) — every occurrence of real_value
    is replaced, offsets reported like the real engine. No NLP, no model load,
    keeps parallel test runs light on RAM. `db` is a real MappingDB so
    per-file audit logging in the dispatcher works.
    """

    def __init__(self, db: MappingDB, pairs: list[tuple[str, str]] | None = None):
        self.db = db
        self.pairs = list(pairs or [])

    def redact_text(self, text, doc=None, toggles=None, audit=False):
        replacements: list[Replacement] = []
        for real, placeholder in self.pairs:
            idx = text.find(real)
            while idx != -1:
                replacements.append(
                    Replacement("PERSON", idx, idx + len(real), real, placeholder)
                )
                text = text[:idx] + placeholder + text[idx + len(real):]
                idx = text.find(real, idx + len(placeholder))
        return RedactResult(text, replacements)

    def reveal_text(self, text, audit=False):
        n = 0
        for real, placeholder in self.pairs:
            n += text.count(placeholder)
            text = text.replace(placeholder, real)
        return text, n

    def analyze(self, text, toggles=None):
        """Detection-only pass (no DB writes) — mirrors RedactionEngine.analyze
        for server tests that exercise preview/confirm as two separate steps."""
        detections: list[Detection] = []
        for real, _ in self.pairs:
            start = 0
            while True:
                idx = text.find(real, start)
                if idx == -1:
                    break
                detections.append(Detection("PERSON", idx, idx + len(real), 1.0))
                start = idx + len(real)
        return sorted(detections, key=lambda d: d.start)

    def apply_redactions(self, text, detections, doc=None, audit=True):
        """Commit an explicit detection list, mirroring
        RedactionEngine.apply_redactions (real DB placeholder creation)."""
        detections = sorted(detections, key=lambda d: d.start)
        parts, replacements, last = [], [], 0
        for d in detections:
            real = text[d.start : d.end]
            placeholder = self.db.get_or_create_placeholder(real, d.entity_type, doc)
            parts.append(text[last : d.start])
            parts.append(placeholder)
            last = d.end
            replacements.append(Replacement(d.entity_type, d.start, d.end, real, placeholder))
        parts.append(text[last:])
        result = RedactResult("".join(parts), replacements)
        if audit:
            self.db.log_action(
                "redact_text",
                doc=doc,
                detail={"replacements": len(replacements), "by_type": result.counts_by_type},
            )
        return result


@pytest.fixture
def stub_engine(tmp_db):
    """Returns a factory: stub_engine([(real, placeholder), ...])"""
    def _make(pairs=None):
        return StubEngine(tmp_db, pairs)

    return _make
