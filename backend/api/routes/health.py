"""Health-check endpoint."""

from __future__ import annotations

import logging
from fastapi import APIRouter

from backend.api.schemas import HealthResponse

router = APIRouter()
logger = logging.getLogger(__name__)


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
