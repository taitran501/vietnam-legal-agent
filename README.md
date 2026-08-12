# EPR Compliance Copilot

EPR Compliance Copilot is a Vietnamese legal-compliance assistant for
Extended Producer Responsibility (EPR). It is implemented as a bounded agent
workflow: the runtime can execute only declared routes, tools, and transitions.
It does not discover tools, invent company facts, or silently turn a missing
legal source into a confident answer.

The product is intentionally narrow today: the indexed legal corpus is EPR.
The domain contracts are separated from the retrieval and workflow core so
another legal corpus can be added later through a corpus descriptor and rule
pack.

> The application provides source-grounded information and preliminary
> assessments. It is not a substitute for professional legal advice.

## Current behavior

Pipeline V4 is the default runtime:

```text
official source
  -> canonical document and chunk audit
  -> Điều/Khoản/Điểm-aware indexing
  -> versioned Qdrant collection
  -> query understanding and route selection
  -> route-specific workflow
  -> exact-anchor + dense + BM25-style retrieval
  -> RRF merge and heuristic reranking
  -> evidence and issue-coverage gate
  -> structured result composition
  -> citation verification
  -> persistence, trace, and SSE presentation
```

The most important user-facing rules are:

- Quick actions only prefill the composer and select an editable intent. They
  never submit a request on their own.
- An assessment or checklist collects facts before it reaches a conclusion.
  Facts are shown with Vietnamese labels and their source is tracked as either
  the user message or the case panel.
- Missing information produces one clear follow-up question and a
  `needs_information` result. The case panel shows all remaining fields.
- A preliminary result is shown only after the required legal issues have
  evidence. Unsupported legal claims cannot finish as `answer_complete`.
- Web research is a separate, explicit user action. It is not an automatic
  fallback for missing company facts or weak legal evidence.
- FAQ data is retained for examples and evaluation only. It is not indexed,
  retrieved, cited, or used as runtime evidence.

## Declared routes

| Route | Purpose | Result | Cache |
| --- | --- | --- | --- |
| `legal_lookup` | Look up a provision or explicit Article | Cited legal answer | Verified standalone answers only |
| `legal_explain_compare` | Explain or compare provisions | Evidence-backed explanation | Never |
| `case_assessment` | Assess a company situation | Preliminary assessment or follow-up | Never |
| `compliance_checklist` | Prepare evidence-linked next steps | Checklist or follow-up | Never |
| `research_web` | Search public sources after user selection | Clearly separated research result | Never |
| `chitchat` | Greeting and small talk | Short conversational response | Never |
| `out_of_scope` | Request outside the registered corpus | Safe stop | Never |

The EPR case workflow currently collects facts such as business role, object
type, EPR product group, material or specification, market placement, activity
purpose, packaged-goods category, revenue thresholds, reuse, and effective
date. Required fields are provided by the backend case schema; the React panel
does not render database field names as user-facing labels.

## Legal corpus and retrieval

The canonical corpus is declared in `data/corpus_manifest.json`. Only records
that can be traced to an official source are eligible for legal evidence.
Structure-aware chunks preserve the document, heading hierarchy, Article,
Clause, Point, original text, offsets, corpus version, and provenance. Appendix
XXII table rows carry page and table provenance and must pass audit before the
index alias can be promoted.

The embedding contract is fixed and checked at readiness time:

- profile: `openai-text-embedding-3-small-v1`
- model: `text-embedding-3-small`
- dimensions: `1536`
- the same normalization is applied to documents and queries

For legal retrieval, explicit Article/Clause/Point anchors are checked first.
Dense top-20 and BM25-style top-20 candidates are merged with reciprocal-rank
fusion (`k=60`), deduplicated by stable chunk ID, and reranked to 10. A route
selects the final evidence set, normally at most three chunks for a direct
lookup. An explicit Article must be found; the system does not substitute a
nearby Article when it is absent. The cross-encoder remains shadow-only.

Each legal evidence item must have a stable ID, source, legal anchor, corpus
version, and provenance metadata. Citation verification performs structural
checks followed by claim-support verification. At most one repair is allowed;
safe-stop outcomes remain safe stops.

## API and SSE

The compatibility endpoint remains:

```text
POST /api/v1/chat
```

It accepts the legacy `query`, `conversation_id`, and `session_id` fields plus
optional V4 controls:

```json
{
  "operation": "message",
  "query": "Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?",
  "conversation_id": "...",
  "intent_hint": "case_assessment",
  "interaction_source": "composer",
  "mode": "auto"
}
```

`operation` can be `message` or `continue_case`. The case workspace is
hydrated and updated through:

```text
GET   /api/v1/sessions/{conversation_id}/case
PATCH /api/v1/sessions/{conversation_id}/case
```

PATCH saves facts only. The user must explicitly press **Tiếp tục đánh giá**
to run the case workflow again.

