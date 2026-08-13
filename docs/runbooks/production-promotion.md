# Production corpus promotion

Production legal chat is intentionally blocked until the corpus has both
technical integrity and external legal approval. A successful build or a
preview run is not approval.

## Release gates

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

## Build and promote Qdrant

The index job derives an immutable collection from the corpus hash, audits all
points, and only then atomically switches the `law_collection` alias:

```powershell
python -m scripts.ensure_law_index
```

Run it with the production environment and approved manifest. The previous
alias target is retained and printed as `rollback_collection`; never delete it
until the release soak and rollback window expire. A failed technical audit or
missing approval must leave the active alias unchanged.

## Deploy order

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
