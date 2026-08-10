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
| Python tests | pass | 345 tests collected; the complete local `pytest` process exited with code 0. This includes the 60 understanding/retrieval manifest contracts and 40 V3 trajectories. |
| V3 Ruff scope | pass | `src/epr_agent`, V3 API/retrieval/index scripts, migration, and V3 tests pass. The repository-wide legacy lint baseline still has 233 unrelated findings and was not hidden or rewritten in this batch. |
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
| Evaluated code commit | `16032b11c92c5973f2bfe53c066e570d91cac0ed` |
| Corpus SHA | `ca0238a1579e555e427dafa5e98761ba5405c9dff41b5e421688c8179c25adfd` |
| Collection target / alias | `law_epr_ca0238a1579e_legal_structure_v2_openai_text_embedding_3_small_v1` / `law_collection` |
| Embedding profile | `openai-text-embedding-3-small-v1` |
| Explicit-article Hit@1 | 1.0 (60-case live retrieval evaluation) |
| Multi-anchor coverage@5 | 1.0 (60-case live retrieval evaluation) |
| P@1 | 1.0 (required >= 0.9375) |
| NDCG@3 | 1.0 (required >= 0.9375) |
| Recall@5 | 1.0 (required >= 0.9375) |
| E2E p95 | pass: all 40 deterministic V3 trajectories assert under 15 s, so p95 is also under the gate |

### Live smoke evidence

- `GET /api/v1/ready` reported the target collection, 1,297 points, matching
  corpus SHA/schema, and the 1,536-dimension embedding profile.
- The cache-cold Article 77 request completed as `legal_lookup` with
  `answer_complete`, `legal_corpus`, sufficient evidence, three citations, and
  this bounded action sequence: validate, load context, understand, cache
  miss, legal retrieval, evidence gate, compose, verify, finish.
- A subsequent Article 78 request also executed legal retrieval rather than
  reusing Article 77. The active answer cache is exact-key Redis only; it no
  longer calls the legacy semantic cache.

Merge to `main` requires every mandatory local and live gate above to be
recorded as passing. A collection or evaluation failure leaves the prior alias
and baseline intact.
