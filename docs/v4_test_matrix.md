# V4 local test matrix

Pipeline V4 is validated by observable behavior: route, facts, issue coverage,
evidence, outcome, SSE contract, persistence, and UI state. Tests do not use
generated answer prose as the oracle.

## Fast deterministic checks

Run from the repository root with the acceptance environment:

```powershell
.venv_acceptance\Scripts\python.exe -m pytest -q
.venv_acceptance\Scripts\ruff.exe check src/epr_agent backend scripts tests
.venv_acceptance\Scripts\mypy.exe src/epr_agent
python -m tests.eval.run_eval --suite all --output data/eval/v4-deterministic.json
```

The V4 manifest contains 60 query-understanding cases, 60 retrieval cases,
and 40 assessment/checklist trajectories. The deterministic runner records
route accuracy, anchor preservation, retrieval metrics, issue coverage,
citations, cache policy, SSE event types, and p95 latency.

## Frontend checks

```powershell
Set-Location frontend-react
npm.cmd run test
npm.cmd run build
npm.cmd run test:e2e -- --grep-invert "real FastAPI|real multi-turn"
```

The mocked browser suite covers prefill-only quick actions, editable intent,
case facts, every V4 outcome, source drawer, history title, cancellation,
sidebar collapse, and mobile layout. A quick action must create no network
request until the user explicitly submits the composer.

## Real local services

Start the real stack and let the one-shot indexer finish before testing:

```powershell
docker compose up -d --build
docker compose ps -a
Invoke-RestMethod http://127.0.0.1/api/v1/ready
```

The backend readiness response must report the active `law_collection` alias,
EPR corpus SHA, legal schema version, and the
`openai-text-embedding-3-small-v1` profile. The second indexer run should reuse
the matching versioned collection without requesting embeddings.

Run service-backed integration tests explicitly:

```powershell
$env:EPR_RUN_INTEGRATION="1"
$env:EPR_API_BASE_URL="http://127.0.0.1"
.venv_acceptance\Scripts\python.exe -m pytest -q tests/integration
```

This checks readiness failure behavior, real SSE ordering, citation-bearing
legal lookup, trace persistence when the debug API is enabled, and the local
service boundary. Integration tests are marked `integration`; `live` tests
are additionally marked `live` and are skipped unless explicitly enabled.

Run real-stack browser flows:

```powershell
Set-Location frontend-react
$env:PLAYWRIGHT_BASE_URL="http://127.0.0.1"
npm.cmd run test:e2e -- --grep "real FastAPI|real multi-turn"
```

These flows validate React → Nginx → FastAPI → V4 workflow → Qdrant. They do
not assert exact generated prose.

## OpenAI live evaluation

The 40-case live suite is opt-in because it uses the configured OpenAI model
and the real V4 collection:

```powershell
Set-Location ..
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
.venv_acceptance\Scripts\python.exe -m tests.eval.run_eval `
  --live --live-url http://127.0.0.1 --suite e2e `
  --output "data/eval/v4-live-$stamp.json"
```

The timestamped report records its UTC generation time, evaluated commit SHA, corpus and Appendix hashes,
rule-pack version, embedding profile, per-case traces, metrics, failures, and
p95 latency. A live report is acceptance evidence only after the configured
thresholds are checked: route macro-F1 ≥ 0.95, explicit-anchor and mandatory
issue coverage at 100%, retrieval P@1/NDCG@3/Recall@5 ≥ 0.9375, valid material
citations, zero FAQ runtime use, zero pre-submit quick-action requests, and
live E2E p95 below 15 seconds.

## Artifacts and stop rules

Generated reports belong in `data/eval/` and are ignored by Git. The
`pipeline_v4_manifest.py` and test fixtures are the versioned source of truth;
the reports capture a particular local run. A missing legal index, incomplete
facts, insufficient issue evidence, failed citation verification, or a
cancelled request must stop safely and must not be reported as
`answer_complete`.
