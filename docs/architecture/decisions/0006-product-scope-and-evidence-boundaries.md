# ADR 0006: Product Scope and Evidence Boundaries

- **Status:** superseded by the general legal-chat workflow (2026-09-30)
- **Context:** The product previously split Vietnamese legal topics into separately bounded workflows. Users now ask ordinary legal questions across topics using a shared multi-domain source and verification path. Upload/OCR, historical-law selection, and additional source collections still require provenance, retention, and effective-date metadata.
- **Decision:** Keep user-entered facts labelled as user-provided and never treat them as independent legal evidence. The export is a preliminary text report for internal cross-checking, not a formal legal document. Missing source metadata is shown as missing instead of inferred.
- **Consequence:** New source collections require tests for provenance, access control, effective dates, and answer verification before use.
