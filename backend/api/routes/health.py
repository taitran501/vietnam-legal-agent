"""Health-check endpoint."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.api.schemas import HealthResponse

router = APIRouter()
logger = logging.getLogger(__name__)


async def readiness_payload() -> tuple[dict[str, Any], bool]:
    """Return capability-level readiness without exposing connection details."""

    from epr_agent.config import get_settings
    from epr_agent.infra.session_store import get_redis

    settings = get_settings()
    dependencies = {"database": "ok", "qdrant": "ok", "redis": "ok", "openai": "ok"}
    capabilities: dict[str, dict[str, str]] = {
        name: {"status": "blocked", "reason": "not_checked"}
        for name in ("history", "legal_chat", "case_workflow", "feedback", "web_research")
    }
    corpus: dict[str, Any] = {
        "corpus_id": settings.corpus_id,
        "corpus_version": settings.corpus_version,
        "corpus_sha": "",
        "appendix_sha256": "",
        "amendment_map_sha256": "",
        "rule_pack_sha256": "",
        "source_completeness": "unknown",
        "amendment_chain_status": "unknown",
        "promotion_status": "unknown",
        "index_schema_version": settings.index_schema_version,
        "embedding_profile": settings.embedding_profile,
        "embedding_dimensions": settings.embedding_dimensions,
        "collection": settings.law_collection,
        "points_count": 0,
        "status": "missing",
        "legal_review_status": "pending",
    }
    audit: dict[str, Any] = {}
    index_matches = False
    technical_corpus_ready = False
    try:
        from scripts.canonical_corpus import corpus_readiness_audit, corpus_sha256

        audit = corpus_readiness_audit(
            manifest_path=settings.corpus_manifest_path,
            rule_pack_path=settings.rule_pack_path,
            amendment_map_path=settings.amendment_map_path,
            appendix_path=settings.appendix_xxii_data_path,
        )
        corpus["amendment_map_sha256"] = audit["amendment_map_sha256"]
        corpus["rule_pack_sha256"] = audit["rule_pack_sha256"]
        corpus["source_completeness"] = "complete" if not audit["source_errors"] else "incomplete"
        corpus["amendment_chain_status"] = "ready" if not audit["amendment_errors"] else "blocked"
        corpus["promotion_status"] = "ready" if audit["ready_for_promotion"] else "blocked"
        corpus["legal_review_status"] = str(audit.get("manifest_legal_review_status") or "pending")

        if "technical_ready" in audit:
            technical_corpus_ready = bool(audit["technical_ready"])
        else:  # Compatibility for injected readiness doubles.
            legal_review_markers = ("legal_review_pending", "legal_review_missing", "resolution_pending")
            technical_corpus_ready = not any(
                not any(marker in error for marker in legal_review_markers)
                for error in [*audit["source_errors"], *audit["amendment_errors"], *audit["rule_pack_errors"]]
            )

        expected_sha = corpus_sha256(
            law_path=settings.law_data_path,
            manifest_path=settings.corpus_manifest_path,
            appendix_path=settings.appendix_xxii_data_path,
        )
        corpus["corpus_sha"] = expected_sha
        if settings.appendix_xxii_data_path.exists():
            corpus["appendix_sha256"] = hashlib.sha256(settings.appendix_xxii_data_path.read_bytes()).hexdigest()
        from epr_agent.retrieval.retrieval import _get_qdrant_client

        client = _get_qdrant_client()
        info = client.get_collection(settings.law_collection)
        corpus["points_count"] = int(info.points_count or 0)
        points, _ = client.scroll(settings.law_collection, limit=1, with_payload=True, with_vectors=False)
        payload = dict(points[0].payload or {}) if points else {}
        index_matches = (
            corpus["points_count"] > 0
            and payload.get("Corpus_ID") == settings.corpus_id
            and payload.get("Corpus_Version") == settings.corpus_version
            and payload.get("Corpus_SHA256") == expected_sha
            and payload.get("Index_Schema_Version") == settings.index_schema_version
            and payload.get("Embedding_Profile") == settings.embedding_profile
            and int(payload.get("Embedding_Dimensions") or 0) == settings.embedding_dimensions
        )
        legal_gate_ready = audit["ready_for_promotion"] if settings.corpus_runtime_mode == "production" else technical_corpus_ready
        if index_matches and legal_gate_ready:
            corpus["status"] = "ready" if settings.corpus_runtime_mode == "production" else "preview_ready"
        else:
            corpus["status"] = "promotion_blocked" if not legal_gate_ready else "version_mismatch"
    except Exception as exc:  # noqa: BLE001 - readiness must be safe when a collection is absent
        logger.info("Legal corpus is not ready: %s", exc)
        dependencies["qdrant"] = "preview" if settings.corpus_runtime_mode == "preview" else "error"
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

    legal_gate_ready = bool(audit.get("ready_for_promotion")) if settings.corpus_runtime_mode == "production" else technical_corpus_ready
    legal_ready = (
        dependencies["database"] == "ok"
        and (dependencies["qdrant"] == "ok" or (settings.corpus_runtime_mode == "preview" and dependencies["qdrant"] in {"ok", "preview"}))
        and dependencies["openai"] == "ok"
        and (index_matches or settings.corpus_runtime_mode == "preview")
        and legal_gate_ready
    )
    if legal_ready:
        reason = "preview_unapproved_corpus" if settings.corpus_runtime_mode == "preview" else "ok"
        capabilities["legal_chat"] = {"status": "ready", "reason": reason}
        capabilities["case_workflow"] = {"status": "ready", "reason": reason}
    else:
        reason = (
            "database_schema_mismatch" if capabilities["history"]["reason"] == "database_schema_mismatch"
            else "corpus_promotion_blocked" if not legal_gate_ready
            else "corpus_index_mismatch" if not index_matches
            else "dependency_unavailable"
        )
        capabilities["legal_chat"] = {"status": "blocked", "reason": reason}
        capabilities["case_workflow"] = {"status": "blocked", "reason": reason}
    if legal_ready and settings.tavily_api_key:
        capabilities["web_research"] = {"status": "ready", "reason": "official_sources_only"}
    else:
        capabilities["web_research"] = {
            "status": "blocked",
            "reason": "provider_not_configured" if not settings.tavily_api_key else capabilities["legal_chat"]["reason"],
        }

    from epr_agent.infra import metrics

    for capability, state in capabilities.items():
        metrics.track_capability_readiness(capability, state["status"], state["reason"])
        if state["status"] != "ready":
            logger.info(
                "capability_readiness capability=%s status=%s reason=%s",
                capability,
                state["status"],
                state["reason"],
            )

    ready = capabilities["history"]["status"] == "ready" and capabilities["legal_chat"]["status"] == "ready"
    return {
        "status": "ready" if ready else "not_ready",
        "runtime_mode": settings.corpus_runtime_mode,
        "preview": settings.corpus_runtime_mode == "preview",
        "dependencies": dependencies,
        "capabilities": capabilities,
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
