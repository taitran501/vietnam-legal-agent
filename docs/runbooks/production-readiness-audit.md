# Production Readiness Audit

**Checked:** 2026-08-26
**Release head:** `22d339c` (`main`)
**Remote CI:** [main CI run 32935342399](https://github.com/taitran501/vietnam-legal-agent/actions/runs/32935342399)

This audit separates repository evidence from deployment evidence. Green
engineering checks do not imply that a live provider, production deployment,
or legal conclusion has been validated.

The evidence rows below refer to the merged baseline `22d339c`; the audit
branch adds one production-configuration regression test, so its local run is
`595 passed, 2 skipped`.

## Proven at the current release head

| Area | Evidence | Status |
| --- | --- | --- |
| Backend contracts | `594 passed, 2 skipped`; corpus metadata check; Ruff; mypy | Pass |
| Deterministic behavior | V4 matrix `60/60`; autonomous trajectories `18/18`; personas `15/15` | Pass |
| Frontend and browser | lint, Vitest, production build, Playwright e2e | Pass |
| Runtime capacity | Redis-backed 50-turn/two-worker pilot-load contract | Pass |
| Compose wiring | PostgreSQL, Redis, Qdrant, backend, gateway smoke | Pass |
| Evaluation control plane | replay/source payload contracts, fail-closed evaluator/provider handling, Promptfoo wrapper | Pass |
| Live-agent workflow contract | manual-only `workflow_dispatch`, protected `pilot`, Redis service, corpus preflight, artifact upload | Pass |

## Not proven and therefore still release-blocking

1. The GitHub `pilot` environment does not exist in the connected account
   (secret/variable lookup returns HTTP 404). No provider-backed live run has
   been dispatched, so there is no current autonomous quality or promotion
   result.
2. No deployment-specific smoke has been run with production PostgreSQL,
   Qdrant, Redis, OpenAI, OIDC, HTTPS/TLS, and network policy.
3. Monitoring, alert delivery, backup/PITR restore, rollback execution, and
   authenticated two-user isolation have not been measured against a deployed
   service.
4. Production p95 time-to-first-event and completion latency have not been
   measured with real providers. The deterministic 50-turn load job proves the
   admission contract, not provider latency.
5. The private GitHub repository still has empty description, homepage, and
   topics. Configure those through an authenticated repository administrator if
   they are required for release hygiene.

## Decision

Keep `pipeline-v4` as the default. Keep `pipeline-agent` feature-flagged and
do not promote it until the protected live workflow produces a complete
artifact with provider/evaluator/source evidence and all configured thresholds
pass. Do not treat a missing `pilot` environment as a failed legal-quality
score; it is an external setup blocker.

The evaluation framework has no human-reviewer or legal-approval dependency.
Corpus activation still requires technical source hashes, provenance,
effective-date metadata, amendment consistency, and an immutable index audit.

## Operator handoff

After the `pilot` environment is configured, dispatch the workflow from the
exact release commit and retain its artifact. Then run the production smoke,
backup/restore, rollback, authenticated isolation, monitoring, and real-latency
checks listed in [Production Promotion](production-promotion.md) before making
a pilot or production decision.
