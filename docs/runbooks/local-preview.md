# Local and staging preview

Preview mode exists to exercise the complete user journey before the legal
corpus has received external approval. It is not a production bypass and must
remain visibly labelled in the UI and source drawer.

## Start a preview

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
preview_unapproved_corpus`. A technically invalid corpus, an index mismatch,
or a database schema mismatch still blocks the relevant capability.

Before starting Compose, copy `.env.example` to `.env`, set
`POSTGRES_PASSWORD` to a long random value, and set `OPENAI_API_KEY` when live
generation or indexing is required. Compose has no database-password fallback.
The `REQUIRE_AUTH=false` override above is local-only and must not be reused in
staging or production.

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

## Promotion boundary

Do not set preview mode in production. The production readiness gate requires
the canonical manifest/rule-pack/index hashes, complete source and amendment
technical checks, and `legal_review_status: approved` with an approved as-of
date. The canonical sync command never changes that approval field:

```powershell
python -m scripts.sync_corpus_metadata --check
```

Use `--write` only as an explicit maintainer action after changing source
files, then review the resulting diff and rerun the complete release checks.
