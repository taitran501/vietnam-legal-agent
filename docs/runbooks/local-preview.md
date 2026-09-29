# Local and Staging Preview

Preview mode exists to exercise the complete user journey with a deterministic
source snapshot. It is not a production bypass and must remain visibly labelled
in the UI and source drawer. The default indexed snapshot is EPR-focused. A
broader Ministry of Justice corpus is an optional local preview artifact; it is
not included in the production release or enabled by default.

## Start a Preview

From the repository root:

```powershell
$env:CORPUS_RUNTIME_MODE = "preview"
# Only for an isolated local preview without OIDC/API-key setup:
$env:REQUIRE_AUTH = "false"
python -m scripts.sync_corpus_metadata --check
python -m scripts.audit_corpus
docker compose up -d --build
Invoke-RestMethod http://127.0.0.1/api/v1/ready
```

The readiness response should report `runtime_mode: preview`,
`corpus.status: preview_ready`, and `legal_chat.reason:
preview_snapshot`. A technically invalid corpus, an index mismatch,
or a database schema mismatch still blocks the relevant capability.
Preview readiness means the configured snapshot passed technical checks; it
does not mean every legal domain has an indexed source.

Before starting Compose, copy `.env.example` to `.env`, set
`POSTGRES_PASSWORD` to a long random value, and set `OPENAI_API_KEY` when live
generation or indexing is required. Compose has no database-password fallback.
The `REQUIRE_AUTH=false` override above is local-only and must not be reused in
staging or production.

CI uses `docker-compose.ci-smoke.yml` to boot this same topology with a no-op
indexer placeholder. It verifies gateway and backend liveness, confirms that
readiness reports a blocked legal capability while no index exists, and checks
the frontend response. This exercises degraded startup without requiring a
paid provider or making a legal-ground-truth claim.

For deterministic browser work without paid providers, use the local test
backend and Vite app:

```powershell
Start-Process -WindowStyle Hidden powershell -ArgumentList `
  "-NoProfile", "-Command", "python -m uvicorn tests.e2e_backend:app --host 127.0.0.1 --port 8010"
Set-Location frontend-react
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:8010"
npm.cmd run dev -- --host 127.0.0.1 --port 4175
```

The deterministic backend is a browser-test adapter. It validates the real
FastAPI chat routes, SSE client, React rendering, durable in-memory turn
contract, source drawer, case drawer, and feedback controls; it is not evidence
that the production Qdrant or official web provider is available.

## Natural-language smoke replay

The structured smoke fixture replays common Vietnamese prompts against the same
deterministic backend used by browser acceptance. It checks route, termination,
follow-up context metadata, retrieval phases, and canonical source snapshots;
generated prose is intentionally not compared verbatim.

With the deterministic backend running on port 8010:

```powershell
python scripts/run_natural_language_smoke.py `
  --base-url http://127.0.0.1:8010 `
  --report artifacts/natural-language-smoke.json
```

The report is a local preview diagnostic, not a live-provider or legal-ground-
truth promotion gate. A failed case should be debugged from its trace ID and
structured failure reason before any browser feedback is filed.

## Promotion Boundary

Do not set preview mode in production. The production readiness gate requires
the canonical manifest/rule-pack/index hashes and complete source and amendment
technical checks. The canonical sync command only refreshes deterministic
source metadata:

```powershell
python -m scripts.sync_corpus_metadata --check
```

Use `--write` only as an explicit maintainer action after changing source
files, then review the resulting diff and rerun the complete release checks.
