# Pipeline V3 retrieval evaluation

This directory keeps the historical V1/V2 benchmark artifacts as a baseline
record. They are **not** an acceptance claim for Pipeline V3: V3 uses a new
canonical corpus contract, a new collection identity, fixed embeddings, and a
different retrieval contract.

## V3 collection protocol

1. Update `data/corpus_manifest.json` and the source extraction only after the
   official source can be audited.
2. Run `python -m scripts.ensure_law_index` against a new versioned collection.
   It computes the corpus SHA, performs the canonical source/chunk audit, and
   atomically switches the `law_collection` alias only after the index audit
   succeeds.
3. Use `GET /api/v1/ready` to confirm the alias, point count, corpus SHA,
   schema, and `openai-text-embedding-3-small-v1` profile agree with runtime.
4. Run the V3 retrieval suite before promotion. Record the resulting corpus
   SHA, index target, commit SHA, profile, and metrics in the acceptance report.

The indexer must be idempotent: a complete collection with matching corpus SHA,
schema, chunking profile, model, and dimensions exits without embedding calls.
It never overwrites a previous collection; rollback means retargeting the alias
to a verified older collection.

## Required V3 gates

| Gate | Required result |
| --- | --- |
| Canonical chunk audit | 100% provenance, unique chunk IDs, valid offsets |
| Explicit Article retrieval | Hit@1 = 100% |
| Multi-Article retrieval | coverage@5 = 100% |
| P@1 / NDCG@3 / Recall@5 | each at least 0.9375 |
| FAQ runtime source/action | 0 occurrences |
| Citation support | every legal claim structurally and semantically verified |
| Readiness | missing/mismatched corpus returns HTTP 503 |

## Historical artifacts

`baseline_manifest.json`, `candidate_legal_structure_v1.json`, and their audit
files document the earlier 16-query experiment. They remain useful as a
historical regression reference but must not be compared directly with V3 until
the same V3 corpus contract and test manifest are used.

The deterministic V3 test manifests live in
`tests/eval/pipeline_v3_manifest.py`. The live runner should write generated
reports under ignored `artifacts/`; only a reviewed, concise acceptance result
belongs in `docs/acceptance_report.md`.
