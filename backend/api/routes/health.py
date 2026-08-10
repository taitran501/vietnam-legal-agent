"""Health-check endpoint."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.api.schemas import HealthResponse

router = APIRouter()
logger = logging.getLogger(__name__)


async def readiness_payload() -> tuple[dict[str, Any], bool]:
    """Return corpus-aware readiness without exposing connection details."""

    from backend.config import get_settings
    from backend.memory.session_store import get_redis

    settings = get_settings()
    dependencies = {"database": "ok", "qdrant": "ok", "redis": "ok", "openai": "ok"}
    corpus: dict[str, Any] = {
        "corpus_id": settings.corpus_id,
        "corpus_version": settings.corpus_version,
        "corpus_sha": "",
        "index_schema_version": settings.index_schema_version,
        "embedding_profile": settings.embedding_profile,
        "embedding_dimensions": settings.embedding_dimensions,
        "collection": settings.law_collection,
        "points_count": 0,
        "status": "missing",
    }
    try:
        from scripts.canonical_corpus import corpus_sha256

        expected_sha = corpus_sha256(
            law_path=settings.law_data_path,
            manifest_path=settings.corpus_manifest_path,
        )
        corpus["corpus_sha"] = expected_sha
        from backend.core.retrieval import _get_qdrant_client

        client = _get_qdrant_client()
        info = client.get_collection(settings.law_collection)
        corpus["points_count"] = int(info.points_count or 0)
        points, _ = client.scroll(settings.law_collection, limit=1, with_payload=True, with_vectors=False)
        payload = dict(points[0].payload or {}) if points else {}
        if (
            corpus["points_count"] > 0
            and payload.get("Corpus_ID") == settings.corpus_id
            and payload.get("Corpus_Version") == settings.corpus_version
            and payload.get("Corpus_SHA256") == expected_sha
            and payload.get("Index_Schema_Version") == settings.index_schema_version
            and payload.get("Embedding_Profile") == settings.embedding_profile
            and int(payload.get("Embedding_Dimensions") or 0) == settings.embedding_dimensions
        ):
            corpus["status"] = "ready"
        else:
            corpus["status"] = "version_mismatch"
    except Exception as exc:  # noqa: BLE001 - readiness must be safe when a collection is absent
        logger.info("Legal corpus is not ready: %s", exc)
        dependencies["qdrant"] = "error"
    try:
        from sqlalchemy import text

        from backend.history.store import _store

        store = await _store()
        async with store.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - readiness reports dependencies without raising
        logger.info("Database is not ready: %s", exc)
        dependencies["database"] = "error"
    try:
        await (await get_redis()).ping()
    except Exception:  # noqa: BLE001 - readiness must not expose dependency errors
        dependencies["redis"] = "error"
    if not settings.openai_api_key:
        dependencies["openai"] = "error"

    ready = corpus["status"] == "ready" and all(value == "ok" for value in dependencies.values())
    return {
        "status": "ready" if ready else "not_ready",
        "dependencies": dependencies,
        "corpus": corpus,
    }, ready


@router.get("/health", response_model=HealthResponse, tags=["ops"])
async def health() -> HealthResponse:
    """Process liveness only; dependency readiness belongs to ``/ready``."""

    return HealthResponse(
        status="ok",
        qdrant="not_checked",
        redis="not_checked",
        openai="not_checked",
    )


@router.get("/ready", tags=["ops"])
async def ready() -> JSONResponse:
    payload, is_ready = await readiness_payload()
    return JSONResponse(status_code=200 if is_ready else 503, content=payload)
