# External Release Gates

The repository can validate code contracts and a deterministic local preview.
The following gates require authority or runtime state outside this checkout.
They must remain explicit in release notes.

## Source Snapshot Integrity

The technical checks can confirm hashes, source structure, amendment links, and
rule-pack consistency, and effective-date metadata. They are the source of
truth for the engineering release gate; no reviewer identity or approval field
is required by the runtime.

This applies across all legal domains in the corpus. Each domain's content
(including the primary law collection and any supplementary corpuses such as
Pháp điển) must carry versioned source metadata before activation. The download
lock and SQLite row-count checks establish reproducibility for the framework;
they do not attempt to author legal ground truth.

## Production Runtime

Run the deployment-specific readiness and smoke checks against the actual
PostgreSQL, Qdrant, Redis, OpenAI, OIDC, and official-web provider
configuration. Local deterministic SSE tests do not prove credentials,
network policy, backups, monitoring, rate limits, or p95 latency in production.
See [local preview](local-preview.md) and
[production promotion](production-promotion.md) for the repository-side
steps and boundaries.

## GitHub Repository Metadata

Checked on 2026-10-28: the repository is public, GitHub reports the MIT license,
and the description is `Vietnamese legal research app with source-grounded
retrieval and preliminary case workflows`. Topics are `vietnam`, `legal-tech`,
`legal-research`, `ai-agent`, and `retrieval-augmented-generation`. The homepage
is intentionally blank because there is no public demo to link. These metadata
settings do not establish production readiness or legal approval.
