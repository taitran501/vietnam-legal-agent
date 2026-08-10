"""Build or reuse a versioned EPR law collection, then atomically switch its alias.

This is intentionally a one-shot Compose service.  It never overwrites an
existing collection, and a matching collection exits before OpenAI embedding or
summarisation is called.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _law_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configure() -> tuple[Any, str, str]:
    from backend.config import get_settings

    base = get_settings()
    digest = _law_hash(Path(base.law_data_path))
    schema = base.index_schema_version.replace("-", "_")
    target = f"law_{base.corpus_id}_{digest[:12]}_{schema}"
    os.environ["LAW_COLLECTION"] = target
    # Corpus version is an explicit deployment contract used by the cache; the
    # immutable SHA and versioned collection carry the concrete source revision.
    os.environ["CORPUS_SHA256"] = digest
    os.environ.setdefault("CHUNKING_STRATEGY", "legal_structure_v1")
    get_settings.cache_clear()
    return get_settings(), target, digest


def _client(settings):
    from qdrant_client import QdrantClient

    if settings.use_qdrant_cloud:
        return QdrantClient(url=settings.qdrant_cloud_url, api_key=settings.qdrant_api_key)
    if settings.qdrant_url:
        return QdrantClient(url=settings.qdrant_url)
    return QdrantClient(path=settings.qdrant_local_path)


def _matching_collection(client, collection: str, *, expected_count: int, digest: str, schema: str) -> bool:
    try:
        info = client.get_collection(collection)
        if int(info.points_count or 0) != expected_count:
            return False
        points, _ = client.scroll(collection, limit=1, with_payload=True, with_vectors=False)
        payload = dict(points[0].payload or {}) if points else {}
        return payload.get("Corpus_SHA256") == digest and payload.get("Index_Schema_Version") == schema
    except Exception:  # noqa: BLE001 - a missing/partial collection is an intentional rebuild signal
        return False


def _audit(client, collection: str, *, expected_count: int, digest: str, schema: str) -> None:
    info = client.get_collection(collection)
    if int(info.points_count or 0) != expected_count or expected_count == 0:
        raise RuntimeError("index_point_count_mismatch")
    offset = None
    seen: set[tuple[str, int]] = set()
    anchors = 0
    while True:
        points, offset = client.scroll(collection, offset=offset, limit=256, with_payload=True, with_vectors=False)
        for point in points:
            payload = dict(point.payload or {})
            if payload.get("Corpus_SHA256") != digest or payload.get("Index_Schema_Version") != schema:
                raise RuntimeError("index_payload_version_mismatch")
            key = (str(payload.get("Parent_Id") or point.id), int(payload.get("Chunk_Index") or 0))
            if key in seen:
                raise RuntimeError("index_duplicate_chunk")
            seen.add(key)
            anchors += int(bool(payload.get("legal_anchor") and payload.get("source") == "legal"))
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
    client = _client(settings)
    try:
        if not _matching_collection(client, target, expected_count=len(chunks), digest=digest, schema=settings.index_schema_version):
            summaries = build_index.summarise_articles(articles)
            chunks, chunk_summaries, _ = build_index.chunk_articles(articles, summaries)
            build_index.upsert_to_qdrant(chunks, chunk_summaries)
        _audit(client, target, expected_count=len(chunks), digest=digest, schema=settings.index_schema_version)
        _switch_alias(client, os.getenv("LAW_COLLECTION_ALIAS", "law_collection"), target)
        print(f"law_index_ready collection={target} corpus_sha256={digest}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
