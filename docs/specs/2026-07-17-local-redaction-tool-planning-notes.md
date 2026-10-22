# Local Document Redaction Tool — Planning Notes (draft, in progress)

*Status: this is an interim summary of an ongoing design conversation, not a final approved spec. A full spec with architecture, data flow, error handling, and testing plan will follow once design questions are worked through.*

## The problem

Company (or personal) policy often forbids putting private/sensitive documents into
cloud AI tools like ChatGPT or Claude, because of leak and privacy risk. But local
AI models running on a laptop aren't good enough for real work. We want the quality
of a cloud model without exposing sensitive data to it.

## The plan

Redact sensitive information **locally, on your own machine**, before anything goes
to a cloud AI — then un-redact the AI's reply afterward, so you keep the benefit of
a strong model without it ever seeing the real data.

### How it works

1. You give it a document, or a whole folder of hundreds of documents (Word, PDF,
   spreadsheets, plain text).
2. It scans each one and finds sensitive things — names, emails, phone numbers, ID
   numbers, company-specific terms — using **Presidio**, a free open-source
   PII-detection/anonymization library from Microsoft built for exactly this.
3. Each sensitive item is replaced with a safe placeholder (e.g. "John Smith" →
   `PERSON_00123`), and the real value is saved in a private local database
   (SQLite) that never leaves the machine.
4. The now-safe, redacted document can be used with any AI — ChatGPT, Claude,
   whatever — either by pasting it in yourself, or through a purpose-built local
   web interface (adapting the open-source **OpenWebUI** project) that automates
   the redact/un-redact steps.
5. When the AI replies, placeholders in its answer are swapped back to real values
   automatically, so the final answer looks normal — but the AI itself never saw
   the real data.

### Key design decisions so far

- The mapping database (fake ↔ real value) stays 100% local. It is the one thing
  that must never leave the machine.
- Must work **standalone**, independent of any custom UI — redact a document, then
  paste it directly into ChatGPT's or Claude's website (or any other AI), no
  integration required.
- Must also support a more automated path via a local web interface (OpenWebUI
  fork) that redacts prompts and un-redacts responses transparently, across
  multiple providers (Claude, ChatGPT, etc.).
- Must reliably batch-process hundreds of files at once, across mixed file types
  (txt/md, docx/pdf, csv/spreadsheets).
- Must be robust and simple enough for a non-technical user to use day to day.

### Planned build order

1. **Redaction engine** (Presidio-based) — detection, consistent pseudonymization,
   local SQLite mapping store, batch processing across file types. Useful
   standalone before any UI exists.
2. **Un-redaction (reveal) layer** — takes AI response text and restores real
   values from the mapping DB.
3. **Frontend/integration** — OpenWebUI fork with a redact/unredact toggle wired
   into the chat pipeline for multiple providers.

### Open questions (design still in progress)

- Exact entity types / recognizers Presidio should run for this use case, plus any
  custom recognizers needed for non-obvious sensitive data (company-specific
  terms, ID formats).
- How consistency is maintained across a whole document (and across a whole batch
  of files) so the same real-world entity always maps to the same placeholder.
- File-format handling specifics for docx/pdf/csv (formatting/layout
  preservation vs. plain-text extraction).
- UX for the non-technical user: how review/approval of a redaction
  before sending happens, and how "reveal" works without exposing the mapping DB.

The approved spec is `docs/specs/2026-07-17-local-redaction-tool-design.md`.
These notes are kept as earlier context and are not authoritative.
