# EPR Compliance Copilot

[![CI](https://github.com/taitran501/legal_epr/actions/workflows/ci.yml/badge.svg)](https://github.com/taitran501/legal_epr/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Vietnamese-first software for preliminary Extended Producer Responsibility
(EPR) research and compliance preparation.

EPR Compliance Copilot helps a user look up a provision, assess a business
situation, or prepare an evidence-linked checklist. It is deliberately
bounded: answers are checked against the active repository-managed corpus,
user-provided facts remain labelled as unverified, and the workflow can stop
when evidence or a required dependency is missing.

> **Important:** This project provides preliminary information. It is not
> legal advice, a formal legal opinion, or a substitute for the official
> text and an organisation's internal approval process.

## Status

- The repository supports a local Docker preview and a deterministic browser
  test environment.
- GitHub Actions validates the backend, frontend, and browser-test contracts.
- There is no hosted public demo in this repository.
- Production legal capability remains subject to corpus review, an approved
  effective date, deployment configuration, and external operational gates.

## What it does

| Workflow | User-facing result |
| --- | --- |
| Legal lookup | A streamed answer with source citations and a source drawer for comparison. |
| Case assessment | A guided form that asks for the facts required by the selected task and returns a preliminary assessment. |
| Compliance checklist | A guided list of preparation actions linked to the available evidence. |
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

The current product focuses on Vietnamese EPR law and the instruments tracked
by the repository corpus. It does not currently provide:

- document upload or OCR;
- historical-law date selection;
- broad web search outside configured official domains;
- long-term user-profile memory;
- a formal legal or compliance report (the export is explicitly preliminary);
- legal coverage outside the EPR domain.

## Quick start: Docker Compose

This is the recommended path for the complete local stack: React, FastAPI,
PostgreSQL, Redis, Qdrant, and the one-shot corpus indexer.

### Prerequisites

- Docker Desktop with Compose
- An OpenAI API key for live embedding/indexing and answer generation

### Start an isolated local preview

```bash
git clone https://github.com/taitran501/legal_epr.git
cd legal_epr
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
the readiness payload and UI may report `preview_unapproved_corpus`; that is
an expected warning, not a production approval.

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
| `e2e` | Playwright browser tests after the backend and frontend jobs pass. |

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
| `DATABASE_URL` | PostgreSQL connection; local development may use `HISTORY_DB_PATH` when unset. |
| `POSTGRES_PASSWORD` | Required by Compose; there is no insecure default. |
| `QDRANT_URL` / `USE_QDRANT_CLOUD` | Self-hosted or Qdrant Cloud vector storage. |
| `REDIS_URL` | Cache and request-protection backend. |
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
| `GET` | `/api/v1/sessions` | List conversations owned by the current principal. |
| `GET/PATCH` | `/api/v1/sessions/{id}/case` | Read or save guided case facts. |
| `PUT` | `/api/v1/conversations/{id}/messages/{message_id}/feedback` | Save answer feedback. |

The main request path is:

```text
React UI → Nginx/SSE → FastAPI → bounded workflow
                         → retrieval/evidence checks → answer or safe stop
                         → durable persistence → source-aware UI
```

The code and contracts are organised as follows:

```text
backend/          FastAPI routes, authentication, configuration, and adapters
src/epr_agent/    Domain models, workflow, retrieval, evidence, and persistence
frontend-react/   React UI, SSE client, guided forms, and browser tests
scripts/          Corpus synchronization, audit, and indexing utilities
data/             Corpus manifests, rule pack, and checked-in fixtures
docs/             Architecture, behavior contracts, runbooks, and acceptance notes
tests/            Unit, contract, integration, evaluation, and API tests
```

Start with [docs/README.md](docs/README.md) for the documentation map,
[the system overview](docs/architecture/system-overview.md), and
[the V4 behavior contract](docs/pipeline_v4_behavior_contract.md).

## Production boundary

A passing build or local preview is not a production release. Before enabling
production legal capability, the release process must independently verify:

- PostgreSQL, Qdrant, Redis, OpenAI, authentication, HTTPS origins, and
  request-protection settings;
- source, amendment, rule-pack, corpus, and immutable-index consistency;
- an approved corpus review status and approved effective date;
- migrations, ownership isolation, readiness, rollback, monitoring, and
  authenticated browser/API smoke tests.

See [external release gates](docs/runbooks/external-release-gates.md),
[production corpus promotion](docs/runbooks/production-promotion.md),
[database migration](docs/runbooks/database-migration.md), and
[rollback](docs/runbooks/rollback.md).

## License

[MIT](LICENSE)
