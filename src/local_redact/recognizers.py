"""Custom recognizers: Hungarian ID patterns, HU date/money formats, and the
persistent custom-term recognizer (always redacts, NER-confidence-independent).
"""

from __future__ import annotations

import re
from typing import Callable

from presidio_analyzer import EntityRecognizer, Pattern, PatternRecognizer, RecognizerResult

from .categories import CUSTOM_ENTITY_TYPE

# --- Hungarian pattern recognizers -----------------------------------------

HU_MONTHS = (
    "január|február|március|április|május|június|július|augusztus|"
    "szeptember|október|november|december"
)

#: Hungarian capitalized-word fragment (accented letters included) — used to
#: build the full street-address pattern below.
_HU_CAP_WORD = r"[A-ZÁÉÍÓÖŐÚÜŰ][\wáéíóöőúüű]*"
_HU_STREET_TYPES = (
    r"(?:utca|u\.|út|tér|krt\.?|körút|sétány|köz|allé|fasor|rakpart|liget|"
    r"udvar|park)"
)


def hu_recognizers(language: str = "hu") -> list[PatternRecognizer]:
    """Hungarian national ID / tax / company / date / money patterns.

    Registered on the Hungarian analyzer pass, which runs on every document,
    so these fire in English-language documents too.
    """
    tax = PatternRecognizer(
        supported_entity="HU_TAX_NUMBER",
        supported_language=language,
        patterns=[
            Pattern("hu_tax", r"\b\d{8}-\d{1}-\d{2}\b", 0.5),
        ],
        context=["adószám", "adoszam", "adószáma", "tax number", "tax id", "vat"],
    )
    taj = PatternRecognizer(
        supported_entity="HU_TAJ",
        supported_language=language,
        patterns=[
            # spaced 3-3-3 is the canonical written form; bare 9 digits only
            # count with nearby context (low base score + context boost).
            Pattern("hu_taj_spaced", r"\b\d{3} \d{3} \d{3}\b", 0.5),
            Pattern("hu_taj_plain", r"\b\d{9}\b", 0.1),
        ],
        context=["taj", "társadalombiztosítási", "social security"],
    )
    personal_id = PatternRecognizer(
        supported_entity="HU_PERSONAL_ID",
        supported_language=language,
        patterns=[
            Pattern("hu_personal_id", r"\b\d{6}[A-Z]{2}\b", 0.5),
        ],
        context=["személyi", "igazolvány", "személyi szám", "id number"],
    )
    company_reg = PatternRecognizer(
        supported_entity="HU_COMPANY_REG",
        supported_language=language,
        patterns=[
            Pattern("hu_company_reg", r"\b\d{2}-\d{2}-\d{6}\b", 0.5),
        ],
        context=["cégjegyzékszám", "cegjegyzekszam", "cg.", "company registration"],
    )
    hu_date = PatternRecognizer(
        supported_entity="DATE_TIME",
        supported_language=language,
        patterns=[
            Pattern("hu_date_numeric", r"\b\d{4}\.\s?\d{1,2}\.\s?\d{1,2}\.?\b", 0.5),
            Pattern(
                "hu_date_month_name",
                rf"\b\d{4}\.\s+(?:{HU_MONTHS})\s+\d{{1,2}}\.",
                0.5,
            ),
        ],
    )
    hu_money = PatternRecognizer(
        supported_entity="MONETARY",
        supported_language=language,
        patterns=[
            Pattern(
                "hu_money",
                r"\b\d[\d .,]*\s?(?:Ft|HUF|EUR|USD|forint|millió|milliárd)\b",
                0.5,
            ),
        ],
    )
    # Full HU street address: postal code + city + street + house number,
    # with optional floor/door. A plain "LOCATION" NER hit only ever grabs the
    # city/street name in isolation, leaving the postal code and house/floor/
    # door numbers in plaintext — this is a much longer match, so it wins the
    # overlap-merge against those fragments.
    address = PatternRecognizer(
        supported_entity="LOCATION",
        supported_language=language,
        patterns=[
            Pattern(
                "hu_full_address",
                rf"\b\d{{4}}\s+{_HU_CAP_WORD}(?:\s+{_HU_CAP_WORD})?,\s*"
                rf"{_HU_CAP_WORD}(?:\s+{_HU_CAP_WORD})?\s+{_HU_STREET_TYPES}\.?"
                rf"\s+\d+\.?"
                rf"(?:\s*(?:\d+\.?\s*(?:em\.?|emelet)\.?|fsz\.?|földszint\.?))?"
                rf"(?:\s*\d+\.?(?:\s*(?:ajtó|a\.))?)?",
                0.6,
            ),
        ],
        context=["lakcím", "lakcíme", "cím", "address"],
    )
    # Generic ID/passport/card numbers: HU-specific patterns above only match
    # HU tax/TAJ/personal-ID/company-reg formats. This catches labeled
    # generic ID numbers (any nationality) that would otherwise leak.
    generic_id = PatternRecognizer(
        supported_entity="GENERIC_ID",
        supported_language=language,
        patterns=[
            Pattern(
                "generic_id_labeled",
                r"\b(?:ID\s*#|ID\s*No\.?|ID\s*number|passport\s*(?:no\.?|number)?|"
                r"card\s*(?:no\.?|number))\s*[:#]?\s*\d{6,15}\b",
                0.6,
            ),
        ],
    )
    return [tax, taj, personal_id, company_reg, hu_date, hu_money, address, generic_id]


# --- Custom term recognizer -------------------------------------------------


class CustomTermRecognizer(EntityRecognizer):
    """Exact-phrase matcher for the user's persistent custom term list.

    Terms are read through `terms_loader` on every analyze() call so additions
    take effect without rebuilding the NLP engines. Always score 1.0.
    """

    def __init__(self, terms_loader: Callable[[], list[str]], language: str = "en"):
        super().__init__(
            supported_entities=[CUSTOM_ENTITY_TYPE],
            supported_language=language,
            name="CustomTermRecognizer",
        )
        self._terms_loader = terms_loader

    @staticmethod
    def _pattern_for(term: str) -> re.Pattern:
        # flexible internal whitespace, non-word boundaries at the edges
        core = r"\s+".join(re.escape(part) for part in term.split())
        return re.compile(rf"(?<![\w])(?:{core})(?![\w])", re.IGNORECASE)

    def load(self) -> None:  # nothing to preload
        pass

    def analyze(self, text, entities=None, nlp_artifacts=None):
        results = []
        for term in self._terms_loader():
            for match in self._pattern_for(term).finditer(text):
                results.append(
                    RecognizerResult(
                        entity_type=CUSTOM_ENTITY_TYPE,
                        start=match.start(),
                        end=match.end(),
                        score=1.0,
                        recognition_metadata={
                            RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                            RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id,
                        },
                    )
                )
        return results
