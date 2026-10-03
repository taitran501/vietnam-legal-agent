"""Health-check endpoint."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.api.schemas import HealthResponse
from vietnam_legal_agent.tools.legal_readiness import audit_legal_readiness

router = APIRouter()
logger = logging.getLogger(__name__)


async def chat_admission_readiness() -> tuple[dict[str, Any], str]:
    """Check only the local dependencies that can prevent a chat turn.

    The full readiness audit hashes the corpus and probes Qdrant/Redis. Those
    checks belong on ``/ready``; repeating them for every chat request adds
    seconds of latency and does not gate legal answers (the workflow handles
    corpus readiness itself).
    """

    from vietnam_legal_agent.config import get_settings

    settings = get_settings()
    schema_capability = {"status": "ready", "reason": "ok"}
    dependencies = {"database": "ok", "openai": "ok"}
    infrastructure_reason = ""
    try:
        from backend.history.store import _store

        schema = await (await _store()).schema_status()
        if schema["status"] != "ready":
            reason = str(schema.get("code") or "database_schema_mismatch")
            dependencies["database"] = "error"
            schema_capability = {"status": "blocked", "reason": reason}
            infrastructure_reason = reason
    except Exception as exc:  # noqa: BLE001 - report local storage failures as admission failures
        logger.info("Chat history database is not ready: %s", exc)
        reason = str(getattr(exc, "code", "database_unavailable"))
        dependencies["database"] = "error"
        schema_capability = {"status": "blocked", "reason": reason}
        infrastructure_reason = reason

    if not settings.openai_api_key:
        dependencies["openai"] = "error"
        infrastructure_reason = infrastructure_reason or "provider_unavailable"

    return {
        "preview": settings.corpus_runtime_mode == "preview",
        "dependencies": dependencies,
        "capabilities": {"history": schema_capability},
    }, infrastructure_reason


async def readiness_payload() -> tuple[dict[str, Any], bool]:
    """Report readiness for the universal legal corpus and chat dependencies."""

    from vietnam_legal_agent.config import get_settings
    from vietnam_legal_agent.infra.session_store import get_redis

    settings = get_settings()
    dependencies = {"database": "ok", "qdrant": "disabled", "redis": "ok", "openai": "ok"}
    retrieval_sources: dict[str, Any] = {
        "qdrant_legal": {"status": "disabled", "reason": "universal_corpus_is_primary"},
        "universal_legal": {"enabled": True, "status": "checking"},
    }
    capabilities: dict[str, dict[str, str]] = {
        name: {"status": "blocked", "reason": "not_checked"}
        for name in ("history", "legal_chat", "feedback", "web_research")
    }
    corpus: dict[str, Any] = {
        "corpus_id": settings.corpus_id,
        "corpus_version": settings.corpus_version,
        "corpus_sha": "",
        "promotion_status": "unknown",
        "index_schema_version": settings.index_schema_version,
        "embedding_profile": settings.embedding_profile,
        "embedding_dimensions": settings.embedding_dimensions,
        "status": "missing",
        "source_snapshot_status": "unknown",
        "legal_readiness_status": "pending",
        "legal_readiness_sha256": "",
        "legally_ready": False,
        "legal_readiness_issues": [],
    }

    try:
        from vietnam_legal_agent.retrieval.universal_retriever import universal_retriever

        source_ready = bool(universal_retriever.is_available)
        retrieval_sources["universal_legal"]["status"] = "ready" if source_ready else "unavailable"
        corpus["corpus_id"] = universal_retriever.corpus_id
        corpus["corpus_version"] = universal_retriever.corpus_version
    except Exception as exc:  # noqa: BLE001 - readiness reports source state without raising
        logger.info("Universal legal corpus is not ready: %s", exc)
        source_ready = False
        retrieval_sources["universal_legal"]["status"] = "unavailable"

    try:
        manifest_bytes = settings.universal_corpus_manifest_path.read_bytes()
        corpus["corpus_sha"] = hashlib.sha256(manifest_bytes).hexdigest()
        corpus["source_snapshot_status"] = "content_locked"
    except OSError:
        corpus["source_snapshot_status"] = "manifest_missing"

    corpus["promotion_status"] = (
        "preview_only" if settings.corpus_runtime_mode == "preview" else "pending_legal_review"
    )
    corpus["status"] = (
        "preview_ready" if source_ready and settings.corpus_runtime_mode == "preview"
        else "ready" if source_ready and settings.corpus_runtime_mode == "production"
        else "missing"
    )
    review = audit_legal_readiness(
        settings.legal_review_manifest_path,
        corpus_sha256=str(corpus["corpus_sha"]),
    )
    corpus["legal_readiness_status"] = review.status.value
    corpus["legal_readiness_sha256"] = review.manifest_sha256
    corpus["legally_ready"] = review.legally_ready
    corpus["legal_readiness_issues"] = list(review.issues)
    retrieval_sources["universal_legal"]["review_status"] = review.status.value

    try:
        from backend.history.store import _store

        store = await _store()
        schema = await store.schema_status()
        if schema["status"] != "ready":
            dependencies["database"] = "error"
            capabilities["history"] = {"status": "blocked", "reason": str(schema["code"])}
            capabilities["feedback"] = {"status": "blocked", "reason": str(schema["code"])}
        else:
            capabilities["history"] = {"status": "ready", "reason": "ok"}
            capabilities["feedback"] = {"status": "ready", "reason": "ok"}
    except Exception as exc:  # noqa: BLE001 - readiness reports dependencies without raising
        logger.info("Database is not ready: %s", exc)
        dependencies["database"] = "error"
        code = getattr(exc, "code", "database_unavailable")
        capabilities["history"] = {"status": "blocked", "reason": str(code)}
        capabilities["feedback"] = {"status": "blocked", "reason": str(code)}

    try:
        await (await get_redis()).ping()
    except Exception:  # noqa: BLE001 - readiness must not expose dependency errors
        dependencies["redis"] = "error"
    if not settings.openai_api_key:
        dependencies["openai"] = "error"

    technical_ready = (
        dependencies["database"] == "ok"
        and dependencies["openai"] == "ok"
        and source_ready
        and bool(corpus["corpus_sha"])
    )
    review_ready = settings.corpus_runtime_mode == "preview" or review.legally_ready
    legal_ready = technical_ready and (not settings.enforce_legal_readiness_gate or review_ready)
    if legal_ready:
        capabilities["legal_chat"] = {
            "status": "ready",
            "reason": "preview_snapshot" if settings.corpus_runtime_mode == "preview" else "ok",
        }
    else:
        reason = (
            "universal_corpus_unavailable" if not source_ready
            else "legal_review_pending" if technical_ready and not review_ready
            else "dependency_unavailable"
        )
        capabilities["legal_chat"] = {"status": "blocked", "reason": reason}

    if technical_ready and settings.tavily_api_key:
        capabilities["web_research"] = {"status": "ready", "reason": "official_sources_only"}
    else:
        capabilities["web_research"] = {
            "status": "blocked",
            "reason": "provider_not_configured" if not settings.tavily_api_key else "dependency_unavailable",
        }

    from vietnam_legal_agent.infra import metrics

    for capability, state in capabilities.items():
        metrics.track_capability_readiness(capability, state["status"], state["reason"])
        if state["status"] != "ready":
            logger.info(
                "capability_readiness capability=%s status=%s reason=%s",
                capability,
                state["status"],
                state["reason"],
            )

    overall_ready = technical_ready and capabilities["history"]["status"] == "ready"
    return {
        "status": "ready" if overall_ready and legal_ready else "degraded" if overall_ready else "not_ready",
        "runtime_mode": settings.corpus_runtime_mode,
        "preview": settings.corpus_runtime_mode == "preview",
        "dependencies": dependencies,
        "retrieval_sources": retrieval_sources,
        "capabilities": capabilities,
        "corpus": corpus,
        "legal_readiness": review.to_dict(),
    }, overall_ready

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
