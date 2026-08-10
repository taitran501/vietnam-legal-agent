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

| Check | Result | Notes |
| --- | --- | --- |
| Python tests | pass | 326 tests collected; the complete local `pytest` process exited with code 0. This includes the 60 understanding/retrieval manifest contracts and 40 V3 trajectories. |
| Repository Ruff | pass | `ruff check .` passes. The unused legacy semantic cache and its tests were removed; mechanical lint fixes retain existing runtime behaviour. |
| `mypy src/epr_agent` | pass | Success for 28 source files. |
| React | pass | Vitest: 5 tests in 3 files; ESLint passed; production build passed. Vite reports only a non-blocking 1.07 MB pre-gzip chunk warning. |
| Playwright | pass | 9/9 browser flows: desktop/mobile/tablet behaviour, missing facts, safe stop, evidence drawer, SSE lookup, and case resume. |
| Docker Compose | pass | Backend rebuilt; `/api/v1/ready` returned 200 with PostgreSQL, Redis, Qdrant, and OpenAI configuration all ready. |
| Indexer idempotence | pass | Second indexer run audited the existing target and confirmed the alias without an embedding request. |

### Canonical audit

- Raw legal records: 178; accepted: 169; excluded: 9 Appendix summary rows
  without verified source pages.
- Production chunks: 1,297; missing provenance: 0; duplicate chunk IDs: 0;
  invalid offsets: 0.
- Runtime uses no FAQ action, FAQ collection, or FAQ evidence. `faq.json`
  remains UI/evaluation-only.

## Live V3 retrieval gates

These gates are intentionally unfilled until the versioned V3 index has been
built from the canonical corpus with `text-embedding-3-small`.

| Field | Result |
| --- | --- |
| Evaluated code commit | `c982b777954fa7c0eb7ef646206e67aa527f1f68` |
| Corpus SHA | `ca0238a1579e555e427dafa5e98761ba5405c9dff41b5e421688c8179c25adfd` |
| Collection target / alias | `law_epr_ca0238a1579e_legal_structure_v2_openai_text_embedding_3_small_v1` / `law_collection` |
| Embedding profile | `openai-text-embedding-3-small-v1` |
| Explicit-article Hit@1 | 1.0 (60-case live retrieval evaluation) |
| Multi-anchor coverage@5 | 1.0 (60-case live retrieval evaluation) |
| P@1 | 1.0 (required >= 0.9375) |
| NDCG@3 | 1.0 (required >= 0.9375) |
| Recall@5 | 1.0 (required >= 0.9375) |
| Real-stack E2E p95 | 3,250.04 ms across 40 cache-cold Docker requests; maximum 4,019.99 ms; all 40 under 15 s |

### Live smoke evidence

- `GET /api/v1/ready` reported the target collection, 1,297 points, matching
  corpus SHA/schema, and the 1,536-dimension embedding profile.
- The cache-cold Article 77 request completed as `legal_lookup` with
  `answer_complete`, `legal_corpus`, sufficient evidence, three citations, and
  this bounded action sequence: validate, load context, understand, cache
  miss, legal retrieval, evidence gate, compose, verify, finish.
- A subsequent Article 78 request also executed legal retrieval rather than
  reusing Article 77. The active answer cache is exact-key Redis only; the
  obsolete semantic-cache component was removed.
- The p95 run used 40 distinct Article queries through the running Docker
  backend with V3 answer-cache keys cleared first. All runs ended
  `answer_complete` with cache miss/store paths; p50 was 2,417.87 ms.

Merge to `main` requires every mandatory local and live gate above to be
recorded as passing. A collection or evaluation failure leaves the prior alias
and baseline intact.
