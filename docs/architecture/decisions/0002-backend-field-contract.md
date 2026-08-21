# ADR 0002: Backend is the Single Source for Field Dependencies and Validation

- **Status:** accepted
- **Context:** The frontend and V4 previously maintained divergent copies of required-field definitions, revenue limits, and conditional packaging fields.
- **Decision:** `CaseFormResolver` (`epr_rules.py`) is the pure service used by the resolve endpoint, session PATCH, and V4 runtime for EPR domain cases. All other domains use `UniversalCaseFormResolver` (`legal_rules.py`). The frontend only renders metadata and surfaces validation errors.
- **Consequences:** Rule changes happen in one place; the UI depends on the API contract and must preserve drafts when resolve errors occur.
- **Rejected:** Having the frontend infer field dependencies from a hard-coded list.
