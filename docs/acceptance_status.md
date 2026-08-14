# Current acceptance status

**Checked:** 2026-08-15
**Workspace:** `fix/priority-user-journeys` after `48fd5b6`, with the
production-hardening changes recorded in this snapshot

This file is the status of the working tree after the review remediation. It is
not a replacement for the commit-scoped historical reports. Once this work is
committed, rerun the checks and record the new commit here before calling it a
release evidence snapshot.

## Local checks

The following checks were run in the repository acceptance environment
(`.venv_acceptance\Scripts\python.exe`) unless stated otherwise:

| Check | Result |
| --- | --- |
| `pytest -q` | **410 passed, 3 skipped** (413 collected) |
| `python -m tests.eval.run_eval --suite all` | **exit 0**; deterministic route matrix 60/60 |
| `ruff check src/epr_agent backend scripts tests` | **pass** |
| `mypy src/epr_agent backend` | **pass**, 62 source files |
| `python -m scripts.sync_corpus_metadata --check` | **pass**, no issues; corpus SHA `1e8635ee…` |
| `docker compose config --quiet` | **pass** with an explicit `POSTGRES_PASSWORD` validation value |
| `git diff --check` | **pass**; only Git line-ending warnings |
| Frontend Vitest | **42 passed** in 14 test files |
| Frontend lint | **pass** |
| Frontend production build | **pass**; Vite reports a non-blocking >500 kB bundle warning |
| Playwright browser acceptance | **27 passed** |

The system Python interpreter without the project dependencies is not an
acceptance environment: it cannot import the declared `sse-starlette`
dependency. Use the repository environment or install `.[dev]` before
interpreting a test result.

## What this validates

- The backend CI path now runs corpus synchronization, unit/integration tests,
  deterministic evaluation, Ruff, and the complete backend mypy boundary.
- CI also installs Chromium and runs the browser journey suite.
- Redis rate limiting is fail-closed by default; an unavailable Redis produces
  a temporary 503 rather than silently disabling request protection.
- Retrieval relevance and web-result synthesis fail closed when the provider or
  structured verdict is unavailable.
- The source drawer displays missing technical metadata explicitly.
- A completed assessment/checklist can export a **preliminary text report**;
  the export repeats the unverified-facts disclaimer and is not a formal legal
  opinion or compliance filing.
- Production startup now fails fast on disabled auth, fail-open rate limiting,
  trace-debug exposure, local persistence, missing providers, or unsafe CORS.
- Backend/frontend/gateway images run unprivileged; Compose requires a database
  password and no longer pins services to non-scalable container names.
- Nginx restricts `/metrics`, forwards the HTTPS signal, and targets the
  authenticated backend metrics route.

## Still not proven by local checks

These are deliberate release gates, not claims that local tests can satisfy:

- the legal owner has approved the corpus, rule pack, amendment map, and an
  effective as-of date;
- a production deployment has healthy PostgreSQL/Qdrant/Redis/OpenAI/OIDC
  integrations, real authentication, monitoring, backups, and measured p95
  latency;
- Docker image builds and a live Compose stack are currently unverified in this
  session because the Docker Desktop Linux engine was not running; static
  Compose interpolation/configuration did pass;
- GitHub repository description, homepage, topics, and visibility have been
  configured by an authenticated repository administrator;
- upload/OCR, historical-law snapshots, and multi-domain legal support exist.
  They remain outside the current EPR-only evidence model and must not be
  implied by the preliminary export.

The historical V4 acceptance report remains valid only for the commit and
environment named inside that report. Its live local-stack result is useful
historical evidence, but it is not current production approval.
