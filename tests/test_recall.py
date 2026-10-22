"""Synthetic HU+EN recall corpus against the real bilingual engine.

Planted entities: person names, orgs, HU tax/TAJ, email, phone, custom terms.
Financial amounts and dates are intentionally LEFT as context (defaults OFF).
"""

from __future__ import annotations

import pytest

from local_redact.db import MappingDB
from local_redact.engine import RedactionEngine

from conftest import TEST_PASSPHRASE

# Planted secrets that MUST be gone after redaction.
MUST_REDACT = {
    "Kovács János": "PERSON",
    "John Smith": "PERSON",
    "Sarah Connor": "PERSON",
    "Richter Gedeon Nyrt.": "ORGANIZATION",
    "Acme Corporation": "ORGANIZATION",
    "12345678-1-23": "HU_TAX_NUMBER",
    "123 456 789": "HU_TAJ",
    "kovacs.janos@example.hu": "EMAIL_ADDRESS",
    "john.smith@acme.com": "EMAIL_ADDRESS",
    "+36 30 123 4567": "PHONE_NUMBER",
    "Project Falcon": "CUSTOM_TERM",
    "Operation North": "CUSTOM_TERM",
}

# Present in corpus but must remain (defaults OFF).
MUST_KEEP = [
    "12 000 000 Ft",
    "5 million USD",
]

CORPUS = """
Confidential board memo — vegyes EN/HU

Kovács János (adószám: 12345678-1-23, TAJ: 123 456 789) a Richter Gedeon Nyrt.
képviselője ma találkozott John Smith-szel az Acme Corporation részéről.
Kapcsolat: kovacs.janos@example.hu / +36 30 123 4567.
Sarah Connor monította, hogy a Project Falcon és az Operation North státusza zöld.
Budget note for context only: 12 000 000 Ft and approximately 5 million USD.
Secondary contact: john.smith@acme.com.
""".strip()


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    db = MappingDB(tmp_path_factory.mktemp("recall") / "mapping.db", TEST_PASSPHRASE)
    for term in ("Project Falcon", "Operation North"):
        db.add_term(term)
    eng = RedactionEngine(db)
    yield eng
    eng.db.close()


def test_recall_all_planted_entities(engine):
    res = engine.redact_text(CORPUS, doc="recall_corpus.md", audit=False)
    missing = [v for v in MUST_REDACT if v in res.text]
    assert not missing, f"leaked values remain: {missing}\n---\n{res.text}"

    by_type = res.counts_by_type
    # at least one of each critical family
    type_families = {
        "PERSON": "PERSON" in by_type,
        "ORGANIZATION": "ORGANIZATION" in by_type,
        "TAX": any(k.startswith("HU_") for k in by_type),
        "EMAIL": "EMAIL_ADDRESS" in by_type,
        "PHONE": "PHONE_NUMBER" in by_type,
        "CUSTOM": "CUSTOM_TERM" in by_type,
    }
    failed = [k for k, ok in type_families.items() if not ok]
    assert not failed, f"missing entity families: {failed}; got {by_type}"


def test_recall_keeps_financial_by_default(engine):
    res = engine.redact_text(CORPUS, doc="recall_fin.md", audit=False)
    for keep in MUST_KEEP:
        assert keep in res.text, f"financial context stripped unexpectedly: {keep}"


def test_recall_reveal_round_trip(engine):
    res = engine.redact_text(CORPUS, doc="recall_rt.md", audit=False)
    revealed, n = engine.reveal_text(res.text, audit=False)
    assert n >= len(MUST_REDACT)
    for value in MUST_REDACT:
        assert value in revealed, f"reveal lost {value}"
