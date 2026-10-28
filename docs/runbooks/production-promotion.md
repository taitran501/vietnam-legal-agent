# Production Promotion

The production target is legal chat grounded in a content-locked corpus of
selected Vietnamese legal sources. Production remains blocked until runtime
evidence, technical corpus integrity, human legal review, and deployment
approval are in place. The selected corpus does not imply complete coverage of
Vietnamese law.

## Autonomous-agent pilot gate

The `pipeline-agent` workflow runs the checked-in 50-case benchmark against the
real model provider and the pinned corpus of selected legal sources. Promotion
requires a pass rate of at least 70%, statutory-anchor accuracy of at least 80%,
context recall of at least 75%, and successful provider/evaluator status for
every case. Each case must also produce a terminal event, source payload, and
passing replay. These benchmark thresholds do not establish complete legal
coverage or legal approval.

See the [Live Agent Evaluation runbook](live-agent-eval.md) for the OpenAI secret, dispatch procedure, and artifact contract.

## Release Gates

Configure PostgreSQL, Redis, OpenAI, at least one authentication mechanism (OIDC or service token), and HTTPS `ALLOWED_ORIGINS` when the UI is cross-origin. Compose requires a database password. Production startup must keep authentication, rate limiting, trace access, legal verification, and CORS settings enabled.

The legal corpus is separate from application state. Build and verify the content-locked artifact for the exact release commit:

```powershell
python -m pip install -e ".[universal]"
python -m scripts.build_universal_index --download --rebuild
python -m scripts.build_universal_index --verify-only
```

A corpus refresh requires a technical integrity check, a review decision for that exact hash, and a production promotion decision. Missing or invalid corpus data must leave legal chat unavailable rather than silently using partial or stale sources.

## Deploy Order

1. Apply database migrations and complete the owner-mapping audit.
2. Verify the corpus artifact and backend readiness.
3. Deploy backend and frontend together with authentication configured.
4. Check `/api/v1/ready`, `/api/v1/health`, authenticated history, a legal lookup, the source drawer, feedback, and cross-user ownership denial.

Monitor authentication and ownership failures, capability status, stopped turns, SSE errors, source rejection, corpus version/hash, retrieval latency, and feedback persistence. Keep the reverse proxy behind TLS for user-facing deployments.
