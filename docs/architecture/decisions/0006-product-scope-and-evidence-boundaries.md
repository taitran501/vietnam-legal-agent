# ADR 0006: Product scope and evidence boundaries

- **Status:** accepted
- **Context:** the current product is a selected-domain Vietnamese legal
  assistant backed by versioned legal corpora. EPR remains a first-class
  domain, while civil/contracts, labor, corporate, land, and traffic workflows
  now share the same bounded agent boundary. Upload/OCR, historical-law
  selection, and additional legal domains introduce new provenance, retention,
  effective-date, and legal review obligations that each corpus contract must
  represent.
- **Decision:** keep the product bounded to explicitly supported legal domains.
  User-entered case facts are typed, labelled as user-provided, and never
  treated as independent legal evidence. The export is a preliminary text
  report for internal cross-checking, not a formal legal document. Missing
  source metadata is shown as missing instead of inferred. Do not expose
  another legal domain until it has a versioned evidence contract and release
  gate.
- **Consequence:** the missing features are documented scope boundaries rather
  than hidden gaps in the current UI. A later implementation must add its own
  tests for provenance, access control, effective dates, and safe-stop behavior
  before exposing the capability.
