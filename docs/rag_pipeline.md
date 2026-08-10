# Retrieval pipeline

This document describes the retrieval path used by the bounded EPR workflow.
The workflow is implemented in `src/epr_agent/`; retrieval is currently
provided through adapters around the existing `backend/core` implementation.

## 1. Offline indexing

The source files are:

- `data/faq.json` for UI suggestions and evaluation only; it is not a runtime source.
- `data/law.json` for structured legal articles and appendices.

Run `python -m scripts.build_index` after changing the legal corpus. The
builder creates the Qdrant collections used by the online service and stores
legal metadata such as article, chapter, and section labels with each record.
Generated audit reports and converted intermediate files belong under the
ignored `artifacts/` directory.

## 2. Context preparation

Before retrieval, the workflow loads recent conversation messages and the
active structured case. A short dependent follow-up such as “What about that
case?” is rewritten into a retrievable query using the recent context and
known case facts. The full conversation is not copied into the retrieval
query.

## 3. Hybrid legal retrieval

The legal retriever runs two candidate generators in parallel:

- Dense search: Qdrant vector search, normally up to twenty candidates after
  the configured candidate expansion.
- Lexical search: an in-memory Vietnamese tokenizer and lightweight BM25-style
  scoring over article headings, summaries, and text.

Explicit references such as “Điều 77” also receive a direct article lookup and
metadata boost. Candidates from the dense, lexical, and explicit-reference
paths are deduplicated by article and ranked by the heuristic reranker. The
reranker considers dense and lexical scores, token/phrase coverage, legal
metadata, and explicit article references. The default public retrieval result
contains up to ten ranked candidates. The workflow passes at most three
selected chunks to answer generation. `rerank_top_n` controls how many merged
candidates are considered before the final result is produced. If an explicitly
named article is absent, the workflow stops instead of substituting a similar article.

A cross-encoder reranker exists behind rollout and timeout controls. It can be
applied or run in shadow mode; the heuristic reranker remains the safe
fallback.

## 5. Evidence gate and answer generation

The evidence evaluator checks:

- at least the configured number of documents;
- enough non-empty content;
- legal source metadata or a valid web source; and
- an optional relevance check.

If evidence is sufficient, the generation adapter composes the answer,
assessment, or checklist. The citation verifier then checks that numbered
citations refer to returned evidence. One repair is allowed when verification
fails; otherwise the workflow stops safely.

If the query remains inside the EPR domain but the legal corpus is
insufficient, the workflow may call Tavily as a labelled web fallback. The web
result is still treated as evidence and is subject to citation checks.

## 6. What is deliberately not used

- FAQ records are not indexed or used as evidence. They remain available only
  as product examples and evaluation prompts.
- Assessment and checklist answers are not semantic-cache entries.
- Web search does not supply missing business facts.
- Retrieval scores alone do not determine a legal conclusion; explicit facts,
  evidence quality, and citation verification are required.
