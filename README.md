# Vietnam Legal Agent

[![CI](https://github.com/taitran501/vietnam-legal-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/taitran501/vietnam-legal-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Vietnamese-first software for preliminary legal research, case analysis, and
compliance preparation across selected legal domains.

Vietnam Legal Agent helps a user look up a provision, assess a legal situation,
or prepare an evidence-linked checklist. It is deliberately bounded: answers
are checked against the active repository-managed corpus, user-provided facts
remain labelled as unverified, and the workflow can stop when evidence or a
required dependency is missing.

> **Important:** This project provides preliminary information. It is not
> legal advice, a formal legal opinion, or a substitute for the official
> text and an organisation's internal approval process.

## Status

- The repository supports a local Docker preview and a deterministic browser
  test environment.
- GitHub Actions validates the backend, frontend, browser, pilot-capacity,
  Compose-smoke, and deterministic evaluation contracts.
- The provider-backed `Live Agent Evaluation` is manual-only and runs against
  the protected `pilot` environment; it is not implied by pull-request CI.
- There is no hosted public demo in this repository.
- Production legal capability remains subject to technical corpus integrity,
  versioned effective-date metadata, deployment configuration, and external
  operational gates. The repository does not make a human legal-review record
  a framework or promotion dependency.

## What it does

| Workflow | User-facing result |
| --- | --- |
| Legal lookup | A streamed answer with source citations and a source drawer for comparison. |
| Case assessment | A guided form that asks for the facts required by the selected task and returns a preliminary assessment. Domain routing via `detect_legal_domain()` sends cases to the appropriate rule engine (7 legal domains + general). |
| Legal/compliance checklist | A guided list of preparation actions linked to the available evidence. |
| Autonomous Agent | Dynamic multi-step reasoning (ReAct loop) with tool calling, budget control ($\le 5$ steps), and layman-friendly query handling. |
| Follow-up and recovery | Continue an active case, stop a turn, retry a failed turn, or regenerate a persisted answer. |
| Explicit web research | Search configured official domains only when the user selects the research workflow. |

The UI is Vietnamese-first. It also supports conversation persistence,
feedback, source-aware preliminary `.txt` report export, and readiness
messages that explain why a capability is unavailable.

## Trust boundaries

The application is designed to fail visibly instead of filling gaps with a
confident-looking answer:

- Legal generation is gated by retrieval and citation checks.
- Missing provisions, weak evidence, incomplete facts, stale corpus metadata,
  and unavailable dependencies produce reason-specific safe stops.
- Facts entered by a user are facts supplied by that user; they are not
  independently verified documents.
- Web research is an explicit route and is restricted to configured official
  domains such as `vanban.chinhphu.vn` and `vbpl.vn`.
- `preview` mode is for local or staging validation. It does not grant legal
  approval and must not be used as a production bypass.

## Scope and limitations

The current product focuses on Vietnamese legal research across selected
domains, including civil/contracts, labor, corporate, land, traffic, and EPR.
It does not currently provide:

- document upload or OCR in the browser UI;
- historical-law date selection;
- broad web search outside configured official domains;
- long-term user-profile memory;
- a formal legal or compliance report (the export is explicitly preliminary);
- complete coverage or authoritative conclusions for every legal domain.

## Quick start: Docker Compose

This is the recommended path for the complete local stack: React, FastAPI,
PostgreSQL, Redis, Qdrant, and the one-shot corpus indexer.

### Prerequisites

- Docker Desktop with Compose
- An OpenAI API key for live embedding/indexing and answer generation

### Start an isolated local preview

```bash
git clone https://github.com/taitran501/vietnam-legal-agent.git
cd vietnam-legal-agent
cp .env.example .env
```

Edit `.env` before starting Compose:

```dotenv
OPENAI_API_KEY=replace-with-your-key
POSTGRES_PASSWORD=use-a-long-random-local-password
CORPUS_RUNTIME_MODE=preview
REQUIRE_AUTH=false
```

`REQUIRE_AUTH=false` is only for an isolated local preview. Use OIDC, service
tokens, or another configured authentication mechanism in a shared or
deployed environment.

Start and inspect the stack:

```bash
docker compose up -d --build
docker compose ps -a
```

Check readiness:

```bash
curl http://127.0.0.1/api/v1/ready
```

Open the application at [http://127.0.0.1](http://127.0.0.1). In preview mode,
the readiness payload and UI may report `preview_snapshot`; that identifies a
non-production runtime mode and is not a quality or legal-opinion claim.

Useful commands:

```bash
docker compose logs -f backend indexer
docker compose ps -a
docker compose down
```

The Compose services are:

| Service | Role |
| --- | --- |
| `nginx` | Same-origin entry point and frontend/API gateway on port 80. |
| `frontend` | React application served by unprivileged Nginx. |
| `backend` | FastAPI API, bounded workflow, persistence, and readiness checks. |
| `postgres` | Durable conversation, case, feedback, and run storage. |
| `redis` | Cache, short-lived context, and rate limiting. |
| `qdrant` | Legal vector storage. |
| `indexer` | One-shot corpus audit and immutable index preparation. |

For the complete preview procedure and promotion boundary, see
[the local-preview runbook](docs/runbooks/local-preview.md).

## Development

### Backend checks

From the repository root, install the development dependencies in a Python
3.11 environment:

```bash
python -m pip install -e ".[dev]"
python -m scripts.sync_corpus_metadata --check
python -m pytest -q
ruff check src/epr_agent backend scripts tests
mypy src/epr_agent backend
python -m tests.eval.run_eval --suite all
```

### Frontend checks

```bash
cd frontend-react
npm ci
npm run lint
npm run test
npm run build
```

### Browser tests

The Playwright configuration starts a deterministic FastAPI adapter and a
Vite server. It does not require production credentials or a live Qdrant
service:

```bash
cd frontend-react
npm ci
npx playwright install chromium
npm run test:e2e
```

The adapter validates the browser contract, SSE handling, persistence-shaped
flows, source and case panels, feedback, retries, and safe stops. It is not
evidence that a production provider, credential, network policy, or legal
approval is available.

## Continuous integration contract

The workflow in `.github/workflows/ci.yml` runs on pull requests and pushes to
`main`:

| Job | Checks |
| --- | --- |
| `backend` | Corpus metadata sync, pytest, deterministic route evaluation, Ruff, and mypy. |
| `frontend` | `npm ci`, ESLint, Vitest, and the production TypeScript/Vite build. |
| `pilot-load` | Redis-backed two-worker SSE contract: 50 concurrent turns, saturation, and lease cleanup. |
| `e2e` | Playwright browser tests after the backend and frontend jobs pass. |
| `compose-smoke` | Builds the preview topology and checks gateway/backend/dependency readiness. |
| `Promptfoo Deterministic Evaluation` | Pull-request replay matrix backed by the internal claim/source verifier; no real provider. |
| `Live Agent Evaluation` | Manual `workflow_dispatch` only; real provider/corpus checks in the protected `pilot` environment. |

The CI badge above reports the repository workflow. It does not claim legal
approval, production readiness, uptime, latency, or the availability of
external providers.

## Configuration and security

Copy [.env.example](.env.example) to `.env`; never commit `.env`, API keys,
database files, Qdrant storage, logs, or generated evaluation output.

Important settings include:

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | Embeddings and live answer generation. |
| `CORPUS_RUNTIME_MODE` | `preview` for local/staging validation; `production` for a release candidate. |
| `REQUIRE_AUTH` | Authentication switch; disable only for an isolated local test. |
| `AGENT_PIPELINE_VERSION` | `pipeline-v4` for deterministic bounded workflow; `pipeline-agent` for autonomous ReAct agent loop. |
| `DATABASE_URL` | PostgreSQL connection; local development may use `HISTORY_DB_PATH` when unset. |
| `POSTGRES_PASSWORD` | Required by Compose; there is no insecure default. |
| `QDRANT_URL` / `USE_QDRANT_CLOUD` | Self-hosted or Qdrant Cloud vector storage. |
| `REDIS_URL` | Cache and request-protection backend. |
| `AGENT_MAX_IN_FLIGHT_TURNS` / `AGENT_ADMISSION_WAIT_SECONDS` | Deployment-wide agent-turn admission (`50` / `2s` by default). |
| `AGENT_LEASE_TTL_SECONDS` / `AGENT_LEASE_HEARTBEAT_SECONDS` | Redis lease lifetime and heartbeat for long-running turns (`300s` / `30s`). |
| `DOCUMENT_MAX_IN_FLIGHT_UPLOADS` | Deployment-wide Redis admission limit for the API-only document preview (default `10`). |
| `ENABLE_CROSS_ENCODER_RERANK` / `CROSS_ENCODER_SHADOW_MODE` / `CROSS_ENCODER_ROLLOUT_PERCENT` | Reranker safety controls; default is shadow-only with 0% user rollout. |
| `RATE_LIMIT_FAIL_OPEN` | Keep `false` outside an explicitly isolated preview. |
| `OIDC_*`, `SERVICE_TOKEN_DEFINITIONS`, `API_KEYS` | Deployment authentication options. |
| `ALLOWED_ORIGINS` | HTTPS origins for a cross-origin deployment; empty is suitable for the same-origin Compose gateway. |

In a deployed browser environment, OIDC is the intended authentication path.
Non-browser automation can use scoped service tokens. Access tokens are not
used as conversation ownership keys and are not persisted by the application.

## API and architecture

When the API is run directly, FastAPI documentation is available at
`http://127.0.0.1:8000/docs`.

Common API routes are:

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Process liveness. |
| `GET` | `/api/v1/ready` | Dependency, corpus, and capability readiness. |
| `POST` | `/api/v1/chat` | Stream a question or guided-workflow turn over SSE. |
| `POST` | `/api/v1/documents/upload` | API-only preview for bounded PDF, DOCX, or UTF-8 TXT parsing; no browser upload UI is included. |
| `GET` | `/api/v1/sessions` | List conversations owned by the current principal. |
| `GET/PATCH` | `/api/v1/sessions/{id}/case` | Read or save guided case facts. |
| `PUT` | `/api/v1/conversations/{id}/messages/{message_id}/feedback` | Save answer feedback. |

Document upload is an API-only preview capability. It accepts a maximum file
payload of 10 MiB (Nginx allows 11 MiB for multipart framing), validates the
extension, declared MIME type, and file signature, and applies PDF, DOCX ZIP,
and extracted-text resource limits before analysis. A full admission queue
returns a retryable HTTP 503 response. This capability is not a production
document-management system and does not currently include OCR or a browser UI.

The main request path is:

```text
React UI → Nginx/SSE → FastAPI → bounded workflow / autonomous agent loop
                         → retrieval/evidence checks → answer or safe stop
                         → durable persistence → source-aware UI
```

The code and contracts are organised as follows:

```text
backend/          FastAPI routes, authentication, configuration, and adapters
src/epr_agent/    Domain models, workflow, autonomous agent, retrieval, evidence, and persistence
frontend-react/   React UI, SSE client, guided forms, and browser tests
scripts/          Corpus synchronization, audit, and indexing utilities
data/             Corpus manifests, rule pack, and checked-in fixtures
docs/             Architecture, behavior contracts, runbooks, and acceptance notes
tests/            Unit, contract, integration, evaluation harness, and API tests
```

The `src/epr_agent/` namespace is retained for backward compatibility; the
product supports all legal domains, not just EPR.

Start with [docs/README.md](docs/README.md) for the documentation map,
[the system overview](docs/architecture/system-overview.md),
[the autonomous agent architecture](docs/architecture/autonomous-agent-architecture.md), and
[the V4 behavior contract](docs/pipeline_v4_behavior_contract.md).

The evaluation control plane is documented in
[replay and quality triage](docs/evaluation/replay-and-triage.md). Deterministic
replay checks event ordering, trace/context continuity, source payloads, and
failure artifacts. Fixtures are engineering inputs and never require a legal
reviewer or become legal ground truth.

## Historical benchmark artifact (not promotion evidence)

The repository contains a 50-case exploratory benchmark across six legal
domains. The checked-in report was generated on **2026-08-19** against the
`vietnam_legal_collection_v1` collection with the configured
`darklethelong/vnlegal-lal` embedding model. Cross-encoder reranking is
configured in shadow mode by default (`CROSS_ENCODER_ROLLOUT_PERCENT=0`), so
the report must not be read as proof that reranking is active for users.

The report is a reproducibility reference, not a current quality or production
claim. It predates the replay/evidence contract and reports only a 10%
LLM-judge gate pass rate, 28% statutory-anchor accuracy, 4.85s average
retrieval latency, and 8.18s average end-to-end latency. See the raw
[historical report](data/eval/ragas_benchmark_results.json) and use the
[replay/evaluation control plane](docs/evaluation/replay-and-triage.md) for
promotion evidence.

### 1. Retrieval & Ranking Benchmark (50 Statutory Scenarios)

| Metric | Score | Description |
| :--- | :---: | :--- |
| **Hit Rate @ 1 (P@1)** | **54.0%** | Relevant statutory provision ranked #1 |
| **Hit Rate @ 3 (Top-3)** | **66.0%** | Target provision retrieved in Top 3 |
| **Hit Rate @ 5 (Top-5)** | **68.0%** | Target provision retrieved in Top 5 |
| **Hit Rate @ 10 (Top-10)** | **80.0%** | Target provision retrieved in Top 10 |
| **MRR @ 10** | **0.6189** | Mean Reciprocal Rank across all 50 queries |
| **NDCG @ 3** | **0.5596** | Normalized Discounted Cumulative Gain @ 3 |
| **NDCG @ 10** | **0.6447** | Normalized Discounted Cumulative Gain @ 10 |
| **Average retrieval latency (historical report)** | **4.85s** | Environment-specific dense + BM25 benchmark measurement |

### 2. RAGAS Framework Evaluation (End-to-End Legal QA)

Evaluated via LLM-as-a-Judge and statutory citation verification across all 50 scenarios:

| RAGAS Dimension | Score | Description |
| :--- | :---: | :--- |
| **Faithfulness (Độ trung thực)** | **83.5%** | Factual claims in the answer supported by retrieved statutory evidence |
| **Answer Relevance (Độ trúng đích)** | **90.0%** | Direct semantic & legal alignment with the user's inquiry |
| **Context Precision (Độ chính xác ngữ cảnh)** | **28.5%** | Proportion of top-k retrieved documents containing essential legal grounds |
| **Context Recall (Độ bao phủ căn cứ)** | **52.0%** | Proportion of expected statutory anchors found in retrieved context |
| **Statutory Anchor Accuracy** | **28.0%** | Expected statutory anchors present in the generated answer |
| **Composite RAGAS Score** | **65.0%** | Weighted multi-dimensional legal assistance quality score |
| **LLM-judge gate pass rate** | **10.0%** | Historical exploratory gate; not a promotion threshold |

### 3. Domain Performance Breakdown (50 Scenarios across 6 Domains)

| Legal Domain | Scenarios | Hit Rate @ 3 | MRR @ 10 | NDCG @ 10 | Faithfulness | Relevance | Composite RAGAS |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Civil & Contracts (Dân sự & Hợp đồng)** | 10 | **80.0%** | **0.7500** | **0.7502** | **93.0%** | **100.0%** | **70.7%** |
| **Labor & Employment (Lao động & Việc làm)** | 10 | **80.0%** | **0.7367** | **0.7869** | **90.8%** | **97.0%** | **69.8%** |
| **Corporate & Commercial (Doanh nghiệp & TM)** | 8 | **75.0%** | **0.6875** | **0.6880** | **100.0%** | **100.0%** | **69.1%** |
| **Marriage & Family (Hôn nhân & Gia đình)** | 7 | **85.7%** | **0.8095** | **0.8217** | **100.0%** | **100.0%** | **74.6%** |
| **Land & Real Estate (Đất đai & Bất động sản)** | 8 | **37.5%** | **0.3637** | **0.4513** | **69.1%** | **80.0%** | **63.2%** |
| **Environmental & EPR (Môi trường & EPR)** | 7 | **28.6%** | **0.2857** | **0.2857** | **40.7%** | **55.7%** | **37.9%** |

To reproduce the benchmark locally:
```bash
python scripts/run_full_benchmark_and_ragas.py
```

## Production boundary

A passing build or local preview is not a production release. Before enabling
production legal capability, the release process must independently verify:

- PostgreSQL, Qdrant, Redis, OpenAI, authentication, HTTPS origins, and
  request-protection settings;
- source, amendment, rule-pack, corpus, and immutable-index consistency;
- versioned source metadata, amendment/rule-pack consistency, and effective-date
  metadata for the corpus and immutable index;
- migrations, ownership isolation, readiness, rollback, monitoring, and
  authenticated browser/API smoke tests.

See [external release gates](docs/runbooks/external-release-gates.md),
[production corpus promotion](docs/runbooks/production-promotion.md),
[database migration](docs/runbooks/database-migration.md), and
[rollback](docs/runbooks/rollback.md).

## License

[MIT](LICENSE)
