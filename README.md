# EPR Compliance Copilot

EPR Compliance Copilot is a Vietnamese legal-compliance assistant for
Extended Producer Responsibility (EPR). It is a bounded workflow, not an
open-ended tool-using agent: it can look up legal sources, make a preliminary
EPR assessment, or build an evidence-linked compliance checklist.

> The application provides document-grounded information, not legal advice.

## Workflow

```text
request
  -> load recent conversation context and active case
  -> structured task understanding
  -> ask for missing required facts, or retrieve evidence
  -> FAQ retrieval -> hybrid legal retrieval -> EPR-only web fallback
  -> compose answer, assessment, or checklist
  -> verify citations -> repair once or stop safely
```

Supported tasks are `legal_lookup`, `assess_epr_obligation`, and
`build_compliance_checklist`. The planner has a closed action set, a maximum of
three retrieval actions, and at most one citation-repair attempt. It never uses
web search to infer company facts and never returns an assessment or checklist
when required facts or supported evidence are missing.

## Retrieval and safety

- FAQ matching uses dense retrieval, keyword support, a threshold, and a
  top-result margin check.
- Legal retrieval combines Qdrant dense search with BM25-style lexical search,
  then merges, deduplicates, and reranks candidates.
- Evidence and citation checks block unsupported legal claims. Web search is an
  explicitly labelled, EPR-scoped fallback only when the corpus is insufficient.
- The candidate structure-aware index splits legislation by `Điều -> Khoản -> Điểm`
  and retains parent-article, hierarchy, offset, and source-text metadata.
- The audited candidate collection passed the same live 16-query gate as the
  baseline: P@1/NDCG@3/Recall@5 `0.9375` and explicit-article hit@3 `1.0`.

See [the retrieval protocol](docs/retrieval/README.md) before creating or
promoting an index.

## Persistence and cache

SQLAlchemy is the single repository for `users`, `conversations`, `messages`,
`conversation_summaries`, `case_states`, and `agent_runs`. PostgreSQL is the
production source of truth; SQLite uses the same schema for local development.
The API-key hash scopes each record owner.

Recent messages and a compact conversation summary provide short-term context.
An active case records only explicit facts for the current assessment or
checklist; it is not a long-term user profile. Redis is limited to answer cache,
hot context, rate limits, and short-lived feedback. Only independent,
corpus-backed `legal_lookup` answers are cacheable.

## Interfaces

`POST /api/v1/chat` accepts `query` and the canonical `conversation_id`; the
legacy `session_id` remains supported. Existing SSE event types remain:
`status`, `response_chunk`, `response_complete`, and `error`. The additional
`workflow_step` event is optional for older clients.

The React workspace is the primary UI. It includes conversation history, chat,
workflow progress, an editable Case Facts panel, evidence/citation cards,
assessment output, and a checklist. React is the only runtime frontend; the
retired Streamlit implementation remains recoverable from `legacy-v1.0.0`.

## Local development

Requirements: Python 3.11, Node.js 18+, Redis, and Qdrant. PostgreSQL is
recommended when exercising the production persistence path.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

The cross-encoder is optional and is not installed in the normal API image:

```powershell
python -m pip install -e ".[cross-encoder]"
```

In another terminal:

```powershell
Set-Location frontend-react
npm install
npm run dev
```

For the container stack, set the required secrets in `.env` and run:

```powershell
docker compose up --build
```

This starts React, FastAPI, PostgreSQL, Redis, and Qdrant. The backend applies
the Alembic migration at startup. Do not commit `.env`, SQLite databases,
Qdrant storage, logs, or cache files.

## Tests

Run verification manually from the project virtual environment. This repository
does not define a CI/CD workflow.

```powershell
pytest -q
ruff check src/epr_agent tests/agent tests/trajectory tests/tools
mypy src/epr_agent

Set-Location frontend-react
npm run test
npm run build
npm run test:e2e
```

The committed source baseline records 49 FAQ entries and 178 legal records in
[docs/retrieval/baseline_manifest.json](docs/retrieval/baseline_manifest.json).
Named local Qdrant baseline and candidate results, collection audits, and the
promotion decision are committed under [docs/retrieval](docs/retrieval/README.md).
Run the 33-case live golden evaluation manually when needed because generated
answer text and latency depend on the configured model service.

## Design handoff

The reviewed Stitch export is preserved as
[`stitch_legal_assistant_system.zip`](docs/design/stitch_legal_assistant_system.zip),
and [the selection record](docs/design/stitch_selection.md) explains which
screens, responsive states, drawers, and interaction patterns were implemented.
Visible product copy is Vietnamese; repository documentation is English.

## License

MIT
