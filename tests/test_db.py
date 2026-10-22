"""MappingDB tests: encryption, placeholder stability, toggles, terms, audit,
wipe, fail-closed behavior."""

import pytest

from local_redact.db import DatabaseError, MappingDB

from conftest import TEST_PASSPHRASE


class TestPlaceholders:
    def test_sequential_per_type(self, tmp_db):
        assert tmp_db.get_or_create_placeholder("A B", "PERSON", None) == "PERSON_00000"
        assert tmp_db.get_or_create_placeholder("C D", "PERSON", None) == "PERSON_00001"
        assert tmp_db.get_or_create_placeholder("X Kft", "ORGANIZATION", None) == "ORG_00000"

    def test_same_value_same_placeholder_case_and_space_insensitive(self, tmp_db):
        p1 = tmp_db.get_or_create_placeholder("Kovács János", "PERSON", "a.txt")
        p2 = tmp_db.get_or_create_placeholder("kovács  JÁNOS", "PERSON", "b.txt")
        assert p1 == p2

    def test_first_seen_doc_kept(self, tmp_db):
        tmp_db.get_or_create_placeholder("A B", "PERSON", "first.txt")
        tmp_db.get_or_create_placeholder("a b", "PERSON", "second.txt")
        rows = tmp_db._conn.execute(
            "SELECT first_seen_doc FROM entities"
        ).fetchall()
        assert rows == [("first.txt",)]


class TestToggles:
    def test_spec_defaults(self, tmp_db):
        t = tmp_db.get_toggles()
        for cat in ("person_names", "organizations", "emails", "phone_numbers",
                    "addresses", "national_id_tax"):
            assert t[cat] is True, cat
        assert t["financial_amounts"] is False
        assert t["dates"] is False

    def test_set_and_persist(self, tmp_db):
        tmp_db.set_toggle("financial_amounts", True)
        assert tmp_db.get_toggles()["financial_amounts"] is True
        tmp_db.set_toggle("person_names", False)
        assert tmp_db.get_toggles()["person_names"] is False
        # other categories untouched
        assert tmp_db.get_toggles()["emails"] is True

    def test_unknown_category_rejected(self, tmp_db):
        with pytest.raises(ValueError):
            tmp_db.set_toggle("not_a_category", True)


class TestCustomTerms:
    def test_add_dedupe_case_insensitive(self, tmp_db):
        assert tmp_db.add_term("Project Falcon") is True
        assert tmp_db.add_term("project falcon") is False
        assert tmp_db.list_terms() == ["Project Falcon"]

    def test_remove(self, tmp_db):
        tmp_db.add_term("Acme Corp")
        assert tmp_db.remove_term("ACME CORP") is True
        assert tmp_db.list_terms() == []
        assert tmp_db.remove_term("Acme Corp") is False

    def test_empty_rejected(self, tmp_db):
        with pytest.raises(ValueError):
            tmp_db.add_term("   ")


class TestAuditLog:
    def test_hash_chain_verifies(self, tmp_db):
        tmp_db.log_action("redact_text", detail={"input_sha256": "a" * 64})
        tmp_db.log_action("reveal_text", detail={"input_sha256": "b" * 64})
        assert tmp_db.verify_audit_chain() is True

    def test_tampering_breaks_chain(self, tmp_db):
        tmp_db.log_action("redact_text", detail={"replacements": 1})
        tmp_db.log_action("reveal_text", detail={"restored": 1})
        with tmp_db._conn:
            tmp_db._conn.execute(
                "UPDATE audit_log SET detail = ? WHERE id = 1", ('{"replacements": 999}',)
            )
        assert tmp_db.verify_audit_chain() is False


class TestWipe:
    def test_wipe_resets_everything(self, tmp_db):
        tmp_db.get_or_create_placeholder("A B", "PERSON", None)
        tmp_db.add_term("Secret")
        tmp_db.set_toggle("dates", True)
        tmp_db.wipe()
        assert tmp_db.entity_count() == 0
        assert tmp_db.list_terms() == []
        assert tmp_db.get_toggles()["dates"] is False
        # counters reset: numbering restarts
        assert tmp_db.get_or_create_placeholder("C D", "PERSON", None) == "PERSON_00000"
        # audit chain restarted with a wipe entry and still verifies
        assert tmp_db.verify_audit_chain() is True
        assert tmp_db.audit_entries()[-1]["action"] == "wipe"


class TestEncryptionAndFailClosed:
    def test_no_plaintext_at_rest(self, tmp_path):
        db = MappingDB(tmp_path / "m.db", TEST_PASSPHRASE)
        db.get_or_create_placeholder("Kovács János", "PERSON", None)
        db.close()
        raw = (tmp_path / "m.db").read_bytes()
        assert b"PERSON_00000" not in raw
        assert "Kovács".encode() not in raw

    def test_wrong_passphrase_fails_closed(self, tmp_path):
        db = MappingDB(tmp_path / "m.db", TEST_PASSPHRASE)
        db.close()
        with pytest.raises(DatabaseError):
            MappingDB(tmp_path / "m.db", "wrong-passphrase")

    def test_reopen_with_correct_passphrase(self, tmp_path):
        db = MappingDB(tmp_path / "m.db", TEST_PASSPHRASE)
        db.get_or_create_placeholder("A B", "PERSON", None)
        db.close()
        db2 = MappingDB(tmp_path / "m.db", TEST_PASSPHRASE)
        assert db2.entity_count() == 1
        db2.close()

    def test_missing_db_fails_closed_when_not_creating(self, tmp_path):
        with pytest.raises(DatabaseError):
            MappingDB(tmp_path / "nope.db", TEST_PASSPHRASE, create=False)
