# ADR 0006: Product scope and evidence boundaries

- **Status:** accepted
- **Context:** the current product is an EPR legal assistant backed by a
  versioned corpus. Upload/OCR, historical-law selection, and multi-domain
  advice would introduce new provenance, retention, effective-date, and legal
  review obligations that the current corpus contract does not represent.
- **Decision:** keep the product explicitly EPR-only. User-entered case facts
  are typed, labelled as user-provided, and never treated as independent legal
  evidence. The export is a preliminary text report for internal
  cross-checking, not a formal legal document. Missing source metadata is shown
  as missing instead of inferred. Do not add upload/OCR, historical snapshots,
  or another legal domain until each has a versioned evidence contract and
  release gate.
- **Consequence:** the missing features are documented scope boundaries rather
  than hidden gaps in the current UI. A later implementation must add its own
  tests for provenance, access control, effective dates, and safe-stop behavior
  before exposing the capability.
