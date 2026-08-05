# Legal EPR Assistant

Legal EPR Assistant is a Vietnamese legal-information system for questions
about Extended Producer Responsibility (EPR), the Vietnamese Environmental
Protection Law, and Decree 08/2022/ND-CP.

The repository contains both the original RAG chatbot and a bounded agentic
workflow refactor. The refactor keeps the existing API contract while making
task detection, evidence checks, follow-up questions, and termination rules
explicit.

> This system provides document-grounded information, not legal advice.

## Current workflow

```text
request
  -> load recent conversation context and active case
  -> classify the task
  -> rewrite a dependent follow-up when needed
  -> answer-cache lookup for standalone legal lookup only
  -> FAQ retrieval
  -> hybrid legal retrieval
  -> evidence evaluation
  -> EPR-scoped web fallback when the corpus is insufficient
  -> compose an answer, assessment, or checklist
  -> verify citations
  -> repair once or stop safely
```

The bounded workflow supports these tasks:

- `legal_lookup`: answer a standalone question from the legal corpus.
- `assess_epr_obligation`: produce a preliminary case assessment after the
  required business facts are available.
- `build_compliance_checklist`: produce an evidence-linked checklist.
- `chitchat`: handle greetings and non-legal conversation without retrieval.

The planner can record only a fixed set of actions. A run is limited to three
retrieval actions and one answer repair. The workflow does not invent missing
business facts and does not return a case assessment or checklist without
evidence and citations.

## Retrieval

- FAQ retrieval uses Qdrant dense search over the FAQ collection, a Vietnamese
  keyword-overlap boost, a score threshold, and a top-candidate margin check.
  Strict FAQ matches may be reranked before returning one answer.
- Legal retrieval runs dense Qdrant search and a lightweight BM25-style
  lexical search in parallel. Their candidates are merged, deduplicated, and
  reranked with the current heuristic reranker. The default legal path returns
  up to ten documents from a candidate pool controlled by `rerank_top_n`.
- Evidence checks require source metadata and enough retrieved content. An
  optional relevance checker can add a semantic/LLM gate.
- Web search is used only as an EPR-scoped fallback after corpus retrieval is
  insufficient. It is not used to fill missing facts about a business.

See [docs/rag_pipeline.md](docs/rag_pipeline.md) for the detailed retrieval
and indexing contract.

## History, case state, and cache

- Conversation history is durably stored in local SQLite at
  `data/chat_history.sqlite3`; the file is ignored by Git.
- Each run loads only recent messages plus a short summary. This is the
  context window for the current conversation, not a general user-profile
  memory.
- An active case stores structured facts needed to resume an assessment or
  checklist across turns. It is separate from chat history.
- Redis is used for hot session context, answer caching, rate limiting, and
  cache TTLs. Only `legal_lookup` answers are eligible for the bounded answer
  cache; case assessments and checklists are not.
- Local case state and run traces use SQLite. Setting `DATABASE_URL` to a
  PostgreSQL URL selects the PostgreSQL case/trace adapter for deployment.

## Repository layout

```text
backend/                 Existing FastAPI services and legacy RAG components
src/epr_agent/           Bounded workflow, domain models, tools, and adapters
data/                    Source FAQ/law data and local runtime database path
scripts/                 Indexing, ingestion, audit, and migration utilities
tests/                   Unit, integration, regression, and trajectory tests
docs/                    English architecture and acceptance documents
frontend/                Streamlit UI used by the Docker Compose deployment
frontend-react/          React/TypeScript UI using the same API contract
```

`backend/` remains available as the regression baseline. The `/api/v1/chat`
route now presents the workflow in `src/epr_agent/` while preserving the
legacy request fields and SSE event types.

## Local setup

Requirements: Python 3.11, Node.js 18+ for the React UI, Redis, and a local
or hosted Qdrant instance. OpenAI is used for embeddings and generation;
Tavily is optional for web fallback.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Set the required API keys and service URLs in `.env`. Do not commit `.env` or
any database, cache, Qdrant, or log files.

Build the legal index when the corpus changes:

```powershell
python -m scripts.build_index
```

Start the backend:

```powershell
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Start the React UI in a second terminal:

```powershell
Set-Location frontend-react
npm install
npm run dev
```

The Streamlit UI can be started with:

```powershell
python -m pip install -r requirements/frontend.txt
streamlit run frontend/app.py --server.port 8501
```

## API and events

The main endpoint is `POST /api/v1/chat`. It accepts `query` and either
`conversation_id` or the legacy `session_id`. The response is an SSE stream
with the existing `status`, `response_chunk`, `response_complete`, and `error`
events. New workflow progress is exposed through `workflow_step`; completed
responses may include task type, assessment, checklist, assumptions, missing
facts, citations, trace ID, and termination reason.

Other useful endpoints include `/api/v1/health`, the session endpoints under
`/api/v1/sessions`, and `/metrics` for Prometheus-compatible metrics.

## Tests and acceptance

Run the local suite with:

```powershell
pytest -q
ruff check src tests
mypy src/epr_agent
```

The latest local acceptance is recorded in
[docs/acceptance_report.md](docs/acceptance_report.md). It covers the legacy
regression suite, bounded-workflow unit tests, trajectory tests, static checks,
and the React build. Live OpenAI, Qdrant, Redis, and Tavily evaluation must be
run separately when those services are available.

## Deployment notes

`docker-compose.yml` retains the Redis, FastAPI, Streamlit, and Nginx
deployment definitions. Its backend image still follows the legacy copy
layout, so update the image to install and copy `src/epr_agent/` before
deploying the new workflow through Docker. For production, use managed
PostgreSQL for case state and workflow traces, managed Qdrant for the legal
index, and managed Redis for cache/rate limiting. Run database migrations and
index versioning as part of deployment rather than committing generated
runtime artifacts.

## License

MIT
