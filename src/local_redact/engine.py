"""Bilingual redaction engine: Presidio analyzers (EN + HU), overlap merging,
stable pseudonymization via the encrypted mapping DB, and reveal.

Every document gets both language passes (spec: mixed-language documents are
the norm, language is never auto-detected or user-flagged).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from presidio_analyzer.nlp_engine import NerModelConfiguration, SpacyNlpEngine
from presidio_analyzer.predefined_recognizers import (
    CreditCardRecognizer,
    EmailRecognizer,
    IbanRecognizer,
    PhoneRecognizer,
    SpacyRecognizer,
    UsSsnRecognizer,
)

from .categories import CATEGORY_DEFAULTS, CUSTOM_ENTITY_TYPE, ENTITY_TO_CATEGORY
from .db import MappingDB
from .recognizers import CustomTermRecognizer, hu_recognizers
from .util import sha256_text

logger = logging.getLogger(__name__)

SCORE_THRESHOLD = 0.4
PHONE_REGIONS = ("HU", "US", "GB", "DE", "AT", "CH")
NER_ENTITIES = ["PERSON", "ORGANIZATION", "LOCATION", "DATE_TIME", "MONETARY"]
#: entity types considered regardless of toggle state (custom terms are
#: always redacted; everything else flows through category toggles)
ALWAYS_ON = [CUSTOM_ENTITY_TYPE]

#: entity types only meaningful on one language pass (registry has no
#: recognizer for them in the other; requesting them just spams warnings)
_HU_ONLY = {"HU_TAX_NUMBER", "HU_TAJ", "HU_PERSONAL_ID", "HU_COMPANY_REG", "GENERIC_ID"}
_EN_ONLY = {"EMAIL_ADDRESS", "IBAN_CODE", "CREDIT_CARD", "US_SSN", CUSTOM_ENTITY_TYPE}

CATEGORY_TO_ENTITIES: dict[str, list[str]] = {}
for _etype, _cat in ENTITY_TO_CATEGORY.items():
    CATEGORY_TO_ENTITIES.setdefault(_cat, []).append(_etype)

#: conservative upper bound for a single text segment fed to spaCy
MAX_NLP_CHARS = 5_000_000

#: single-token Hungarian function words that statistical NER reliably
#: mislabels as PERSON/ORG (sentence-initial "Az", "A", ...). Over-redaction
#: is safe, but redacting every sentence opener floods the placeholder space
#: and degrades AI comprehension for no privacy gain.
_HU_FUNCTION_WORDS = {
    "az", "azaz", "a", "egy", "és", "hogy", "nem", "is", "meg", "el", "fel",
    "le", "ki", "be", "rá", "át", "vissza", "de", "ha", "mint", "már",
    "még", "csak", "akkor", "amikor", "vagy", "illetve", "hiszen", "mivel",
    "így", "úgy", "majd", "ezt", "azt", "ez", "ő", "mi", "ti", "ők", "én",
    "te",
}

#: same idea as _HU_FUNCTION_WORDS but for the English pass — common
#: sentence-opening adverbs/conjunctions that spaCy's EN model occasionally
#: mislabels as PERSON when they're capitalized at a sentence start.
_EN_FUNCTION_WORDS = {
    "meanwhile", "however", "therefore", "otherwise", "moreover",
    "nonetheless", "furthermore", "besides", "instead", "thus", "hence",
    "also", "then", "so", "still", "yet", "indeed", "again", "here",
    "there", "now", "today", "tomorrow", "yesterday",
}

#: acronyms/currency codes that NER models routinely mislabel as
#: PERSON/ORGANIZATION/LOCATION when they appear as bare tokens.
_ACRONYM_DENYLIST = {
    "USD", "EUR", "HUF", "GBP", "CHF", "JPY", "SMS", "PIN", "ATM", "URL",
    "PDF", "FAQ",
}

#: substrings that mark a token as (part of) a spelled-out Hungarian number
#: (e.g. "egymillió", "kettőszázötvenezer"). Combined with function words,
#: this catches phrases like "azaz egymillió-kettőszázötvenezer" that NER
#: sometimes tags as PERSON.
_HU_NUMBER_ROOTS = (
    "millió", "milliárd", "száz", "ezer", "tizen", "húsz", "harminc",
    "negyven", "ötven", "hatvan", "hetven", "nyolcvan", "kilencven",
)

#: leading connector words that NER span boundaries sometimes swallow along
#: with a real entity (e.g. "of Falcon Industries Kft."). Trimmed from the
#: front of a detection so they stay in plaintext instead of vanishing into
#: the placeholder.
_LEADING_TRIM_WORDS = _HU_FUNCTION_WORDS | {"of", "the", "a", "an", "on", "in", "for"}

#: lowercase name particles that legitimately appear inside a PERSON span
#: ("van der Berg") — everything else lowercase trailing a capitalized name
#: (e.g. "Anna lakcíme" = "Anna['s] address") is NER over-capture, not part
#: of the name, and gets trimmed by _trim_trailing_noise.
_PERSON_LOWERCASE_PARTICLES = {"van", "der", "von", "de", "di", "la", "le", "al", "dr.", "dr"}


@dataclass
class Detection:
    entity_type: str
    start: int
    end: int
    score: float


@dataclass
class Replacement:
    entity_type: str
    start: int  # span in the ORIGINAL text
    end: int
    real_value: str
    placeholder: str


@dataclass
class RedactResult:
    text: str
    replacements: list[Replacement] = field(default_factory=list)

    @property
    def counts_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.replacements:
            counts[r.entity_type] = counts.get(r.entity_type, 0) + 1
        return counts


class RedactionEngine:
    def __init__(self, db: MappingDB):
        self.db = db
        self._analyzers: dict[str, AnalyzerEngine] | None = None

    # -- NLP setup (lazy: CLI commands that only touch the DB stay fast) ---

    def _build_analyzers(self) -> dict[str, AnalyzerEngine]:
        mapping = dict(NerModelConfiguration().model_to_presidio_entity_mapping)
        mapping["MONEY"] = "MONETARY"  # not mapped by default
        cfg = NerModelConfiguration(model_to_presidio_entity_mapping=mapping)

        analyzers = {}
        for lang, model in (("en", "en_core_web_lg"), ("hu", "hu_core_news_lg")):
            nlp_engine = SpacyNlpEngine(
                models=[{"lang_code": lang, "model_name": model}],
                ner_model_configuration=cfg,
            )
            nlp_engine.load()
            nlp_engine.nlp[lang].max_length = MAX_NLP_CHARS

            registry = RecognizerRegistry(supported_languages=[lang])
            registry.add_recognizer(
                SpacyRecognizer(supported_language=lang, supported_entities=NER_ENTITIES)
            )
            registry.add_recognizer(
                PhoneRecognizer(
                    supported_language=lang, supported_regions=PHONE_REGIONS
                )
            )
            if lang == "en":
                registry.add_recognizer(EmailRecognizer())
                registry.add_recognizer(IbanRecognizer())
                registry.add_recognizer(CreditCardRecognizer())
                registry.add_recognizer(UsSsnRecognizer())
                registry.add_recognizer(
                    CustomTermRecognizer(self.db.list_terms, language="en")
                )
            else:
                for rec in hu_recognizers(language="hu"):
                    registry.add_recognizer(rec)

            analyzers[lang] = AnalyzerEngine(
                nlp_engine=nlp_engine,
                registry=registry,
                supported_languages=[lang],
            )
        return analyzers

    def _ensure_nlp(self) -> None:
        if self._analyzers is None:
            self._analyzers = self._build_analyzers()

    # -- detection -----------------------------------------------------------

    def _requested_entities(self, toggles: dict[str, bool]) -> list[str]:
        requested = list(ALWAYS_ON)
        for category, enabled in toggles.items():
            if enabled:
                requested.extend(CATEGORY_TO_ENTITIES.get(category, []))
        return sorted(set(requested))

    def analyze(self, text: str, toggles: dict[str, bool] | None = None) -> list[Detection]:
        """Run both language passes and merge into non-overlapping detections."""
        self._ensure_nlp()
        if toggles is None:
            toggles = self.db.get_toggles()
        requested = self._requested_entities(toggles)
        results = []
        for lang, analyzer in self._analyzers.items():
            if lang == "hu":
                lang_entities = [e for e in requested if e not in _EN_ONLY]
            else:
                lang_entities = [e for e in requested if e not in _HU_ONLY]
            for r in analyzer.analyze(
                text,
                language=lang,
                entities=lang_entities,
                score_threshold=SCORE_THRESHOLD,
            ):
                if self._is_noise(text, r.entity_type, r.start, r.end):
                    continue
                results.append(
                    Detection(
                        entity_type=r.entity_type,
                        start=r.start,
                        end=r.end,
                        score=r.score,
                    )
                )
        merged = self._merge(results)
        split = self._split_conjunctions(text, merged)
        extended = self._extend_allcaps(text, split)
        trimmed = [self._trim_leading_stopword(text, d) for d in extended]
        trimmed = [self._trim_trailing_noise(text, d) for d in trimmed]
        return sorted(trimmed, key=lambda d: d.start)

    @staticmethod
    def _is_noise(text: str, entity_type: str, start: int, end: int) -> bool:
        """Catch-all filter for NER hits that are structurally not PII:
        bare function words/pronouns, ambiguous acronyms/currency codes, and
        spelled-out Hungarian numbers — all safe to leave in plaintext."""
        if entity_type not in ("PERSON", "ORGANIZATION", "LOCATION"):
            return False
        raw = text[start:end].strip()
        if raw in _ACRONYM_DENYLIST:
            return True
        span = raw.strip(".,;:!?").lower()
        tokens = span.split()
        if not tokens:
            return False
        if all(t in _HU_FUNCTION_WORDS or t in _EN_FUNCTION_WORDS for t in tokens):
            return True

        def _number_ish(tok: str) -> bool:
            return tok in _HU_FUNCTION_WORDS or any(root in tok for root in _HU_NUMBER_ROOTS)

        if all(_number_ish(t) for t in tokens) and any(
            any(root in t for root in _HU_NUMBER_ROOTS) for t in tokens
        ):
            return True
        return False

    @staticmethod
    def _split_conjunctions(text: str, detections: list[Detection]) -> list[Detection]:
        """spaCy sometimes returns one PERSON/ORGANIZATION span for two
        coordinated names ("Nagy Editet és Kovács Jánost") instead of two —
        split those back into independent entities so each keeps its own
        stable placeholder and "és" (and) stays in plaintext."""
        pattern = re.compile(
            r"^(?P<a>[A-ZÁÉÍÓÖŐÚÜŰ][\wáéíóöőúüű-]*(?:\s+[A-ZÁÉÍÓÖŐÚÜŰ][\wáéíóöőúüű-]*)?)"
            r"\s+és\s+"
            r"(?P<b>[A-ZÁÉÍÓÖŐÚÜŰ][\wáéíóöőúüű-]*(?:\s+[A-ZÁÉÍÓÖŐÚÜŰ][\wáéíóöőúüű-]*)?)$"
        )
        out: list[Detection] = []
        for d in detections:
            if d.entity_type in ("PERSON", "ORGANIZATION"):
                m = pattern.match(text[d.start : d.end])
                if m:
                    a_end = d.start + len(m.group("a"))
                    b_start = d.end - len(m.group("b"))
                    out.append(Detection(d.entity_type, d.start, a_end, d.score))
                    out.append(Detection(d.entity_type, b_start, d.end, d.score))
                    continue
            out.append(d)
        return out

    @staticmethod
    def _extend_allcaps(text: str, detections: list[Detection]) -> list[Detection]:
        """ALL-CAPS multi-word names (e.g. "NAGY EDIT") are frequently
        under-tagged to a single word by the NER model. If a PERSON/
        ORGANIZATION span is itself all-caps and immediately followed by
        another all-caps word, extend the span onto it."""
        extended: list[Detection] = []
        for i, d in enumerate(detections):
            if d.entity_type in ("PERSON", "ORGANIZATION") and text[d.start : d.end].isupper():
                m = re.match(r" ([A-ZÁÉÍÓÖŐÚÜŰ]{2,})(?=[\s.,;:!?]|\Z)", text[d.end :])
                if m:
                    new_end = d.end + 1 + len(m.group(1))
                    next_start = detections[i + 1].start if i + 1 < len(detections) else len(text)
                    if new_end <= next_start:
                        d = Detection(d.entity_type, d.start, new_end, d.score)
            extended.append(d)
        return extended

    @staticmethod
    def _trim_leading_stopword(text: str, d: Detection) -> Detection:
        """Trim a leading connector word ("of Falcon Industries Kft.") that
        the NER span boundary swallowed along with the real entity."""
        if d.entity_type not in ("PERSON", "ORGANIZATION", "LOCATION"):
            return d
        span = text[d.start : d.end]
        m = re.match(r"^([A-Za-zÀ-ſ]+)\s+", span)
        if m and m.group(1).lower() in _LEADING_TRIM_WORDS:
            return Detection(d.entity_type, d.start + len(m.group(0)), d.end, d.score)
        return d

    @staticmethod
    def _trim_trailing_noise(text: str, d: Detection) -> Detection:
        """PERSON spans occasionally swallow a following lowercase common
        noun ("Anna lakcíme" = "Anna's address", "lakcíme" is not part of
        the name). Trim trailing lowercase tokens that aren't recognized
        name particles, leaving them in plaintext."""
        if d.entity_type != "PERSON":
            return d
        span = text[d.start : d.end]
        tokens = span.split(" ")
        end = d.end
        while len(tokens) > 1:
            last = tokens[-1]
            bare = last.strip(".,;:!?'’")
            if bare and bare.isalpha() and bare.islower() and bare.lower() not in _PERSON_LOWERCASE_PARTICLES:
                end -= len(last) + 1
                tokens.pop()
            else:
                break
        return Detection(d.entity_type, d.start, end, d.score)

    @staticmethod
    def _merge(detections: list[Detection]) -> list[Detection]:
        """Resolve overlaps: longest span wins; ties go to the higher score
        (custom terms score 1.0, so they win exact ties against NER)."""
        ordered = sorted(
            detections, key=lambda d: (-(d.end - d.start), -d.score, d.start)
        )
        accepted: list[Detection] = []
        for d in ordered:
            if all(d.end <= a.start or d.start >= a.end for a in accepted):
                accepted.append(d)
        return sorted(accepted, key=lambda d: d.start)

    # -- redact / reveal -----------------------------------------------------

    def redact_text(
        self,
        text: str,
        doc: str | None = None,
        toggles: dict[str, bool] | None = None,
        audit: bool = True,
    ) -> RedactResult:
        detections = self.analyze(text, toggles)
        return self.apply_redactions(text, detections, doc=doc, audit=audit)

    def apply_redactions(
        self,
        text: str,
        detections: list[Detection],
        doc: str | None = None,
        audit: bool = True,
    ) -> RedactResult:
        """Commit an explicit, already-decided detection list: create/reuse
        placeholders and substitute. Used directly by review-screen callers
        that let a human accept/reject/add spans between detection and
        commit — nothing touches the DB until this runs."""
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
                detail={
                    "input_sha256": sha256_text(text),
                    "replacements": len(replacements),
                    "by_type": result.counts_by_type,
                },
            )
        return result

    def reveal_text(self, text: str, audit: bool = True) -> tuple[str, int]:
        mapping = self.db.placeholder_map()
        if not mapping:
            if audit:
                self.db.log_action(
                    "reveal_text",
                    detail={"input_sha256": sha256_text(text), "restored": 0},
                )
            return text, 0
        pattern = re.compile(
            "|".join(re.escape(p) for p in sorted(mapping, key=len, reverse=True))
        )
        restored = 0

        def _sub(match: re.Match) -> str:
            nonlocal restored
            restored += 1
            return mapping[match.group(0)]

        out = pattern.sub(_sub, text)
        if audit:
            self.db.log_action(
                "reveal_text",
                detail={"input_sha256": sha256_text(text), "restored": restored},
            )
        return out, restored

    # -- convenience ----------------------------------------------------------

    def toggles(self) -> dict[str, bool]:
        return self.db.get_toggles()

    @staticmethod
    def category_defaults() -> dict[str, bool]:
        return dict(CATEGORY_DEFAULTS)
