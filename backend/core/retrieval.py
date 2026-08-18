"""V3 legal retrieval boundary.

This module owns Qdrant connection/vector-store lifecycle only.  Every runtime
legal query is delegated to :mod:`backend.core.ensemble_retrieval`, which is
the one canonical dense + BM25 + RRF + heuristic-rerank implementation.
Legacy SelfQuery, LLM query construction, counting-answer synthesis, and a
second reranking path were deliberately removed so they cannot bypass V3
evidence and citation gates.
"""

from __future__ import annotations

import asyncio
import threading
from functools import lru_cache
from typing import TYPE_CHECKING

import tiktoken
from langchain_core.documents import Document

from backend.config import get_settings

if TYPE_CHECKING:
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient

_qdrant_client: QdrantClient | None = None
_qdrant_client_lock = threading.Lock()


def _count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """Count tokens with a deterministic fallback for Vietnamese text."""

    try:
        return len(tiktoken.encoding_for_model(model).encode(text))
    except Exception:  # noqa: BLE001 - token counting has a deterministic fallback
        return int(len(text) / 3.5)


def _truncate_text(text: str, max_tokens: int = 1000, model: str = "gpt-3.5-turbo") -> str:
    """Trim text on token boundaries where possible."""

    try:
        encoding = tiktoken.encoding_for_model(model)
        tokens = encoding.encode(text)
        return text if len(tokens) <= max_tokens else encoding.decode(tokens[:max_tokens]) + "..."
    except Exception:  # noqa: BLE001 - truncation has a deterministic fallback
        return text[: max_tokens * 4] + "..."


def _get_qdrant_client() -> QdrantClient:
    """Return the configured local or cloud Qdrant client."""

    from qdrant_client import QdrantClient

    global _qdrant_client
    if _qdrant_client is not None:
        return _qdrant_client
    with _qdrant_client_lock:
        if _qdrant_client is not None:
            return _qdrant_client
        settings = get_settings()
        if settings.use_qdrant_cloud and settings.qdrant_cloud_url and settings.qdrant_api_key:
            _qdrant_client = QdrantClient(
                url=settings.qdrant_cloud_url,
                api_key=settings.qdrant_api_key,
                timeout=10,
            )
        elif settings.qdrant_url:
            _qdrant_client = QdrantClient(url=settings.qdrant_url, timeout=10)
        else:
            try:
                _qdrant_client = QdrantClient(path=settings.qdrant_local_path, timeout=10)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Local Qdrant path initialization failed (%s); fallback to memory client", exc)
                _qdrant_client = QdrantClient(":memory:", timeout=10)
        return _qdrant_client


def close_qdrant_client() -> None:
    """Release process-local Qdrant resources and cached vector-store state."""

    global _qdrant_client
    with _qdrant_client_lock:
        if _qdrant_client is not None:
            _qdrant_client.close()
            _qdrant_client = None
    _get_law_vectorstore.cache_clear()


@lru_cache(maxsize=1)
def _get_law_vectorstore() -> QdrantVectorStore:
    """Build the V3 versioned-law vector-store view through its alias."""

    from langchain_qdrant import QdrantVectorStore

    from backend.core.llm_instances import get_embeddings

    settings = get_settings()
    return QdrantVectorStore(
        client=_get_qdrant_client(),
        collection_name=settings.law_collection,
        embedding=get_embeddings(),
        content_payload_key="Text",
        metadata_payload_key="metadata",
    )


def _enrich_docs_from_qdrant(docs: list[Document], collection_name: str) -> list[Document]:
    """Attach root payload metadata required by V3 evidence and trace gates."""

    point_ids: list[str] = [
        str(document.metadata["_id"])
        for document in docs
        if document.metadata.get("_id") is not None
    ]
    if not point_ids:
        return docs
    points = _get_qdrant_client().retrieve(
        collection_name=collection_name,
        ids=point_ids,
        with_payload=True,
        with_vectors=False,
    )
    payloads = {str(point.id): dict(point.payload or {}) for point in points}
    for document in docs:
        payload = payloads.get(str(document.metadata.get("_id", "")), {})
        for key, value in payload.items():
            if key != "Text":
                document.metadata.setdefault(key, value)
    return docs


def retrieve_legal(
    query: str,
    *,
    required_anchors: list[str] | None = None,
    metadata_filters: dict[str, str] | None = None,
    top_k: int = 10,
) -> list[Document]:
    """Run the sole V3 hybrid legal retrieval implementation."""

    from backend.core.ensemble_retrieval import retrieve_legal_ensemble

    return retrieve_legal_ensemble(
        query,
        k=top_k,
        required_anchors=required_anchors,
        metadata_filters=metadata_filters,
    )


async def retrieve_legal_async(
    query: str,
    *,
    required_anchors: list[str] | None = None,
    metadata_filters: dict[str, str] | None = None,
    top_k: int = 10,
) -> list[Document]:
    """Execute blocking Qdrant retrieval away from the event loop."""

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: retrieve_legal(
            query,
            required_anchors=required_anchors,
            metadata_filters=metadata_filters,
            top_k=top_k,
        ),
    )
