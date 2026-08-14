# ADR 0005: V3/V4 retirement boundary

- **Status:** accepted
- **Context:** V4 is the bounded workflow for the current case-facing product,
  while the repository still contains the older graph/runtime path used by
  compatibility and non-case flows. Removing both paths in one change would
  make the release riskier and would invalidate existing contracts.
- **Decision:** V4 owns new case assessment, checklist, evidence-gated legal
  answers, persistence, and browser acceptance. The legacy path is a
  compatibility boundary only. New features must not add new direct calls to
  the legacy graph; they must enter through the typed workflow/API contracts.
  The CI and acceptance status must name which boundary they exercise.
- **Retirement criteria:** remove the legacy path only after route coverage,
  replay/history compatibility, deterministic evaluation, and production
  telemetry show no remaining consumer. A future removal is a separate,
  commit-scoped migration rather than an implicit part of a product patch.
- **Consequence:** V3/V4 coexistence is now an explicit migration boundary,
  not an undocumented claim that the architecture is already unified. This
  keeps the current release bounded while preventing further architectural
  drift.
