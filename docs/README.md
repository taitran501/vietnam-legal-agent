# Architecture and Operational Documentation

This is the documentation index for Vietnam Legal Agent. The application
supports preliminary research and assessment across selected Vietnamese legal
domains: civil/contracts, labor, corporate, land, traffic, and EPR (Environmental
Producer Responsibility). This documentation does not constitute official legal
text or formal legal advice.

## Sources of Truth

- **Behavior Contract:** [pipeline_v4_behavior_contract.md](pipeline_v4_behavior_contract.md) defines the backend behavior that must remain stable.
- **Autonomous Agent Contract:** [autonomous-agent-architecture.md](architecture/autonomous-agent-architecture.md) specifies the ReAct cognitive loop, tool registry, budget control, and trajectory harness.
- **Domain Contract:** Source code in `src/epr_agent/domain/`, particularly `v4.py`, `legal_rules.py` (multi-domain rules and `UniversalCaseFormResolver`), and `epr_rules.py` (EPR-specific `CaseFormResolver` and rule pack), is the source of truth for fields, dependencies, validation, and case states. The route `backend/api/routes/case_form.py` is a side-effect-free HTTP adapter.
- **API Contract:** Pydantic schemas in `backend/api/schemas.py` and routes in `backend/api/routes/` serve as the public request/response contract.
- **UI Contract:** Components and tests in `frontend-react/src/` define the guided user journey.
- **Release Evidence:** Acceptance reports record strictly verified commits and environments.
- **Repository Hygiene:** Binary design exports and raw audit dumps are kept outside Git-tracked documentation; only summarized contracts, architectural decisions, and acceptance evidence are maintained.

## Documentation Map

### Architecture

- [System Overview](architecture/system-overview.md)
- [Autonomous Agent Architecture & Evaluation Harness](architecture/autonomous-agent-architecture.md)
- [Guided User Flows](architecture/guided-user-flows.md)
- [Domain Model](architecture/domain-model.md)
- [Testing Strategy](architecture/testing-strategy.md)
- [Architectural Decision Records](architecture/decisions/)
  - [ADR 0001: Inline Guided Form](architecture/decisions/0001-inline-guided-form.md)
  - [ADR 0002: Backend Field Contract](architecture/decisions/0002-backend-field-contract.md)
  - [ADR 0003: Atomic Guided Submit](architecture/decisions/0003-atomic-guided-submit.md)
  - [ADR 0004: Progressive Technical Metadata](architecture/decisions/0004-progressive-technical-metadata.md)
  - [ADR 0005: V3/V4 Retirement Boundary](architecture/decisions/0005-v3-v4-retirement-boundary.md)
  - [ADR 0006: Product Scope and Evidence Boundaries](architecture/decisions/0006-product-scope-and-evidence-boundaries.md)

### Retrieval and Behavior

- [V4 Behavior Contract](pipeline_v4_behavior_contract.md)
- [V4 Test Matrix](v4_test_matrix.md)
- [RAG Pipeline](rag_pipeline.md)
- [Retrieval Guide](retrieval/README.md)
- [Universal Corpus](retrieval/universal-corpus.md)

### Operations & Runbooks

- [Local Preview](runbooks/local-preview.md)
- [Database Migration](runbooks/database-migration.md)
- [Production Promotion](runbooks/production-promotion.md)
- [Live Agent Evaluation](runbooks/live-agent-eval.md) — protected provider-backed pilot gate
- [Rollback Runbook](runbooks/rollback.md)
- [External Release Gates](runbooks/external-release-gates.md)

### Acceptance & Quality

- [Current Acceptance Status](acceptance_status.md) — commit-scoped verification for the current `main`
- [Replay and Quality Triage](evaluation/replay-and-triage.md) — engineering replay, provenance, and feedback contracts; not legal ground truth
- [Guided User Experience Acceptance](browser_acceptance_report_guided_user_experience.md) — latest committed guided-UX snapshot
- [Browser Acceptance Report](browser_acceptance_report.md) — historical browser/API snapshot
- [V4 Acceptance Report](pipeline_v4_acceptance_report.md) — historical V4 pipeline snapshot
- [Baseline Acceptance Report](acceptance_report.md) — historical baseline snapshot

### Design

- [Stitch UI Selection](design/stitch_selection.md) — adopted design screens and patterns

Mermaid diagrams are embedded directly in Markdown files for inline GitHub rendering and peer review.
