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
    dependencies = {"qdrant": "ok", "redis": "ok", "openai": "ok"}
    corpus: dict[str, Any] = {
        "corpus_id": settings.corpus_id,
        "corpus_version": settings.corpus_version,
        "index_schema_version": settings.index_schema_version,
        "collection": settings.law_collection,
        "points_count": 0,
        "status": "missing",
    }
    try:
        from backend.core.retrieval import _get_qdrant_client

        client = _get_qdrant_client()
        info = client.get_collection(settings.law_collection)
        corpus["points_count"] = int(info.points_count or 0)
        points, _ = client.scroll(settings.law_collection, limit=1, with_payload=True, with_vectors=False)
        payload = dict(points[0].payload or {}) if points else {}
        if (
            corpus["points_count"] > 0
            and payload.get("Corpus_Version") == settings.corpus_version
            and payload.get("Index_Schema_Version") == settings.index_schema_version
        ):
            corpus["status"] = "ready"
        else:
            corpus["status"] = "version_mismatch"
    except Exception as exc:  # noqa: BLE001 - readiness must be safe when a collection is absent
        logger.info("Legal corpus is not ready: %s", exc)
        dependencies["qdrant"] = "error"
    try:
        await (await get_redis()).ping()
    except Exception:
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
    """Ping Qdrant, Redis, and OpenAI; return their status.

    SECURITY: Only returns 'ok' or 'error' — never exposes infrastructure details
    like connection strings, hostnames, or stack traces to clients.
    Detailed errors are logged internally for debugging.
    """
    from backend.config import get_settings
    from backend.memory.session_store import get_redis
    from backend.core.retrieval import _get_qdrant_client

    settings = get_settings()

    # Qdrant
    qdrant_status = "ok"
    try:
        client = _get_qdrant_client()
        client.get_collections()
    except Exception as exc:
        logger.error("Qdrant health check failed: %s", exc)
        qdrant_status = "error"  # Generic message only — no infrastructure details

    # Redis
    redis_status = "ok"
    try:
        r = await get_redis()
        await r.ping()
    except Exception as exc:
        logger.error("Redis health check failed: %s", exc)
        redis_status = "error"  # Generic message only
    
    # OpenAI API - lightweight check (list models)
    openai_status = "ok"
    try:
        from backend.core.llm_instances import get_llm_smart
        llm = get_llm_smart()
        # Just verify we can create an instance - don't actually call API on startup
        # A real check would be: await llm.aget_num_tokens("test") but that costs tokens
        # Instead, we'll check if the API key is configured
        import os
        if not os.getenv("OPENAI_API_KEY"):
            openai_status = "error"
            logger.warning("OpenAI API key not configured")
    except Exception as exc:
        logger.error("OpenAI health check failed: %s", exc)
        openai_status = "error"  # Generic message only

    overall = "ok" if all(s == "ok" for s in [qdrant_status, redis_status, openai_status]) else "degraded"
    return HealthResponse(
        status=overall,
        qdrant=qdrant_status,
        redis=redis_status,
        openai=openai_status,
    )


@router.get("/ready", tags=["ops"])
async def ready() -> JSONResponse:
    payload, is_ready = await readiness_payload()
    return JSONResponse(status_code=200 if is_ready else 503, content=payload)
