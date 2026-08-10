"""Versioned corpus descriptors used by the bounded legal workflow."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CorpusDescriptor:
    """Stable runtime identity for one legal corpus.

    The first deployment registers only EPR.  Keeping this small descriptor at
    the graph boundary prevents cache and trace records from being tied to a
    hard-coded Qdrant collection when another legal corpus is introduced.
    """

    corpus_id: str
    collection_alias: str
    corpus_version: str
    scope: str
    corpus_sha: str = ""
    embedding_profile: str = "openai-text-embedding-3-small-v1"
    citation_requirements: tuple[str, ...] = ("source", "legal_anchor", "provenance")


def epr_corpus(
    *,
    collection_alias: str,
    corpus_version: str,
    corpus_sha: str = "",
    embedding_profile: str = "openai-text-embedding-3-small-v1",
) -> CorpusDescriptor:
    return CorpusDescriptor(
        corpus_id="epr",
        collection_alias=collection_alias,
        corpus_version=corpus_version,
        scope="Vietnamese EPR legal corpus",
        corpus_sha=corpus_sha,
        embedding_profile=embedding_profile,
    )
