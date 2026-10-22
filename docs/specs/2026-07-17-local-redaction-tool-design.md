# Local Document Redaction Tool — Design Spec

Status: approved 2026-07-17. Ready for implementation planning.

## Problem

Some documents should not be pasted into a cloud AI tool. Policy,
confidentiality, and ordinary caution all point the same way, and a small
local model is often not strong enough for the actual work. The goal is
cloud-model quality without sending the original document to a cloud
provider.

## Users

Primary user: non-technical, working with mixed Hungarian and English
documents (legal, financial, and general business material). A separate
technical person sets the tool up and maintains it; the primary user runs
it day to day.

## Goals

- Redact sensitive information locally before it reaches any cloud AI, and
  reliably restore it in the AI's response afterward.
- Work standalone (paste redacted text/files directly into ChatGPT's or
  Claude's own website) with zero dependency on any custom integration.
- Also work as an integrated chat experience (fork of OpenWebUI) that redacts
  and unredacts automatically across multiple providers.
- Let the user control what gets redacted beyond defaults — including
  company-specific terms, codenames, and colleague names that generic NER
  won't catch.
- Handle batches of hundreds of files across mixed formats — plain text/
  markdown, Word (.docx), PDF, Excel (.xlsx) and CSV, PowerPoint (.pptx), and
  email files (.eml/.msg, including Outlook exports) — reliably.
- Be simple enough for a non-technical executive to use without hand-holding
  after initial setup.

## Non-goals

- Not building a general-purpose chat client feature set beyond what OpenWebUI
  already provides.
- Not attempting perfect (100%) automatic entity recall without human review —
  the design assumes and supports human review instead of promising
  unattainable automation.
- Not handling legal/compliance questions around insider information or
  market-moving data — this tool only addresses the technical leak-prevention
  problem, not corporate disclosure policy.

## Architecture

One shared **redaction core** (local service/library), consumed by two
independent front ends that share the same database and settings:

```
                    Redaction Core
              (Presidio + custom recognizers
               + Hungarian/English NLP models)
                          |
                 Local SQLite DB (encrypted,
                 global mapping + term list)
                    /                  \
      Standalone App              OpenWebUI (forked)
   (Redact/Reveal, no          (auto redact-before-send /
   provider connection)         unredact-after-receive,
                                 multi-provider)
```

Both front ends call the same core, so a term added or a category toggled in
one applies everywhere.

## Redaction engine (core)

- **Presidio** (`presidio-analyzer` + `presidio-anonymizer`) as the
  detection/replacement framework.
- **Bilingual NLP**: an English spaCy model (`en_core_web_lg`) plus a
  Hungarian-capable model (HuSpaCy, or a multilingual transformer NER as
  fallback), both run per document rather than selected by a language flag —
  mixed-language documents get both passes.
- **Category toggles**: checkboxes for built-in entity types (person names,
  organizations, financial amounts, dates, addresses, emails, phone numbers,
  national ID/tax numbers), each independently on/off and fully
  user-customizable. Default state is not "everything on": person names,
  organizations, emails, phone numbers, addresses, and national ID/tax
  numbers default **on**; financial amounts and dates default **off**: those
  are frequently needed as context for the AI to give useful analysis (e.g.
  reviewing a financial report), and are lower-identifying in isolation than
  a name or ID number. The user can turn either on per document or globally
  at any time. Toggle state is shared and consistent across both front ends.
- **Custom term list**: a persistent, editable list (e.g. "Acme Corp",
  "Project Falcon", specific colleague names) stored in the shared DB, always
  redacted regardless of NER confidence.
- **Consistent pseudonymization**: every real value maps to one stable
  placeholder ID (`PERSON_00123`, `ORG_00007`) across an entire document and
  across a whole batch run.
- **Batch mode**: point it at a folder, it walks all files (txt/md, docx, pdf,
  xlsx/csv, pptx, eml/msg), produces a mirrored folder of redacted copies plus
  a summary report (entity counts per file) for review. Per-format handling:
  docx/pptx are parsed structurally (redact text, keep formatting/layout
  intact); xlsx is redacted cell-by-cell (values and formula results, not
  formulas themselves — a redacted formula would break the sheet); eml/msg
  are parsed to redact body text and headers (sender/recipient/subject)
  separately, since headers often carry names and emails that body-only
  scanning would miss; attachments inside .msg/.eml are treated as their own
  files and run through the same per-format pipeline recursively.

## Data model

Single local SQLite DB, encrypted at rest (SQLCipher), passphrase set on
first run:

- `entities`: placeholder ID ↔ real value ↔ entity type ↔ first-seen
  document. Global, permanent — kept indefinitely, manual purge only (no
  auto-expiry, per decision).
- `custom_terms`: persistent redact-always list, user-editable.
- `settings`: category toggle state, shared by both front ends.
- Manual "wipe everything" control available in both UIs.

## Standalone app

Minimal local web app, two primary actions:

- **Redact**: drop a file or folder → review screen (highlighted entities,
  editable; on by default, can be turned off per decision) → confirm →
  redacted copy, ready to paste/upload into ChatGPT's or Claude's website
  directly.
- **Reveal**: paste an AI reply → real values substituted back in via the
  local mapping DB.
- Settings page for category toggles + custom term list, shared with the
  OpenWebUI side.
- Makes no outbound network call to any AI provider — no standing connection,
  smallest possible attack surface for this half of the system.

## OpenWebUI integration

A forked OpenWebUI with a redaction middleware layer:

- Before a message/document is sent to any configured provider (Claude,
  ChatGPT, others OpenWebUI already supports), it passes through the same
  redaction core.
- The response passes back through the reveal step before being displayed.
- A visible per-chat toggle ("Redaction: ON") so it is never silently off,
  plus the same review screen as the standalone app before first send in a
  conversation (respecting the on-by-default review setting).
- Requires storing provider API keys locally in the OpenWebUI instance
  (standard OpenWebUI behavior) — accepted trade-off for the smoother
  experience.

## Security posture

- DB encrypted at rest; passphrase never stored in plaintext — prompted per
  session, or held in the OS keychain if available.
- Both front ends bind to `localhost` only by default.
- No telemetry. No external calls except the deliberate provider calls from
  OpenWebUI (after redaction has already run) and OpenWebUI's own update
  checks, which should be disabled explicitly for this deployment.

## Security & compliance (enterprise review gaps)

A design-time review against typical enterprise security review standards
(not a tested/audited claim — see Testing approach) found the overall
local-first architecture sound, but identified gaps that must be closed
before this is genuinely enterprise-deployable, not just safer than pasting
raw documents into a public chatbot:

**To be designed and built in:**

- **App-level authentication**, not just DB encryption. `localhost`-only
  binding stops remote attackers, not local ones (malware, another logged-in
  user, a compromised browser extension on the same machine). The app itself
  must require the passphrase to open, not just to decrypt the DB.
- **API keys in the OS keychain** (Windows Credential Manager / macOS
  Keychain), not a plaintext OpenWebUI config file. Inject via environment
  variable from the keychain at process start rather than storing on disk.
- **Tamper-evident audit log**: append-only, hash-chained local log of every
  redact/reveal action (what document, what categories, when) — expected by
  any real security review of sensitive material.
- **Dependency scanning process** for the OpenWebUI fork: run Trivy or Snyk
  against its dependency tree before each release, and document who owns
  tracking upstream CVEs and the update cadence.
- **Secure temp-file handling**: process documents in an encrypted or tmpfs
  working directory during redaction, scrub plaintext intermediates after
  use rather than leaving them on disk.

**Managed, not eliminable — state plainly, do not oversell as "fixed":**

- **Third-party code risk.** Forking a large, actively-developed project
  (OpenWebUI) means trusting a codebase not written in-house. Scanning and
  pinning reduces this; it does not remove the risk category. Normal and
  acceptable with a real dependency-management process, same as any
  enterprise software built on open source.
- **Compromised-endpoint risk.** If the laptop itself is compromised, nothing
  running on it — this tool included — is fully safe. Secure temp handling
  reduces blast radius; it cannot eliminate this risk category.

**Open question, not a design fix — verify before implementation starts:**
whether the target machine's corporate IT policy even permits Docker Desktop
installation. Some corporate endpoint policies block it outright. If blocked,
packaging needs to shift to a native installer instead of Docker Compose —
confirm with IT before committing engineering time to the Docker path.

## Packaging & deployment

- Docker Compose bundle (core + SQLite + OpenWebUI fork + standalone app),
  works identically via Docker Desktop on Windows or macOS.
- Runs entirely on the primary user's own work laptop/desktop — not on any
  third party's infrastructure.
- The deployer performs one-time setup on the machine; day-to-day use is a
  single shortcut/icon opening `localhost` in the browser.

## Error handling

- If NLP detection fails on a file (corrupt PDF, unsupported format), it is
  flagged as skipped in the batch report — never silently passed through
  un-redacted.
- If the DB is locked or corrupted, both front ends fail closed (block
  sending) rather than fail open.

## Testing approach

- Unit tests on the redaction core against a synthetic corpus of Hungarian +
  English documents with known-planted entities (names, IBANs, tax IDs,
  company codenames) to measure recall.
- Batch-mode test against a large synthetic folder (hundreds of files, mixed
  formats) for robustness/performance.
- Manual review-screen walkthrough for the review-before-send UX.

## Build order

1. Redaction engine (core) — usable standalone via CLI/API even before any UI.
2. Standalone app (Redact/Reveal, review screen, batch mode).
3. OpenWebUI fork + middleware integration.

## Deferred decision: secondary local-model verification pass

Presidio's NER + regex detection has real gaps for this risk level: it can't
catch context-dependent sensitive content that doesn't match a named entity
(e.g. "the deal with our northern competitor"), and Hungarian NER recall is
weaker than English. A secondary pass — a small local LLM re-reading the
document holistically and flagging additional candidates for the review
screen — would help close that gap, but is **not part of the initial build**.

Constraint driving this: the target laptop has 8GB RAM and needs to run this
tool alongside normal work apps (Office, Outlook/Teams, browser). A model
capable of decent open-ended judgment (7-8B class) doesn't fit that budget
even quantized; a model that does fit (1-2B class) is only reliable for
narrow, closed-form tasks (per-sentence "possibly sensitive, yes/no"
classification for review-screen highlighting), not open-ended review, and
would need to run on-demand (loaded only during a redaction job, unloaded
after) rather than resident alongside other apps.

Decision on whether to add this, and at what model size/scope, is deferred
until after the core engine, standalone app, and OpenWebUI integration are
built and their real-world detection recall against actual documents can be
measured. If gaps remain after the custom term list and category tuning,
revisit this as a follow-on phase.
