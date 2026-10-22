"""Category mapping and defaults (no model load)."""

from local_redact.categories import (
    CATEGORY_DEFAULTS,
    CUSTOM_ENTITY_TYPE,
    ENTITY_TO_CATEGORY,
    prefix_for,
)
from local_redact.engine import ALWAYS_ON, CATEGORY_TO_ENTITIES, RedactionEngine


def test_spec_defaults_financial_and_dates_off():
    assert CATEGORY_DEFAULTS["financial_amounts"] is False
    assert CATEGORY_DEFAULTS["dates"] is False
    for cat in (
        "person_names",
        "organizations",
        "emails",
        "phone_numbers",
        "addresses",
        "national_id_tax",
    ):
        assert CATEGORY_DEFAULTS[cat] is True


def test_custom_term_always_on_not_a_category():
    assert CUSTOM_ENTITY_TYPE not in ENTITY_TO_CATEGORY
    assert CUSTOM_ENTITY_TYPE in ALWAYS_ON


def test_prefix_map():
    assert prefix_for("PERSON") == "PERSON"
    assert prefix_for("ORGANIZATION") == "ORG"
    assert prefix_for("CUSTOM_TERM") == "TERM"
    assert prefix_for("HU_TAX_NUMBER") == "ID"


def test_category_to_entities_inverse():
    eng_defaults = RedactionEngine.category_defaults()
    assert eng_defaults == CATEGORY_DEFAULTS
    # every mappable entity appears under exactly one category list
    inverted = {
        e: cat for cat, ents in CATEGORY_TO_ENTITIES.items() for e in ents
    }
    assert inverted == ENTITY_TO_CATEGORY
