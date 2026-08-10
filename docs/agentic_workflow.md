# Bounded agentic workflow

The refactor keeps `backend/` and its original tests as the regression
baseline, while the application boundary moves to `src/epr_agent/`.

```text
request
  -> load recent conversation history + active case
  -> structured task understanding
  -> rewrite a dependent follow-up into a retrievable query
  -> [legal_lookup only] scoped answer-cache lookup
  -> FAQ retrieval
  -> legal hybrid retrieval
  -> deterministic evidence check
  -> EPR-only web fallback when the corpus is insufficient
  -> compose answer / assessment / checklist
  -> citation verification
  -> one repair or safe stop
```

The workflow supports three substantive tasks plus bounded chitchat:

- `legal_lookup`: a standalone legal question. Its corpus-backed answer may be
  cached using task type, standalone query and corpus version.
- `assess_epr_obligation`: a case-specific preliminary assessment. It requires
  explicit business role, product or packaging, material, and activity-scope
  facts.
- `build_compliance_checklist`: a case-specific checklist with the same required
  facts. Assessment and checklist output are never answer-cache entries.

Task understanding produces a validated schema with `task_type`,
`is_follow_up`, `standalone_query`, explicit facts, and missing facts. Its model
output cannot select tools or transitions: the planner accepts only the
predeclared actions and falls back safely when structured output fails.

SSE progress is emitted from actual LangGraph node updates, not from a simulated
timer. Every `workflow_step` carries an ordered step number, closed action name,
status, and trace id before the final response is streamed.

`case_states` stores only the active structured case needed to resume a
follow-up. It is not a long-term user profile. `agent_runs` records the trace
id, action sequence, tool latency and termination reason. SQLAlchemy persists
users, conversations, messages, summaries, case states, and runs through one
repository. SQLite is the local adapter; PostgreSQL is the production source
of truth.

The planner can record only the actions in `epr_agent.domain.models.Action`.
The graph allows at most three retrieval actions and one answer repair. It does
not call web search to fill missing business facts, and it does not return an
assessment or checklist without evidence and citations.

The answer cache stores a versioned bundle containing the answer, evidence,
citations, and source. A cache hit is accepted only after the citations are
verified against its cached evidence. Only independent, corpus-backed
`legal_lookup` answers are eligible; case work and web answers are excluded.

## Local development

Install the package in editable mode so the `src` layout is available to the
legacy FastAPI entry point:

```powershell
python -m pip install -e ".[dev]"
```

The existing `backend/core/pipeline.py` remains available for the 33-case
legacy evaluation and comparison. The `/api/v1/chat` route now presents the new
workflow while preserving the existing request fields and SSE event types.
