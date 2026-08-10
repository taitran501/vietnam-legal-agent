# Pipeline V3: legal retrieval contract

## Canonical source boundary

`scripts.canonical_corpus` converts the raw `data/law.json` extraction into
`LegalDocument` and `LegalChunk` contracts. A record can enter the production
index only if it points to the declared primary source and has a legal heading,
text, source pages, source hash, and valid offsets. FAQ and editorial summaries
are not legal evidence.

The structural chunker never crosses an Article boundary. It splits at
`Điều -> Khoản -> Điểm`, merges very short adjacent units inside the same
Article, splits long units at sentence boundaries, and preserves the exact
source range and unmodified `original_text`. `retrieval_text` and
`lexical_text` are deterministic fields built from document identity, heading
hierarchy, legal anchor, and original legal text. No LLM summary enters an
embedding.

## Index contract

The active collection must use `openai-text-embedding-3-small-v1`:

- `text-embedding-3-small`, 1536 dimensions;
- identical deterministic preprocessing for document and query;
- versioned by corpus SHA, schema, chunking, and embedding profile.

`python -m scripts.ensure_law_index` creates a versioned collection when one
is missing, audits it, runs its smoke checks, and atomically repoints
`law_collection`. A matching collection exits without calling the embedding
API. The collection alias is never overwritten in place.

## Query plan and retrieval

The graph parses named document, Article, Clause, and Point references before
the structured `QueryPlan` model runs. The model may rewrite a dependent
follow-up and classify a declared route, but the validator restores any parsed
anchor the model omitted.

Every legal route shares this retrieval core:

1. exact metadata lookup for explicit anchors;
2. dense top-20 and BM25-style top-20 in parallel;
3. RRF fusion with `k=60`;
4. stable `chunk_id` deduplication;
5. heuristic rerank to 10 using anchor, document/heading, phrase coverage, and
   RRF signals;
6. diversity cap of two chunks per Article after reranking, except for a
   multi-anchor request;
7. route-specific evidence selection.

If an explicitly requested Article is not in the collection, the workflow
returns a safe stop rather than a semantically similar Article. If a non-anchor
query has weak evidence, one query expansion/retrieval retry is permitted; a
run has at most two legal retrieval attempts.

## Evidence and output

The evidence gate accepts a legal chunk only when it has provenance, corpus
version/SHA, embedding profile, stable ID, and legal anchor. Each selected
anchor must be covered for comparison requests. Answer schemas cite chunk IDs;
display citations are created only after verification.

Verification first checks citation structure and source/anchor existence. One
structured LLM batch then checks that each material legal claim is supported by
the cited evidence. One repair may be attempted. A response with no supported
legal claim cannot end as `answer_complete`.

Web research is a separate `research_web` route. The user selects it through
`mode=research_web` or the safe-stop CTA; it is never an automatic fallback and
does not provide missing company facts.
