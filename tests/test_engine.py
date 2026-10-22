"""Real-model engine tests: bilingual detection, merge, placeholder stability,
toggle filtering, custom terms, reveal. Loads both spaCy models ONCE per
session — do not run in parallel with other model-loading tests."""

import pytest

from local_redact.db import MappingDB
from local_redact.engine import Detection, RedactionEngine

from conftest import TEST_PASSPHRASE

HU_DOC = (
    "Kovács János, a Richter Gedeon Nyrt. vezérigazgatója, ma Budapesten "
    "találkozott John Smith-szel. Az adószáma 12345678-1-23, a TAJ száma "
    "123 456 789. E-mail címe: kovacs.janos@example.hu, telefonszáma "
    "+36 30 123 4567. A Project Falcon költségvetése 12 000 000 Ft."
)


@pytest.fixture(scope="session")
def engine(tmp_path_factory):
    db = MappingDB(
        tmp_path_factory.mktemp("engine") / "mapping.db", TEST_PASSPHRASE
    )
    db.add_term("Project Falcon")
    eng = RedactionEngine(db)
    yield eng
    eng.db.close()


class TestBilingualDetection:
    def test_hungarian_entities(self, engine):
        res = engine.redact_text(HU_DOC, doc="t1", audit=False)
        types = {r.entity_type for r in res.replacements}
        assert "PERSON" in types
        assert "ORGANIZATION" in types
        assert "HU_TAX_NUMBER" in types
        assert "HU_TAJ" in types
        assert "EMAIL_ADDRESS" in types
        assert "PHONE_NUMBER" in types

    def test_no_sensitive_values_remain(self, engine):
        res = engine.redact_text(HU_DOC, doc="t2", audit=False)
        for value in ("Kovács János", "Richter Gedeon Nyrt.", "12345678-1-23",
                      "123 456 789", "kovacs.janos@example.hu", "+36 30 123 4567"):
            assert value not in res.text, value

    def test_custom_term_redacted_case_insensitive(self, engine):
        res = engine.redact_text("A PROJECT FALCON titkos.", doc="t3", audit=False)
        assert "PROJECT FALCON" not in res.text
        assert "TERM_" in res.text

    def test_financial_and_dates_off_by_default(self, engine):
        res = engine.redact_text(HU_DOC, doc="t4", audit=False)
        assert "12 000 000 Ft" in res.text  # financial default OFF per spec

    def test_financial_on_when_toggled(self, engine):
        toggles = engine.db.get_toggles()
        toggles["financial_amounts"] = True
        res = engine.redact_text(
            "A költségvetés 12 000 000 Ft.", doc="t5", toggles=toggles, audit=False
        )
        assert "12 000 000 Ft" not in res.text


class TestPlaceholderStability:
    def test_same_value_same_placeholder_across_calls(self, engine):
        r1 = engine.redact_text("Kovács János elment.", doc="t6", audit=False)
        r2 = engine.redact_text("Kovács János szerint a terv jó.", doc="t7", audit=False)
        ph1 = [r.placeholder for r in r1.replacements if r.real_value == "Kovács János"]
        ph2 = [r.placeholder for r in r2.replacements if r.real_value == "Kovács János"]
        assert ph1 and ph1 == ph2

    def test_reveal_round_trip(self, engine):
        original = "Kovács János adószáma 12345678-1-23."
        res = engine.redact_text(original, doc="t8", audit=False)
        revealed, n = engine.reveal_text(res.text, audit=False)
        assert n == len(res.replacements)
        assert revealed == original


class TestMergeAndNoise:
    def test_function_word_not_redacted(self, engine):
        # "Az" (sentence-initial "The") must not become a PERSON placeholder
        res = engine.redact_text("Az adószáma ismert.", doc="t9", audit=False)
        assert res.text.startswith("Az ")

    def test_overlap_resolves_to_single_placeholder(self, engine):
        # custom term "Project Falcon" overlaps any NER hit on "Falcon";
        # result must contain no partial overlap or double redaction
        res = engine.redact_text("A Project Falcon státusza zöld.", doc="t10", audit=False)
        assert "Falcon" not in res.text
        assert "Project" not in res.text


