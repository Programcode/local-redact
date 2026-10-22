"""Redaction categories, their defaults, and entity-type mapping.

Defaults per approved design spec: person names, organizations, emails, phone
numbers, addresses, national ID/tax numbers default ON; financial amounts and
dates default OFF. Custom terms are not a category — they are always redacted.
"""

from __future__ import annotations

#: category -> default toggle state (spec: do not flip financial/dates back on)
CATEGORY_DEFAULTS: dict[str, bool] = {
    "person_names": True,
    "organizations": True,
    "emails": True,
    "phone_numbers": True,
    "addresses": True,
    "national_id_tax": True,
    "financial_amounts": False,
    "dates": False,
}

#: entity type -> category. Anything not listed here (e.g. CUSTOM_TERM) is
#: always redacted and not user-toggleable.
ENTITY_TO_CATEGORY: dict[str, str] = {
    "PERSON": "person_names",
    "ORGANIZATION": "organizations",
    "EMAIL_ADDRESS": "emails",
    "PHONE_NUMBER": "phone_numbers",
    "LOCATION": "addresses",
    "HU_TAX_NUMBER": "national_id_tax",
    "HU_TAJ": "national_id_tax",
    "HU_PERSONAL_ID": "national_id_tax",
    "HU_COMPANY_REG": "national_id_tax",
    "US_SSN": "national_id_tax",
    "IBAN_CODE": "national_id_tax",
    "CREDIT_CARD": "national_id_tax",
    "GENERIC_ID": "national_id_tax",
    "MONETARY": "financial_amounts",
    "DATE_TIME": "dates",
}

#: entity type -> placeholder prefix (PERSON_00001, ORG_00007, ...).
PREFIX: dict[str, str] = {
    "PERSON": "PERSON",
    "ORGANIZATION": "ORG",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "LOCATION": "ADDRESS",
    "HU_TAX_NUMBER": "ID",
    "HU_TAJ": "ID",
    "HU_PERSONAL_ID": "ID",
    "HU_COMPANY_REG": "ID",
    "US_SSN": "ID",
    "IBAN_CODE": "IBAN",
    "CREDIT_CARD": "CARD",
    "GENERIC_ID": "ID",
    "MONETARY": "MONEY",
    "DATE_TIME": "DATE",
    "CUSTOM_TERM": "TERM",
    "MANUAL": "REDACT",
}

CUSTOM_ENTITY_TYPE = "CUSTOM_TERM"


def prefix_for(entity_type: str) -> str:
    return PREFIX.get(entity_type, "ENTITY")
