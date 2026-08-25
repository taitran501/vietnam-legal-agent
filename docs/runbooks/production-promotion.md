# Production Corpus Promotion

Production legal chat is intentionally blocked until each legal domain corpus
has both technical integrity and external legal approval. A successful build or
a preview run is not approval.

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

## Release Gates

Before starting a production backend, configure a real PostgreSQL URL, Qdrant
endpoint, OpenAI key, at least one authentication mechanism (OIDC, service
token, or legacy compatibility key), and HTTPS `ALLOWED_ORIGINS` when the UI is
cross-origin. `POSTGRES_PASSWORD` is required by Compose and has no insecure
default. The backend rejects production startup when auth is disabled, rate
limiting is fail-open, trace debugging is enabled, or local/HTTP CORS origins
are configured.

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
- external reviewer, approval date, and `legal_review_status: approved`.

The current repository deliberately records technical amendment readiness
without self-asserting legal approval. If approval is absent, leave runtime in
`production` and expect `legal_chat` and `case_workflow` to be blocked.

## Multi-Domain Corpus Promotion

Each legal domain in the corpus follows its own activation boundary. The primary
law collection and any supplementary corpuses (e.g., Pháp điển) each require
an independent domain reviewer to approve their source and effective date before
production activation. `ENABLE_UNIVERSAL_RETRIEVAL` must remain `false` in
production until its domain review is recorded; the production configuration
rejects the flag while that gate is pending.

## Build and Promote Qdrant

The index job derives an immutable collection from the corpus hash, audits all
points, and only then atomically switches the `law_collection` alias:

```powershell
python -m scripts.ensure_law_index
```

Run it with the production environment and approved manifest. The previous
alias target is retained and printed as `rollback_collection`; never delete it
until the release soak and rollback window expire. A failed technical audit or
missing approval must leave the active alias unchanged.

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
