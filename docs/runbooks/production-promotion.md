# Production Corpus Promotion

Production legal chat is gated by technical corpus integrity and runtime
evidence. The repository does not model human legal approval as a deployment
dependency; source freshness and legal interpretation remain product/operator
responsibilities outside this framework acceptance loop.

## Autonomous-agent pilot gate

`pipeline-agent` remains feature-flagged until the manually dispatched
`Live Agent Evaluation` workflow passes against the protected `pilot`
environment. The workflow runs the checked-in 50-case benchmark through the
actual autonomous runtime and requires a pass rate of 70%, statutory-anchor
accuracy of 80%, and context recall of 75%. Its JSON artifact is the promotion
evidence; deterministic pull-request checks do not replace this live gate.
Every case must also report `evaluator_status: ok` and
`provider_status: ok`. An unavailable judge, provider, terminal event, or
source payload fails promotion even when aggregate percentages remain above
threshold.

See the [Live Agent Evaluation runbook](live-agent-eval.md) for the required
`pilot` secrets, Qdrant collection variable, Redis service, dispatch procedure,
and artifact retention contract.

## Release Gates

Before starting a production backend, configure a real PostgreSQL URL, Qdrant
endpoint, OpenAI key, at least one authentication mechanism (OIDC, service
token, or legacy compatibility key), and HTTPS `ALLOWED_ORIGINS` when the UI is
cross-origin. `POSTGRES_PASSWORD` is required by Compose and has no insecure
default. The backend rejects production startup when auth is disabled, rate
limiting is fail-open, trace debugging is enabled, either legal safety gate is
disabled, or local/HTTP CORS origins are configured.

The technical corpus audit and the independent legal-readiness manifest are
separate release gates. The repository manifest starts blocked and contains no
reviewer or sign-off. That state must not prevent process startup: `/health`
continues to report liveness and `/ready` reports `degraded` while technical
dependencies are healthy. Legal chat and case routes safe-stop until every
requested EPR provision has a matching reviewer record, reviewed interval, and
subject hash; chitchat, authentication, history, feedback, and explicit web
research remain separate capabilities.

Run these from the exact release commit:

```powershell
python -m scripts.sync_corpus_metadata --check
python -m scripts.audit_corpus
```

Review the audit for:

- source and signed-source hashes matching the manifest;
- complete amendment relationships and technical operation validation;
- active anchors and source provenance for every indexed chunk;
- rule-pack linkage to the same corpus hash;
- immutable collection name and index schema/embedding metadata;
- synchronized source snapshot metadata and a reproducible corpus hash.

The current repository records technical amendment readiness without turning a
benchmark fixture into legal ground truth. If technical integrity is absent,
the active alias remains unchanged and the affected capabilities fail closed.
The legal-readiness manifest is hashed separately from the corpus and must
reference the exact corpus, amendment-map, and rule-pack hashes. It is not
considered a legal approval until an authorized reviewer signs the relevant
scope entries.

## Bounded EPR Scope

Milestone 1 only permits the bounded EPR scope of Điều 77–86 and Phụ lục XXII.
No Nghị định 05/2025/NĐ-CP or Nghị định 48/2026/NĐ-CP ingestion, temporal
materialization, or Universal Corpus expansion is part of this release. Any
future corpus expansion needs its own technical audit, legal-readiness scope,
and explicit production promotion decision. `ENABLE_UNIVERSAL_RETRIEVAL`
remains `false` in production.

## Build and Promote Qdrant

The index job derives an immutable collection from the corpus hash, audits all
points, and only then atomically switches the `law_collection` alias:

```powershell
python -m scripts.ensure_law_index
```

Run it with the production environment and synchronized manifest. The previous
alias target is retained and printed as `rollback_collection`; never delete it
until the release soak and rollback window expire. A failed technical audit or
missing source metadata must leave the active alias unchanged.

## Deploy Order

1. Apply database migrations and complete the owner-mapping audit/apply.
2. Build and audit the immutable Qdrant collection without changing the active
   alias.
3. Promote the alias atomically after all release gates pass.
4. Deploy backend and frontend together, with browser API-key configuration
   removed and OIDC settings present.
5. Check `/api/v1/ready`, `/api/v1/health`, `/api/v1/me`, authenticated history,
   one legal lookup, source drawer, case save, feedback, and a second-user
   ownership denial.

Monitor authentication failures, cross-owner denials, capability reasons,
stopped turns, SSE error codes, source rejection, feedback failures, corpus
version/hash, retrieval latency, and assessment outcomes.

The `/metrics` gateway path is restricted to loopback and private scrape
networks and proxies to the authenticated backend metrics route. Keep the
reverse proxy behind TLS in any user-facing deployment.
