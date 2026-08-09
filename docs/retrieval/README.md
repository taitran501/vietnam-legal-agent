# Retrieval benchmark and candidate-index protocol

The repository freezes both source data and measured collection results. The
source corpus contains 49 FAQ entries and 178 legal records.

## Accepted local snapshot

| Collection | Strategy | Points | P@1 | NDCG@3 | Recall@5 | Article hit@3 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `law_collection_baseline_v1` | sliding window | 461 | 0.9375 | 0.9375 | 0.9375 | 1.0 |
| `law_collection_legal_structure_v2` | `Điều -> Khoản -> Điểm` | 1,989 | 0.9375 | 0.9375 | 0.9375 | 1.0 |

The values are from the same 16-query live dense + BM25-style hybrid +
heuristic-rerank protocol. Both collection audits passed. The candidate has no
metric regression, has complete explicit-article hit@3, preserves source
metadata, and is marked `promotable: true` in
`candidate_legal_structure_v1.json`.

Nightly/release automation sets `LIVE_EVAL_QUERY_BUDGET=16`; the benchmark
enforces that value as a hard cap on variable-cost live retrieval calls.

Committed evidence:

- `baseline_manifest.json`: source hashes, deterministic offline metrics, live
  baseline metrics, and baseline audit summary.
- `baseline_collection_audit.json`: named baseline collection audit.
- `candidate_legal_structure_v1.json`: candidate metrics and promotion checks.
- `candidate_collection_audit.json`: named candidate collection audit.

## Reproduce the baseline

Create or refresh the source manifest:

```powershell
python -m scripts.retrieval_benchmark
```

Audit and benchmark a configured baseline collection:

```powershell
$env:LAW_COLLECTION = "law_collection_baseline_v1"
python -m scripts.audit_law_collection --output docs/retrieval/baseline_collection_audit.json
python -m scripts.retrieval_benchmark `
  --run-retrieval `
  --collection $env:LAW_COLLECTION `
  --collection-audit docs/retrieval/baseline_collection_audit.json `
  --output docs/retrieval/baseline_manifest.json
```

## Build a structure-aware candidate

Always use a new collection. Never overwrite the production collection.

```powershell
$env:LAW_COLLECTION = "law_collection_legal_structure_v2"
$env:CORPUS_VERSION = "epr-law-structure-v2"
$env:CHUNKING_STRATEGY = "legal_structure_v1"
$env:SUMMARY_SOURCE_COLLECTION = "law_collection_baseline_v1"
$env:SUMMARY_CACHE_PATH = "artifacts/index/summary_cache.json"
$env:EMBED_BATCH_SIZE = "32"
$env:RECREATE_COLLECTION = "true"
python -m scripts.build_index
python -m scripts.audit_law_collection --output docs/retrieval/candidate_collection_audit.json
python -m scripts.retrieval_benchmark `
  --run-retrieval `
  --collection $env:LAW_COLLECTION `
  --chunking-strategy $env:CHUNKING_STRATEGY `
  --baseline docs/retrieval/baseline_manifest.json `
  --collection-audit docs/retrieval/candidate_collection_audit.json `
  --output docs/retrieval/candidate_legal_structure_v1.json
```

The builder reuses exact summaries from the baseline collection or the local
summary cache and batches embeddings. Structure-aware chunks retain the parent
article, heading hierarchy, character offsets, and original source text.

## Promotion and rollback

Promote only if all checks are true:

- P@1, NDCG@3, and Recall@5 do not decrease.
- Explicit article hit@3 is 1.0.
- The named live collection audit passes schema, hygiene, duplicate, legal-anchor,
  and source-metadata checks.
- The benchmark actually queried the named collection; offline-only metrics are
  insufficient.

After publishing the collection, update `LAW_COLLECTION` and `CORPUS_VERSION`
together so answer-cache keys cannot cross corpus versions. Keep the previous
collection and version available for rollback. Cross-encoder reranking remains
optional and should run in shadow mode before it affects user ranking.
