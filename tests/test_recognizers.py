"""Pattern recognizers and custom-term matches without loading spaCy models."""

from __future__ import annotations

from local_redact.recognizers import CustomTermRecognizer, hu_recognizers


def test_hu_tax_and_taj_patterns():
    recs = {r.supported_entities[0]: r for r in hu_recognizers("hu")}
    text = "adószám 12345678-1-23, TAJ 123 456 789, cégjegyzékszám 01-09-123456"
    tax_hits = recs["HU_TAX_NUMBER"].analyze(text, entities=["HU_TAX_NUMBER"])
    taj_hits = recs["HU_TAJ"].analyze(text, entities=["HU_TAJ"])
    reg_hits = recs["HU_COMPANY_REG"].analyze(text, entities=["HU_COMPANY_REG"])
    assert any(text[h.start:h.end] == "12345678-1-23" for h in tax_hits)
    assert any(text[h.start:h.end] == "123 456 789" for h in taj_hits)
    assert any(text[h.start:h.end] == "01-09-123456" for h in reg_hits)


def test_custom_term_case_and_whitespace():
    terms = lambda: ["Project Falcon", "Acme Corp"]
    rec = CustomTermRecognizer(terms, language="en")
    text = "update on PROJECT   FALCON and Acme Corp status"
    hits = rec.analyze(text, entities=["CUSTOM_TERM"])
    matched = sorted(text[h.start:h.end] for h in hits)
    assert any("FALCON" in m.upper() for m in matched)
    assert any("Acme Corp" in m for m in matched)


def test_custom_term_whole_phrase_not_substring():
    rec = CustomTermRecognizer(lambda: ["Falcon"], language="en")
    # word boundary: FalconX should not match
    text = "FalconX and Falcon"
    hits = rec.analyze(text, entities=["CUSTOM_TERM"])
    assert len(hits) == 1
    assert text[hits[0].start:hits[0].end] == "Falcon"


def test_hu_full_address_pattern():
    recs = {r.supported_entities[0]: r for r in hu_recognizers("hu")}
    address = recs["LOCATION"]
    text = "Lakcíme: 1234 Budapest, Minta utca 15. 2. em. 3. Telefonszáma: +36 20 555 0142."
    hits = address.analyze(text, entities=["LOCATION"])
    matched = [text[h.start : h.end] for h in hits]
    assert any(m == "1234 Budapest, Minta utca 15. 2. em. 3." for m in matched)


def test_hu_full_address_pattern_ground_floor_and_u_abbreviation():
    recs = {r.supported_entities[0]: r for r in hu_recognizers("hu")}
    address = recs["LOCATION"]
    text = "4026 Debrecen, Minta utca 7. fsz. 2. ajtó."
    hits = address.analyze(text, entities=["LOCATION"])
    matched = [text[h.start : h.end] for h in hits]
    assert any(m == "4026 Debrecen, Minta utca 7. fsz. 2. ajtó" for m in matched)

    text2 = "1234 Budapest, Minta u. 12."
    hits2 = address.analyze(text2, entities=["LOCATION"])
    matched2 = [text2[h.start : h.end] for h in hits2]
    assert any(m == "1234 Budapest, Minta u. 12." for m in matched2)


def test_hu_full_address_pattern_unrecognized_street_type_only_partially_matches():
    # documents the known boundary: a street-type abbreviation not in
    # _HU_STREET_TYPES falls back to no address-pattern match at all (the
    # NER LOCATION fragments still catch the city name in isolation).
    recs = {r.supported_entities[0]: r for r in hu_recognizers("hu")}
    address = recs["LOCATION"]
    text = "1234 Budapest, Some Made-Up Way 9."
    hits = address.analyze(text, entities=["LOCATION"])
    assert hits == []


def test_generic_id_pattern():
    recs = {r.supported_entities[0]: r for r in hu_recognizers("hu")}
    generic_id = recs["GENERIC_ID"]
    text = "Her personal ID card reads ID# 665544332211."
    hits = generic_id.analyze(text, entities=["GENERIC_ID"])
    assert any(text[h.start : h.end] == "ID# 665544332211" for h in hits)

    text2 = "Please confirm passport number 112233445566 on file."
    hits2 = generic_id.analyze(text2, entities=["GENERIC_ID"])
    assert any(text2[h.start : h.end] == "passport number 112233445566" for h in hits2)
