# External Release Gates

The repository can validate code contracts and a deterministic local preview.
The following gates require authority or runtime state outside this checkout.
They must remain explicit in release notes.

## Legal Corpus Approval

The technical checks can confirm hashes, source structure, amendment links, and
rule-pack consistency. They cannot grant legal approval. A maintainer with
domain authority must set and review the approved corpus status and effective
as-of date before enabling production legal capability. Preview mode is the
safe default while that field is pending.

This applies across all legal domains in the corpus. Each domain's content
(including the primary law collection and any supplementary corpuses such as
Pháp điển) requires an independent source review recorded before its production
activation. The download lock and SQLite row-count checks establish
reproducibility, not legal authority.

## Production Runtime

Run the deployment-specific readiness and smoke checks against the actual
PostgreSQL, Qdrant, Redis, OpenAI, OIDC, and official-web provider
configuration. Local deterministic SSE tests do not prove credentials,
network policy, backups, monitoring, rate limits, or p95 latency in production.
See [local preview](local-preview.md) and
[production promotion](production-promotion.md) for the repository-side
steps and boundaries.

## GitHub Repository Metadata

The repository is private and the connected read-only inspection confirmed
that description, homepage, topics, and license metadata are not configured in
the returned repository record. The local `LICENSE` file is now present, but
that does not update GitHub's settings. An authenticated repository admin must
set the desired visibility/description/homepage/topics and verify them on
GitHub. No local code change can truthfully claim this gate is complete.
