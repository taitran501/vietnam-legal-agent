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
assessment output, and a checklist. The legacy Streamlit source is retained
only as a reference while the React deployment is validated. Run
`docker compose --profile legacy up frontend-legacy` to start it separately;
it is not part of the default proxy path.

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

```powershell
pytest -q
ruff check src/epr_agent tests
mypy src/epr_agent

Set-Location frontend-react
npm run test
npm run build
npm run test:e2e
```

The committed source baseline records 49 FAQ entries and 178 legal records in
[docs/retrieval/baseline_manifest.json](docs/retrieval/baseline_manifest.json).
It is a corpus manifest, not a live retrieval-quality claim. Live Qdrant,
OpenAI, Redis, Tavily, and container integration must be measured separately
before release.

## Design handoff

The English Stitch prompt pack and design tokens are in
[docs/design](docs/design/README.md). Visible product copy is Vietnamese. A
Stitch export URL and screenshots still require explicit design review before
they can be claimed as approved design artifacts.

## License

MIT
