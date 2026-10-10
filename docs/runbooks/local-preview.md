# Local and Staging Preview

Preview mode exercises legal chat against a content-locked, multi-domain corpus. It does not approve the corpus for production.

## Start a Preview

From the repository root:

```powershell
$env:CORPUS_RUNTIME_MODE = "preview"
# Only for an isolated local preview without OIDC/API-key setup:
$env:REQUIRE_AUTH = "false"
python -m pip install -e ".[dev,universal]"
python -m scripts.build_universal_index --download --rebuild
python -m scripts.build_universal_index --verify-only
docker compose -f docker-compose.yml -f docker-compose.universal-preview.yml up -d --build
Invoke-RestMethod http://127.0.0.1/api/v1/ready
```

Readiness must report `runtime_mode: preview`, `retrieval_sources.universal_legal.status: ready`, and a ready `legal_chat` capability. A missing or invalid corpus artifact blocks legal chat. The generated SQLite database is mounted read-only and is not copied into the application image.

Before starting Compose, copy `.env.example` to `.env`, set `POSTGRES_PASSWORD` to a long random value, and set `OPENAI_API_KEY` when live generation or corpus indexing is required. Compose has no database password fallback. The `REQUIRE_AUTH=false` override is local-only.

CI boots the same topology with an empty corpus mount to verify that the backend reports blocked legal-chat readiness while health and the frontend remain available. This checks degraded startup without calling a paid provider.

## Browser and Chat Preview

The deterministic browser backend uses source-grounded fixtures from employment, civil, consumer, administrative, criminal, family, corporate, and public information law. Run the browser suite from `frontend-react`:

```powershell
npm ci
npm run test:e2e
```

The browser suite launches its own test API and Vite server. It checks ordinary legal chat, evidence display, multi-turn context, feedback, stop/retry flows, and mobile/tablet layouts. Its fixtures are test data; they do not represent a production legal-quality or current-law certification.

## Natural-language Smoke Replay

The structured smoke fixture checks ordinary Vietnamese prompts, routing, termination, context handling, and source provenance. Generated prose is not compared byte-for-byte.

With the deterministic backend running on port 8010:

```powershell
python scripts/run_natural_language_smoke.py `
  --base-url http://127.0.0.1:8010 `
  --report artifacts/natural-language-smoke.json
```

Use a failed turn's trace ID and structured reason to locate the faulty stage.

## Promotion Boundary

Do not enable preview mode in production. Production promotion requires a content-locked corpus build and verification, a domain-neutral review decision, and a release artifact for the exact corpus hash. Technical reproducibility does not establish legal completeness or approval.
