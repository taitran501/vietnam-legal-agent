# Current acceptance status

**Checked:** 2026-08-18
**Workspace:** `agent/legal-repo-cleanup`

This file records checks against the current checkout. It is not a replacement
for the commit-scoped historical reports, and production/legal approval remains
a separate gate.

## Local checks

The following checks were run in the repository acceptance environment
(`.venv_acceptance\Scripts\python.exe`) unless stated otherwise:

| Check | Result |
| --- | --- |
| `pytest -q` | **455 passed, 3 skipped** (458 collected) |
| `python -m tests.eval.run_eval --suite all` | **exit 0**; deterministic route matrix 60/60 |
| `ruff check src/epr_agent backend scripts tests` | **pass** |
| `mypy src/epr_agent backend` | **pass**, 68 source files |
| `python -m scripts.sync_corpus_metadata --check` | **pass**, no issues; corpus SHA `9c7fe73bd6215a1e794432815d34a8a3cf8671dab7f1581d9c3d0abdf2756a45` |
| `git diff --check` | **pass**; only Git line-ending warnings |
| Frontend Vitest | **42 passed** in 14 test files |
| Frontend lint | **pass**; 3 existing Fast Refresh warnings, no errors |
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
- The public product language is now **Vietnam Legal Agent**; EPR remains a
  supported rule-pack and corpus domain rather than the product identity.
- The compatibility package namespace (`epr_agent`) and EPR corpus/rule-pack
  identifiers remain stable so existing imports, data manifests, and API
  clients do not break during the product rename.
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
- Appendix XXII corpus identity is stable across LibreOffice outputs: the
  converter-only `PDF_SHA256` field is excluded from the canonical row hash,
  while the source hash and extracted row content remain part of identity.
- Preview Compose promotion now uses the synchronized corpus hash and keeps
  legal review visibly pending instead of treating preview as production.

## Still not proven by local checks

These are deliberate release gates, not claims that local tests can satisfy:

- the legal owner has approved the corpus, rule pack, amendment map, and an
  effective as-of date;
- a production deployment has healthy PostgreSQL/Qdrant/Redis/OpenAI/OIDC
  integrations, real authentication, monitoring, backups, and measured p95
  latency;
- a production deployment has not been approved or measured; the current
  browser suite uses deterministic in-memory adapters and does not prove live
  PostgreSQL/Qdrant/Redis/OpenAI/OIDC integration;
- GitHub repository metadata beyond the canonical name (`vietnam-legal-agent`)
  has been configured by an authenticated repository administrator;
- upload/OCR and historical-law snapshots are not implemented, and legal
  coverage remains limited to the explicitly supported domains. They must not
  be implied by the preliminary export.

The historical V4 acceptance report remains valid only for the commit and
environment named inside that report. Its live local-stack result is useful
historical evidence, but it is not current production approval.