The response is streamed as SSE. Existing `status`, `response_chunk`,
`response_complete`, and `error` events remain supported. V4 also emits
`workflow_step`, `case_update`, and `input_required`. Every event includes a
stable `trace_id`, `pipeline_version`, and sequence number. The completion
payload can include route, outcome, result type, case state, required and
covered issues, evidence status, citations, available actions, corpus metadata,
and termination reason.

Readiness endpoints are separate:

```text
GET /api/v1/health   # process liveness
GET /api/v1/ready    # dependencies and legal index readiness
```

`/ready` returns `503` until PostgreSQL, Redis, Qdrant, the configured OpenAI
embedding contract, the `law_collection` alias, corpus metadata, and point
count are valid.

Trace inspection is opt-in:

```text
GET /api/v1/debug/traces/{trace_id}
GET /api/v1/debug/traces?conversation_id={id}&limit=20
```

Set `ENABLE_TRACE_DEBUG_API=true` to expose these endpoints. Set
`VITE_ENABLE_TRACE_DEBUG=true` to build the React trace drawer. Traces contain
workflow decisions, retrieval scores, evidence decisions, timing, and
termination reasons, but not API keys, system prompts, chain-of-thought, or
raw conversation history.

## Persistence and local services

PostgreSQL is the production source of truth for users, conversations,
messages, summaries, case states, agent runs, and trace events. SQLite uses the
same SQLAlchemy/Alembic schema for local development. Redis is limited to
answer cache, rate limiting, hot context, and short-lived feedback. The
API-key hash scopes stored conversations and traces to their owner.

The one-shot `indexer` service builds an immutable, versioned law collection.
It audits the collection and promotes the `law_collection` alias only after
the checks pass. Matching subsequent runs are idempotent and do not recompute
embeddings. Older collections remain available for rollback.

## Run locally

Requirements: Python 3.11, Node.js 18+, Docker Desktop, and an `.env` file
based on `.env.example`. Never commit `.env`, database files, Qdrant storage,
logs, cache files, or generated evaluation reports.

### Full stack

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose ps -a
Invoke-RestMethod http://127.0.0.1/api/v1/ready
```

Open the React application at [http://127.0.0.1](http://127.0.0.1). The
Compose stack includes React, Nginx, FastAPI, PostgreSQL, Redis, Qdrant, and
the one-shot law indexer. The backend starts only after the indexer exits
successfully.

### Python development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### Frontend development

```powershell
Set-Location frontend-react
npm.cmd install
npm.cmd run dev
```

Use the Docker stack when testing the real API, SSE, Qdrant index, or
PostgreSQL persistence. The Vite server is intended for isolated frontend
development.

## Local verification

There is deliberately no CI/CD workflow. The default checks are deterministic
and do not call OpenAI:

```powershell
.venv_acceptance\Scripts\python.exe -m pytest -q
.venv_acceptance\Scripts\ruff.exe check src/epr_agent backend scripts tests
.venv_acceptance\Scripts\mypy.exe src/epr_agent
python -m tests.eval.run_eval --suite all --output data/eval/v4-deterministic.json

Set-Location frontend-react
npm.cmd run test
npm.cmd run build
npm.cmd run test:e2e -- --grep-invert "real FastAPI|real multi-turn"
```

Opt-in service-backed checks require the Docker stack:

```powershell
$env:EPR_RUN_INTEGRATION = "1"
$env:EPR_API_BASE_URL = "http://127.0.0.1"
Set-Location ..
.venv_acceptance\Scripts\python.exe -m pytest -q tests/integration

Set-Location frontend-react
$env:PLAYWRIGHT_BASE_URL = "http://127.0.0.1"
npm.cmd run test:e2e -- --grep "real FastAPI|real multi-turn"
```

The OpenAI live evaluation is intentionally separate and writes a timestamped
local report:

```powershell
Set-Location ..
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
.venv_acceptance\Scripts\python.exe -m tests.eval.run_eval `
  --live --live-url http://127.0.0.1 --suite e2e `
  --output "data/eval/v4-live-$stamp.json"
```

The V4 test matrix and acceptance evidence are documented in
[`docs/v4_test_matrix.md`](docs/v4_test_matrix.md) and
[`docs/pipeline_v4_acceptance_report.md`](docs/pipeline_v4_acceptance_report.md).
The evaluated UI export and design states are preserved in
[`docs/design/`](docs/design/).

## Repository layout

```text
backend/              FastAPI routes, persistence adapters, migrations
src/epr_agent/        domain contracts, workflow, retrieval, evidence, trace
frontend-react/       React workspace, SSE client, panels, tests
scripts/              corpus/indexing and local operational utilities
data/                 source corpus and evaluation fixtures
docs/                 architecture, design handoff, test matrix, reports
tests/                unit, contract, integration, and evaluation tests
```

## Scope and next steps

The current release does not include login UI, file upload, long-term user
profile memory, autonomous tool discovery, or automatic web fallback. Adding a
new legal area should provide a corpus descriptor and rule pack, then pass the
same provenance, retrieval, evidence, API, SSE, and end-to-end quality gates.

## License

MIT
