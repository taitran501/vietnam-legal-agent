# Bounded agentic workflow

The refactor keeps `backend/` and its original tests as the regression
baseline, while the application boundary moves to `src/epr_agent/`.

```text
request
  -> load recent conversation history + active case
  -> classify task
  -> rewrite dependent follow-up into a retrievable query
  -> [legal_lookup only] scoped answer-cache lookup
  -> FAQ retrieval
  -> legal hybrid retrieval
  -> deterministic evidence check
  -> EPR-only web fallback when the corpus is insufficient
  -> compose answer / assessment / checklist
  -> citation verification
  -> one repair or safe stop
```

The first workflow supports three tasks:

- `legal_lookup`: a standalone legal question. Its corpus-backed answer may be
  cached using task type, standalone query and corpus version.
- `assess_epr_obligation`: a case-specific preliminary assessment. It requires
  explicit business role, product or packaging, and material facts.
- `build_compliance_checklist`: a case-specific checklist with the same required
  facts. Assessment and checklist output are never answer-cache entries.

`case_states` stores only the active structured case needed to resume a
follow-up. It is not a long-term user profile. `agent_runs` records the trace
id, action sequence, tool latency and termination reason. Local development uses
the existing SQLite path; setting `DATABASE_URL` to a PostgreSQL URL selects the
production adapter.

The planner can record only the actions in `epr_agent.domain.models.Action`.
The graph allows at most three retrieval actions and one answer repair. It does
not call web search to fill missing business facts, and it does not return an
assessment or checklist without evidence and citations.

## Local development

Install the package in editable mode so the `src` layout is available to the
legacy FastAPI entry point:

```powershell
python -m pip install -e ".[dev]"
```

The existing `backend/core/pipeline.py` remains available for the 33-case
legacy evaluation and comparison. The `/api/v1/chat` route now presents the new
workflow while preserving the existing request fields and SSE event types.
