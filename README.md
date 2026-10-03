# Vietnam Legal Agent

[![CI](https://github.com/taitran501/vietnam-legal-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/taitran501/vietnam-legal-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Vietnamese-first software for preliminary legal research across legal domains.

Vietnam Legal Agent lets a user ask ordinary questions, describe a legal
situation, or request procedural steps in chat. It is deliberately bounded: answers
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
  versioned effective-date metadata, deployment configuration, and a review
  record tied to the complete selected corpus hash. The current repository does
  not contain an approval record for production use of the multi-domain corpus.

## What it does

| Workflow | User-facing result |
| --- | --- |
| Legal lookup | A streamed answer with source citations and a source drawer for comparison. |
| Legal situation | Ordinary chat using facts the user provides; the assistant can ask one material follow-up question. |
| Procedure request | A concise, source-linked explanation of supported steps. |
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

The multi-domain preview uses the content-locked Ministry of Justice corpus
for legal chat across topics. An optional Qdrant collection is disabled by
default. The production image does not include the generated multi-domain
index until it passes the release and legal-review gates. The current corpus
does not provide complete coverage of every law or every legal domain. The
application does not currently provide:

- document upload or OCR in the browser UI;
- historical-law date selection;
- broad web search outside configured official domains;
- long-term user-profile memory;
- a formal legal or compliance report (the export is explicitly preliminary);
- complete coverage or authoritative conclusions for every legal domain.

## Quick start: Docker Compose

This is the recommended path for the local stack: React, FastAPI, PostgreSQL,
Redis, and the multi-domain corpus. Qdrant is an optional retrieval adapter
and stays disabled by default.

### Prerequisites

- Docker Desktop with Compose
- An OpenAI API key for live embedding/indexing and answer generation

### Start an isolated local preview

```bash
git clone https://github.com/taitran501/vietnam-legal-agent.git
cd vietnam-legal-agent
cp .env.example .env
```

Build and verify the multi-domain corpus before starting Compose:

```bash
python -m pip install -e ".[universal]"
python -m scripts.build_universal_index --download
python -m scripts.build_universal_index --verify-only
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
docker compose -f docker-compose.yml -f docker-compose.universal-preview.yml up -d --build
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
docker compose logs -f backend
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
| Local legal corpus | Content-locked multi-domain SQLite corpus mounted read-only by the backend. |

For the complete preview procedure and promotion boundary, see
[the local-preview runbook](docs/runbooks/local-preview.md).
The narrow official-law update experiment is documented in the
[official-delta preview runbook](docs/runbooks/official-delta-preview.md).

## Development

### Backend checks

From the repository root, install the development dependencies in a Python
3.11 environment:

```bash
python -m pip install -e ".[dev,universal]"
python -m scripts.build_universal_index --download --verify-only
python -m pytest -q
ruff check src/vietnam_legal_agent backend scripts tests
mypy src/vietnam_legal_agent backend
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

The adapter validates the browser contract, SSE handling, conversation
history, source display, feedback, retries, and safe stops. It is not
evidence that a production provider, credential, network policy, or legal
approval is available.

## Continuous integration contract

The workflow in `.github/workflows/ci.yml` runs on pull requests and pushes to
`main`:

| Job | Checks |
| --- | --- |
| `backend-quality` | Dependency consistency, Ruff, and mypy. |
| `backend` | Corpus metadata sync, pytest, deterministic route evaluation, and persona simulation. |
| `frontend` | `npm ci`, ESLint, Vitest, and the production TypeScript/Vite build. |
| `pilot-load` | Redis-backed two-worker SSE contract: 50 concurrent turns, saturation, and lease cleanup. |
| `e2e` | Playwright browser tests after the backend and frontend jobs pass. |
| `compose-smoke` | Builds the preview topology and checks gateway/backend/dependency readiness. |
| `Promptfoo Deterministic Evaluation` | Pull-request replay matrix backed by the internal claim/source verifier; no real provider. |
| `Live Agent Evaluation` | Manual `workflow_dispatch` only; real provider/corpus checks in the protected `pilot` environment. |

The CI badge above reports the repository workflow. It does not claim legal
approval, production readiness, uptime, latency, or the availability of
external providers.

CI currently validates the application but does not deploy it. A staging
deployment still needs a selected container host for FastAPI and a configured
frontend/API origin; production promotion should follow a smoke check against
that deployed staging environment.

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
| `QDRANT_URL` / `USE_QDRANT_CLOUD` | Optional vector retrieval adapter for a general legal corpus. |
| `REDIS_URL` | Cache and request-protection backend. |
| `ENFORCE_LEGAL_SAFETY_CIRCUIT_BREAKER` | Production safety contract; verifier/critic outages fail closed. Must remain `true` in production. |
| `ENFORCE_LEGAL_READINESS_GATE` / `LEGAL_READINESS_MANIFEST_PATH` | The current review manifest covers only a legacy narrow source. Production is blocked until the multi-domain corpus has a domain-neutral legal review. |
| `ENABLE_OFFICIAL_DELTA_RETRIEVAL` / `OFFICIAL_DELTA_MANIFEST_PATH` | Preview-only exact-instrument lookup for the small official-law delta; disabled by default. |
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
| `POST` | `/api/v1/chat` | Stream a natural-language legal question over SSE. |
| `POST` | `/api/v1/documents/upload` | API-only preview for bounded PDF, DOCX, or UTF-8 TXT parsing; no browser upload UI is included. |
| `GET` | `/api/v1/sessions` | List conversations owned by the current principal. |
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
src/vietnam_legal_agent/    Domain models, workflow, autonomous agent, retrieval, evidence, and persistence
frontend-react/   React UI, SSE client, ordinary chat, and browser tests
scripts/          Corpus synchronization, audit, and indexing utilities
data/             Multi-domain corpus manifest and versioned evaluation fixtures
docs/             Architecture, behavior contracts, runbooks, and acceptance notes
tests/            Unit, contract, integration, evaluation harness, and API tests
```

`src/vietnam_legal_agent/` is the primary package namespace for the product.

Start with [docs/README.md](docs/README.md) for the documentation map,
[the system overview](docs/architecture/system-overview.md),
[the autonomous agent architecture](docs/architecture/autonomous-agent-architecture.md), and
[the V4 behavior contract](docs/pipeline_v4_behavior_contract.md).

The evaluation control plane is documented in
[replay and quality triage](docs/evaluation/replay-and-triage.md). Deterministic
replay checks event ordering, trace/context continuity, source payloads, and
failure artifacts. Fixtures are engineering inputs and never require a legal
reviewer or become legal ground truth.

## Evaluation

The deterministic evaluation fixtures cover legal chat across several
ordinary domains and verify workflow, source, and citation contracts. They are
engineering checks, not legal ground truth or a claim of production quality.
A provider-backed evaluation with reviewed examples is still required before
making quality or production-readiness claims.

## Production boundary

A passing build or local preview is not a production release. Before enabling
production legal capability, the release process must independently verify:

- PostgreSQL, Redis, OpenAI, authentication, HTTPS origins, and
  request-protection settings;
- source-manifest hashes, corpus consistency, and versioned effective-date
  metadata;
- migrations, ownership isolation, readiness, rollback, monitoring, and
  authenticated browser/API smoke tests.

See [external release gates](docs/runbooks/external-release-gates.md),
[production corpus promotion](docs/runbooks/production-promotion.md),
[database migration](docs/runbooks/database-migration.md), and
[rollback](docs/runbooks/rollback.md).

## License

[MIT](LICENSE)
