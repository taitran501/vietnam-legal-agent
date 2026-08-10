# Pipeline V3 acceptance record

This document separates reproducible local checks from live checks that require
the configured OpenAI embedding service and a real Qdrant collection. Do not
mark a live gate complete from mocks or deterministic doubles.

## Baseline

- Legacy baseline tag: `legacy-v1.0.0`.
- Historical source extraction: 49 FAQ records and 178 raw legal records.
- V3 source policy: FAQ is UI/evaluation-only; untraceable Appendix rows are
  excluded from the production corpus.
- V3 embedding profile: `openai-text-embedding-3-small-v1` (`1536` dimensions).

## Implemented local contracts

- Canonical `LegalDocument`/`LegalChunk`, source hash, structure-aware chunks,
  provenance/offset/duplicate audit, and versioned index aliasing.
- Bounded route contracts for lookup, explanation/comparison, assessment,
  checklist, explicit web research, chitchat, and out-of-scope stop.
- Shared legal retrieval contract: exact anchor, dense + lexical candidates,
  RRF, rerank, diversity, and route-specific evidence limits.
- Explicit web route only; no FAQ runtime route/source and no automatic web
  fallback.
- Strict legal evidence gate; structural citation verification plus one batch
  claim-support verifier; one repair maximum.
- Readiness endpoint, source/profile metadata in SSE, owner-scoped trace API,
  and a debug-only React trace drawer.

## Local evidence

Record the command output from the final candidate commit below.

| Check | Result | Notes |
| --- | --- | --- |
| `pytest -q` | pending final run | Includes workflow, corpus, API, trace, and V3 manifests |
| `ruff check ...` | pending final run | Backend, core, scripts, agent, and tests |
| `mypy src/epr_agent` | pending final run | Typed agent core |
| React Vitest/lint/build | pending final run | No browser E2E claim without a run |
| Docker Compose smoke | pending final run | Includes one-shot indexer and `/ready` |

## Live V3 retrieval gates

These gates are intentionally unfilled until the versioned V3 index has been
built from the canonical corpus with `text-embedding-3-small`.

| Field | Result |
| --- | --- |
| Commit SHA | pending |
| Corpus SHA | pending |
| Collection target / alias | pending |
| Embedding profile | `openai-text-embedding-3-small-v1` |
| Explicit-article Hit@1 | pending, required 1.0 |
| Multi-anchor coverage@5 | pending, required 1.0 |
| P@1 | pending, required >= 0.9375 |
| NDCG@3 | pending, required >= 0.9375 |
| Recall@5 | pending, required >= 0.9375 |
| E2E p95 | pending, required <= 15 s |

Merge to `main` requires every mandatory local and live gate above to be
recorded as passing. A collection or evaluation failure must leave the prior
alias and baseline intact.
