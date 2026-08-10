"""Build or reuse a versioned EPR law collection, then atomically switch its alias.

This is intentionally a one-shot Compose service.  It never overwrites an
existing collection, and a matching collection exits before OpenAI embedding or
summarisation is called.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _configure() -> tuple[Any, str, str]:
    from backend.config import get_settings
    from scripts.canonical_corpus import corpus_sha256, load_document_manifest

    base = get_settings()
    corpus_id, corpus_version, _ = load_document_manifest(Path(base.corpus_manifest_path))
    digest = corpus_sha256(law_path=Path(base.law_data_path), manifest_path=Path(base.corpus_manifest_path))
    schema = base.index_schema_version.replace("-", "_")
    profile = base.embedding_profile.replace("-", "_")
    target = f"law_{corpus_id}_{digest[:12]}_{schema}_{profile}"
    os.environ["LAW_COLLECTION"] = target
    os.environ["CORPUS_ID"] = corpus_id
    os.environ["CORPUS_VERSION"] = corpus_version
    os.environ["CORPUS_SHA256"] = digest
    os.environ["CHUNKING_STRATEGY"] = base.chunking_profile.replace("-", "_")
    get_settings.cache_clear()
    return get_settings(), target, digest


def _client(settings):
    from qdrant_client import QdrantClient

    if settings.use_qdrant_cloud:
        return QdrantClient(url=settings.qdrant_cloud_url, api_key=settings.qdrant_api_key)
    if settings.qdrant_url:
        return QdrantClient(url=settings.qdrant_url)
    return QdrantClient(path=settings.qdrant_local_path)


def _matching_collection(client, collection: str, *, expected_count: int, digest: str, schema: str, settings) -> bool:
    try:
        info = client.get_collection(collection)
        if int(info.points_count or 0) != expected_count:
            return False
        points, _ = client.scroll(collection, limit=1, with_payload=True, with_vectors=False)
        payload = dict(points[0].payload or {}) if points else {}
        return (
            payload.get("Corpus_SHA256") == digest
            and payload.get("Index_Schema_Version") == schema
            and payload.get("Embedding_Profile") == settings.embedding_profile
            and int(payload.get("Embedding_Dimensions") or 0) == settings.embedding_dimensions
            and payload.get("Chunking_Strategy") == settings.chunking_profile
        )
    except Exception:  # noqa: BLE001 - a missing/partial collection is an intentional rebuild signal
        return False


def _audit(client, collection: str, *, expected_count: int, digest: str, schema: str, settings) -> None:
    info = client.get_collection(collection)
    if int(info.points_count or 0) != expected_count or expected_count == 0:
        raise RuntimeError("index_point_count_mismatch")
    offset = None
    seen: set[str] = set()
    anchors = 0
    while True:
        points, offset = client.scroll(collection, offset=offset, limit=256, with_payload=True, with_vectors=False)
        for point in points:
            payload = dict(point.payload or {})
            if payload.get("Corpus_SHA256") != digest or payload.get("Index_Schema_Version") != schema:
                raise RuntimeError("index_payload_version_mismatch")
            if (
                payload.get("Embedding_Profile") != settings.embedding_profile
                or int(payload.get("Embedding_Dimensions") or 0) != settings.embedding_dimensions
                or payload.get("Chunking_Strategy") != settings.chunking_profile
            ):
                raise RuntimeError("index_embedding_profile_mismatch")
            key = str(payload.get("document_id") or point.id)
            if key in seen:
                raise RuntimeError("index_duplicate_chunk")
            seen.add(key)
            required = ("legal_anchor", "source", "source_file", "Original_Text", "retrieval_text", "lexical_text", "Source_Start", "Source_End")
            if not all(payload.get(field) not in (None, "") for field in required):
                raise RuntimeError("index_missing_citation_metadata")
            if int(payload["Source_End"]) < int(payload["Source_Start"]):
                raise RuntimeError("index_invalid_source_offsets")
            anchors += int(payload.get("source") == "legal")
        if offset is None:
            break
    if anchors != expected_count:
        raise RuntimeError("index_missing_citation_metadata")


def _switch_alias(client, alias: str, target: str) -> None:
    # Qdrant alias update is atomic.  Use the REST client model rather than a
    # delete/recreate collection so the old collection remains rollbackable.
    from qdrant_client.http.models import CreateAlias, CreateAliasOperation, DeleteAlias, DeleteAliasOperation

    aliases = {item.alias_name: item.collection_name for item in client.get_aliases().aliases}
    operations = []
    if alias in aliases and aliases[alias] != target:
        operations.append(DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias)))
    if aliases.get(alias) != target:
        operations.append(CreateAliasOperation(create_alias=CreateAlias(collection_name=target, alias_name=alias)))
    if operations:
        client.update_collection_aliases(change_aliases_operations=operations)


def main() -> None:
    settings, target, digest = _configure()
    from scripts import build_index

    raw = build_index.load_articles()
    build_index.validate_index_contract(raw)
    articles, _ = build_index.normalise_articles(raw)
    build_index.validate_index_contract(articles)
    # Structural chunks are deterministic and give the exact expected point count
    # without making embedding or summary calls.
    chunks, _, _ = build_index.chunk_articles(articles, [""] * len(articles))
    from scripts.canonical_corpus import canonical_chunks

    canonical, chunk_audit = canonical_chunks(chunks)
    if chunk_audit.duplicate_chunk_ids or chunk_audit.invalid_offsets:
        raise RuntimeError("canonical_chunk_audit_failed")
    client = _client(settings)
    try:
        if not _matching_collection(client, target, expected_count=len(canonical), digest=digest, schema=settings.index_schema_version, settings=settings):
            build_index.upsert_to_qdrant(canonical)
        _audit(client, target, expected_count=len(canonical), digest=digest, schema=settings.index_schema_version, settings=settings)
        _switch_alias(client, os.getenv("LAW_COLLECTION_ALIAS", "law_collection"), target)
        print(f"law_index_ready collection={target} corpus_sha256={digest}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
