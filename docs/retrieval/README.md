# Pipeline V4 retrieval evaluation

This directory keeps the historical V1/V2 benchmark artifacts as a baseline
record. They are **not** an acceptance claim for Pipeline V4: V4 uses a new
canonical corpus contract, a new collection identity, fixed embeddings, and a
different retrieval contract.

## V4 collection protocol

1. Update `data/corpus_manifest.json` and the source extraction only after the
   official source can be audited.
2. Run `python -m scripts.ensure_law_index` against a new versioned collection.
   It computes the corpus SHA, performs the canonical source/chunk audit, and
   atomically switches the `law_collection` alias only after the index audit
   succeeds.
3. Use `GET /api/v1/ready` to confirm the alias, point count, corpus SHA,
   schema, and `openai-text-embedding-3-small-v1` profile agree with runtime.
4. Run the V4 retrieval suite before promotion. Record the resulting corpus
   SHA, index target, commit SHA, profile, and metrics in the acceptance report.

The indexer must be idempotent: a complete collection with matching corpus SHA,
schema, chunking profile, model, and dimensions exits without embedding calls.
It never overwrites a previous collection; rollback means retargeting the alias
to a verified older collection.

## Required V4 gates

| Gate | Required result |
| --- | --- |
| Canonical chunk audit | 100% provenance, unique chunk IDs, valid offsets |
| Explicit Article retrieval | Hit@1 = 100% |
| Multi-Article retrieval | coverage@5 = 100% |
| P@1 / NDCG@3 / Recall@5 | each at least 0.9375 |
| FAQ runtime source/action | 0 occurrences |
| Citation support | every legal claim structurally and semantically verified |
| Readiness | missing/mismatched corpus returns HTTP 503 |

## Current eval counts

The V4 deterministic eval manifest contains 125 cases:

- 60 retrieval cases
- 60 query-understanding cases
- 5 manifest cases

The current acceptance run comprises 574 passing pytest tests (3 skipped), 18
agent test cases, and 27 Playwright browser tests. See
[`docs/acceptance_status.md`](../acceptance_status.md) for the commit-scoped
evidence and remaining promotion gates.

## Historical experiments

The earlier 16-query baseline/candidate experiment is retained as historical
context only. Its generated manifests and audit JSON are intentionally not
versioned in this documentation folder: raw experiment output belongs under
the ignored `artifacts/` or `data/eval/` directories. It must not be compared
directly with V4 until the same V4 corpus contract and test manifest are used.

The deterministic V4 manifest and runner live in
`tests/eval/pipeline_v4_manifest.py` and `tests/eval/run_eval.py`. Generated
reports belong under ignored `data/eval/`; only a reviewed, concise
acceptance result belongs in `docs/pipeline_v4_acceptance_report.md`.
