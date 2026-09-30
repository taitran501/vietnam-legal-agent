"""Versioned corpus descriptors used by the bounded legal workflow."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CorpusDescriptor:
    """Stable runtime identity for one legal corpus.

    This descriptor keeps cache and trace records independent of one
    particular statutory domain or vector-store collection.
    """

    corpus_id: str
    collection_alias: str
    corpus_version: str
    scope: str
    corpus_sha: str = ""
    embedding_profile: str = "openai-text-embedding-3-small-v1"
    citation_requirements: tuple[str, ...] = ("source", "legal_anchor", "provenance")


def vietnamese_law_corpus(
    *,
    collection_alias: str,
    corpus_version: str,
    corpus_sha: str = "",
    embedding_profile: str = "openai-text-embedding-3-small-v1",
) -> CorpusDescriptor:
    return CorpusDescriptor(
        corpus_id="vietnamese_law",
        collection_alias=collection_alias,
        corpus_version=corpus_version,
        scope="Vietnamese legal corpus",
        corpus_sha=corpus_sha,
        embedding_profile=embedding_profile,
    )
