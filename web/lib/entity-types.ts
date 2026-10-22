/** Entity-type -> category/label/highlight-color mapping, mirroring
 * src/local_redact/categories.py (ENTITY_TO_CATEGORY, PREFIX). Kept as a
 * plain TS object rather than fetched, since it changes only alongside
 * backend code changes.
 */

export const ENTITY_TO_CATEGORY: Record<string, string> = {
  PERSON: "person_names",
  ORGANIZATION: "organizations",
  EMAIL_ADDRESS: "emails",
  PHONE_NUMBER: "phone_numbers",
  LOCATION: "addresses",
  HU_TAX_NUMBER: "national_id_tax",
  HU_TAJ: "national_id_tax",
  HU_PERSONAL_ID: "national_id_tax",
  HU_COMPANY_REG: "national_id_tax",
  US_SSN: "national_id_tax",
  IBAN_CODE: "national_id_tax",
  CREDIT_CARD: "national_id_tax",
  GENERIC_ID: "national_id_tax",
  MONETARY: "financial_amounts",
  DATE_TIME: "dates",
  CUSTOM_TERM: "custom_terms",
  MANUAL: "manual",
};

export const CATEGORY_LABELS: Record<string, string> = {
  person_names: "Person names",
  organizations: "Organizations",
  emails: "Emails",
  phone_numbers: "Phone numbers",
  addresses: "Addresses",
  national_id_tax: "National ID / tax",
  financial_amounts: "Financial amounts",
  dates: "Dates",
  custom_terms: "Custom terms",
  manual: "Manual selection",
};

interface Swatch {
  bg: string;
  text: string;
  border: string;
}

const SWATCHES: Record<string, Swatch> = {
  person_names: { bg: "#e1f3fe", text: "#1f6c9f", border: "#bfe4fb" },
  organizations: { bg: "#eee7fb", text: "#5b3fa0", border: "#dccdf5" },
  emails: { bg: "#e3f6f0", text: "#1c7a63", border: "#c3ecdf" },
  phone_numbers: { bg: "#edf3ec", text: "#346538", border: "#d6e7d4" },
  addresses: { bg: "#fbf3db", text: "#956400", border: "#f3e2ac" },
  national_id_tax: { bg: "#fdebec", text: "#9f2f2d", border: "#f8cfd0" },
  financial_amounts: { bg: "#fdf0e4", text: "#a2571a", border: "#f6dcc0" },
  dates: { bg: "#eef0f2", text: "#51606b", border: "#d8dee3" },
  custom_terms: { bg: "#fbe8f2", text: "#a12d6b", border: "#f5c9e1" },
  manual: { bg: "#f2f1ed", text: "#2f3437", border: "#c9c7bf" },
};

export function categoryFor(entityType: string): string {
  return ENTITY_TO_CATEGORY[entityType] ?? "manual";
}

export function swatchFor(entityType: string): Swatch {
  return SWATCHES[categoryFor(entityType)] ?? SWATCHES.manual;
}

export function labelFor(entityType: string): string {
  return CATEGORY_LABELS[categoryFor(entityType)] ?? entityType;
}