class TestNoiseAndSpanFixups:
    """Static post-processing helpers added after the mixed HU/EN stress
    test. Pure string logic — no spaCy load, run fast in the default suite.
    """

    def _det(self, text, entity_type, needle):
        start = text.index(needle)
        return Detection(entity_type, start, start + len(needle), 0.85)

    def test_is_noise_multi_token_hu_pronoun(self):
        text = "Az ő adószáma ismert."
        assert RedactionEngine._is_noise(text, "PERSON", 0, len("Az ő"))

    def test_is_noise_en_adverb(self):
        text = "Meanwhile, J. Smith confirmed."
        assert RedactionEngine._is_noise(text, "PERSON", 0, len("Meanwhile"))

    def test_is_noise_acronym_denylist(self):
        text = "Paid in HUF today."
        start = text.index("HUF")
        assert RedactionEngine._is_noise(text, "ORGANIZATION", start, start + 3)

    def test_is_noise_hu_spelled_out_number(self):
        text = "Az összeg azaz egymillió-kettőszázötvenezer forint."
        needle = "azaz egymillió-kettőszázötvenezer"
        start = text.index(needle)
        assert RedactionEngine._is_noise(text, "PERSON", start, start + len(needle))

    def test_is_noise_does_not_flag_real_name(self):
        text = "Kovács János elment."
        assert not RedactionEngine._is_noise(text, "PERSON", 0, len("Kovács János"))

    def test_split_conjunctions_splits_coordinated_names(self):
        text = "Nagy Editet és Kovács Jánost is értesítettük."
        d = self._det(text, "PERSON", "Nagy Editet és Kovács Jánost")
        out = RedactionEngine._split_conjunctions(text, [d])
        assert len(out) == 2
        assert text[out[0].start : out[0].end] == "Nagy Editet"
        assert text[out[1].start : out[1].end] == "Kovács Jánost"
        # the word "és" between them stays outside both spans
        assert text[out[0].end : out[1].start] == " és "

    def test_split_conjunctions_leaves_single_name_alone(self):
        text = "Kovács János elment."
        d = self._det(text, "PERSON", "Kovács János")
        out = RedactionEngine._split_conjunctions(text, [d])
        assert out == [d]

    def test_extend_allcaps_stitches_second_word(self):
        text = "that NAGY EDIT (all caps, note!) signed off"
        d = self._det(text, "PERSON", "NAGY")
        out = RedactionEngine._extend_allcaps(text, [d])
        assert text[out[0].start : out[0].end] == "NAGY EDIT"

    def test_extend_allcaps_does_not_reach_across_next_detection(self):
        text = "NAGY EDIT VARGA"
        first = Detection("PERSON", 0, 4, 0.9)  # "NAGY"
        second = Detection("PERSON", 10, 15, 0.9)  # "VARGA" (already its own hit)
        out = RedactionEngine._extend_allcaps(text, [first, second])
        # extension is capped at the next detection's start
        assert out[0].end <= second.start

    def test_trim_leading_stopword_drops_of(self):
        text = "signed off on behalf of Falcon Industries Kft. Her card"
        d = self._det(text, "ORGANIZATION", "of Falcon Industries Kft.")
        out = RedactionEngine._trim_leading_stopword(text, d)
        assert text[out.start : out.end] == "Falcon Industries Kft."

    def test_trim_leading_stopword_leaves_real_org_alone(self):
        text = "Falcon Industries Kft. filed the report."
        d = self._det(text, "ORGANIZATION", "Falcon Industries Kft.")
        out = RedactionEngine._trim_leading_stopword(text, d)
        assert out == d

    def test_trim_trailing_noise_drops_common_noun(self):
        text = "Anna lakcíme 4025 Debrecen."
        d = self._det(text, "PERSON", "Anna lakcíme")
        out = RedactionEngine._trim_trailing_noise(text, d)
        assert text[out.start : out.end] == "Anna"

    def test_trim_trailing_noise_keeps_lowercase_name_particle(self):
        text = "Ludwig van Beethoven composed this."
        d = self._det(text, "PERSON", "Ludwig van Beethoven")
        out = RedactionEngine._trim_trailing_noise(text, d)
        assert text[out.start : out.end] == "Ludwig van Beethoven"

    def test_trim_trailing_noise_ignores_non_person(self):
        text = "Falcon Industries kft filed."
        d = self._det(text, "ORGANIZATION", "Falcon Industries kft")
        out = RedactionEngine._trim_trailing_noise(text, d)
        assert out == d


class TestAudit:
    def test_redact_and_reveal_are_audited(self, engine):
        before = len(engine.db.audit_entries())
        res = engine.redact_text("Kovács János.", doc="audit-doc")
        engine.reveal_text(res.text)
        entries = engine.db.audit_entries()
        actions = [e["action"] for e in entries[before:]]
        assert actions == ["redact_text", "reveal_text"]
        # raw content is never logged — only hashes and counts
        for e in entries[before:]:
            assert "Kovács" not in str(e["detail"])
