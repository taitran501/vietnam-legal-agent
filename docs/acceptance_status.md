# Current acceptance status

**Checked:** 2026-08-25
**Baseline commit:** `34f1ee8` (`main` in `vietnam-legal-agent`)
**Audit branch:** `audit/repo-docs-and-runtime-contracts` (not merged)

This file records checks against the current checkout. It is not a replacement
for the commit-scoped historical reports, and production/legal approval remains
a separate gate.

## Local checks

The following checks were run in the repository acceptance environment
(`.venv_acceptance\Scripts\python.exe`) unless stated otherwise:

| Check | Result |
| --- | --- |
| `pytest -q` | **573 passed, 3 skipped, 9 warnings** (audit branch; baseline main was 570) |
| `python -m tests.eval.run_eval --suite all` | **exit 0**; deterministic route matrix **60/60**, generated at this commit |
| `python tests/eval/agent_harness.py --suite all` | **18/18** trajectory cases |
| `python tests/eval/persona_simulation.py --persona all` | **15/15** persona cases |
| `ruff check src/epr_agent backend scripts tests promptfoo` | **pass** |
| `mypy src/epr_agent backend` | **pass** (77 source files) |
| `python -m scripts.sync_corpus_metadata --check` | **pass**, no issues |
| `git diff --check` | **pass** |
| `docker compose ... config --quiet` | **pass** for the base stack plus deterministic CI smoke overlay |
| Universal corpus verification | **pass** for the local content-locked artifact; generated DB remains ignored |
| Frontend Vitest | **45 passed** in 15 test files |
| Frontend lint | **pass**; existing Fast Refresh warnings, no errors |
| Frontend production build | **pass**; Vite reports a non-blocking >500 kB bundle warning |
| Playwright browser acceptance | **27 passed** in the latest GitHub Actions E2E job |
| Pilot-load CI contract | **pass**; 50-turn Redis-backed SSE SLO job |
| Compose-smoke CI contract | **pass**; latest `main` push workflow |
| Promptfoo deterministic replay | **pass**; latest `main` push workflow |

The system Python interpreter without the project dependencies is not an
acceptance environment: it cannot import the declared `sse-starlette`
dependency. Use the repository environment or install `.[dev]` before
interpreting a test result.

## What this validates

- The backend CI path now runs corpus synchronization, unit/integration tests,
  deterministic evaluation, Ruff, and the complete backend mypy boundary.
- CI also installs Chromium and runs the browser journey suite.
- CI runs on pull requests, all branch pushes, and manual dispatch; it
  also runs `pip check` and a real Docker Compose gateway/backend/dependency
  smoke overlay in preview mode.
- The product language is **Vietnam Legal Agent**. EPR remains a
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
- Trace inspection is explicitly gated, owner-scoped for quality readers,
  operations-scoped for cross-owner access, bounded in memory, and connected to
  the durable redacted run store used by Pipeline V4.
- Universal-corpus augmentation is disabled by default and rejected in
  production until that separate source receives legal approval; its inputs and
  generated output are content-locked for reproducible preview builds.
- Backend/frontend/gateway images run unprivileged; Compose requires a database
  password and no longer pins services to non-scalable container names.
- Nginx restricts `/metrics`, forwards the HTTPS signal, and targets the
  authenticated backend metrics route.
- Appendix XXII corpus identity is stable across LibreOffice outputs: the
  converter-only `PDF_SHA256` field is excluded from the canonical row hash,
  while the source hash and extracted row content remain part of identity.
- Preview Compose promotion now uses the synchronized corpus hash and keeps
  legal review visibly pending instead of treating preview as production.
- The V4 pipeline routes cases through `detect_legal_domain()` to the
  appropriate rule engine: EPR uses the deterministic `CaseFormResolver`;
  all other domains (labor, civil, corporate, marriage, land, traffic)
  use `UniversalCaseFormResolver` and `evaluate_universal_case()`.
- The autonomous agent path (`pipeline-agent`) shares the same tool registry
  and supports all legal domains via `evaluate_legal_case`.
- The audited-evaluation control plane now records multi-turn replay events,
  trace/source payloads, claim-level verification, and redacted feedback triage.
  Pending fixtures remain informational and cannot block promotion.

## Still not proven by local checks

These are deliberate release gates, not claims that local tests can satisfy:

- the legal owner has approved the corpus, rule pack, amendment map, and an
  effective as-of date;
- the pushed commit has passed the GitHub Actions Compose smoke job; the local
  check above validates configuration but does not replace the remote container
  run;
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
- The checked-in historical RAGAS artifact is exploratory only: it reports a
  10% gate pass rate and 28% statutory-anchor accuracy, and is not evidence of
  current production quality. The live provider-backed evaluation has not been
  run in this checkout because it is a manual `workflow_dispatch` gate.
- The 2026-law fixture is still `pending` legal-source audit; no generated
  answer from that fixture is an authoritative legal ground truth.

The historical V4 acceptance report remains valid only for the commit and
environment named inside that report. Its live local-stack result is useful
historical evidence, but it is not current production approval.
