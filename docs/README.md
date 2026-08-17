# Architecture and Operational Documentation

This is the documentation index for EPR Compliance Copilot. The application assists with research and preliminary assessment of Vietnamese Extended Producer Responsibility (EPR) regulations; this documentation does not constitute official legal text or formal legal advice.

## Sources of Truth

- **Behavior Contract:** [pipeline_v4_behavior_contract.md](pipeline_v4_behavior_contract.md) defines the backend behavior that must remain stable.
- **Autonomous Agent Contract:** [autonomous-agent-architecture.md](architecture/autonomous-agent-architecture.md) specifies the ReAct cognitive loop, tool registry, budget control, and trajectory harness.
- **Domain Contract:** Source code in `src/epr_agent/domain/`, particularly `v4.py` and `epr_rules.py` (`CaseFormResolver`), is the sole source of truth for fields, dependencies, validation, and case states. The route `backend/api/routes/case_form.py` is a side-effect-free HTTP adapter.
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
- [Architectural Decision Records (ADRs)](architecture/decisions/)

### Retrieval and Behavior

- [V4 Behavior Contract](pipeline_v4_behavior_contract.md)
- [V4 Test Matrix](v4_test_matrix.md)
- [RAG Pipeline](rag_pipeline.md)
- [Retrieval Guide](retrieval/README.md)

### Operations & Runbooks

- [Local Preview](runbooks/local-preview.md)
- [Database Migration](runbooks/database-migration.md)
- [Production Promotion](runbooks/production-promotion.md)
- [Rollback Runbook](runbooks/rollback.md)

### Acceptance & Quality

- [Current Acceptance Status](acceptance_status.md) — working-tree remediation status
- [Guided User Experience Acceptance](browser_acceptance_report_guided_user_experience.md) — latest committed guided-UX snapshot
- [Browser Acceptance Report](browser_acceptance_report.md) — historical browser/API snapshot
- [V4 Acceptance Report](pipeline_v4_acceptance_report.md) — historical V4 pipeline snapshot
- [Baseline Acceptance Report](acceptance_report.md) — historical baseline snapshot

Mermaid diagrams are embedded directly in Markdown files for inline GitHub rendering and peer review.
