# Architecture and Operational Documentation

This is the documentation index for Vietnam Legal Agent. The application uses
one legal-chat workflow for questions about topics represented in its selected
sources. The local preview corpus is content-locked and based on a Ministry of
Justice snapshot and the tracked UTS_VLC input; it does not cover Vietnamese law
in full. Optional retrieval adapters are disabled by default, and the generated
corpus is not included in the production release. This documentation is not
official legal text or formal legal advice.

## Sources of Truth

- **Behavior Contract:** [pipeline_v4_behavior_contract.md](pipeline_v4_behavior_contract.md) defines the backend behavior that must remain stable.
- **Autonomous Agent Contract:** [autonomous-agent-architecture.md](architecture/autonomous-agent-architecture.md) specifies the ReAct cognitive loop, tool registry, budget control, and trajectory harness.
- **Domain Contract:** Source code in `src/vietnam_legal_agent/domain/` defines legal topics, routing hints, evidence contracts, and conversation state. Follow-up context is carried in ordinary chat turns.
- **API Contract:** Pydantic schemas in `backend/api/schemas.py` and routes in `backend/api/routes/` serve as the public request/response contract.
- **UI Contract:** Components and tests in `frontend-react/src/` define ordinary chat, three optional intent shortcuts, and source display. No domain-specific intake form is part of the current flow.
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
- [Historical ADR 0001: Inline Guided Form](architecture/decisions/0001-inline-guided-form.md) (superseded)
- [Historical ADR 0003: Atomic Guided Submit](architecture/decisions/0003-atomic-guided-submit.md) (superseded)
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
- [Production Readiness Audit](runbooks/production-readiness-audit.md) — current evidence and external blockers
- [Live Agent Evaluation](runbooks/live-agent-eval.md) — protected provider-backed pilot gate
- [Rollback Runbook](runbooks/rollback.md)
- [External Release Gates](runbooks/external-release-gates.md)

### Acceptance & Quality

- [Portable legal-source verifier skill](../skills/vietnam-legal-source-verifier/SKILL.md) — standalone official-source verification workflow
- [Corpus attribution and licenses](retrieval/corpus-attribution.md) — license and source terms for each included corpus input
- [Historical Acceptance Snapshot](acceptance_status.md) — commit-scoped evidence; current workflow triggers are listed separately
- [Replay and Quality Triage](evaluation/replay-and-triage.md) — engineering replay, provenance, and feedback contracts; not legal ground truth
- [Guided User Experience Acceptance](browser_acceptance_report_guided_user_experience.md) — latest committed guided-UX snapshot

### Design

- [Stitch UI Selection](design/stitch_selection.md) — adopted design screens and patterns

Mermaid diagrams are embedded directly in Markdown files for inline GitHub rendering and peer review.
