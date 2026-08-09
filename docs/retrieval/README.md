# Retrieval benchmark and candidate-index protocol

`docs/retrieval/baseline_manifest.json` freezes the committed source corpus.
It is not a performance claim until a named Qdrant collection has been tested.

Create or refresh the source-only baseline manifest:

```powershell
python -m scripts.retrieval_benchmark
```

Build a separate structure-aware candidate. Do not point this command at the
production collection:

```powershell
$env:LAW_COLLECTION = "law_collection_legal_structure_v2"
$env:CORPUS_VERSION = "epr-law-structure-v2"
$env:CHUNKING_STRATEGY = "legal_structure_v1"
python -m scripts.build_index
python -m scripts.retrieval_benchmark --run-retrieval --collection $env:LAW_COLLECTION --chunking-strategy $env:CHUNKING_STRATEGY --output docs/retrieval/candidate_legal_structure_v2.json
```

Promote only when the candidate has no regression in P@1, NDCG@3, or Recall@5,
has `explicit_article_hit_at_3 = 1.0`, passes `scripts.audit_law_collection`,
and preserves source metadata (`Parent_Dieu`, hierarchy and source offsets).
Keep the old collection and its `CORPUS_VERSION` available for rollback.
