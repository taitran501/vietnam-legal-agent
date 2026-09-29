"""Health-check endpoint."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.api.schemas import HealthResponse
from epr_agent.tools.legal_readiness import LegalReadinessAudit, ReadinessStatus, audit_legal_readiness

router = APIRouter()
logger = logging.getLogger(__name__)


async def chat_admission_readiness() -> tuple[dict[str, Any], str]:
    """Check only the local dependencies that can prevent a chat turn.

    The full readiness audit hashes the corpus and probes Qdrant/Redis. Those
    checks belong on ``/ready``; repeating them for every chat request adds
    seconds of latency and does not gate legal answers (the workflow handles
    corpus readiness itself).
    """

    from epr_agent.config import get_settings

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
    """Return capability-level readiness without exposing connection details."""

    from epr_agent.config import get_settings
    from epr_agent.infra.session_store import get_redis

    settings = get_settings()
    dependencies = {"database": "ok", "qdrant": "ok", "redis": "ok", "openai": "ok"}
    universal_retrieval_enabled = bool(getattr(settings, "enable_universal_retrieval", True))
    retrieval_sources: dict[str, Any] = {
        "qdrant_legal": {
            "status": "checking",
            "collection": settings.law_collection,
            "points_count": 0,
            "index_matches": False,
        },
        "universal_legal": {
            "enabled": universal_retrieval_enabled,
            "status": "checking" if universal_retrieval_enabled else "disabled",
        },
    }
    if universal_retrieval_enabled:
        try:
            from epr_agent.retrieval.universal_retriever import universal_retriever

            retrieval_sources["universal_legal"]["status"] = (
                "ready" if universal_retriever.is_available else "unavailable"
            )
        except Exception as exc:  # noqa: BLE001 - source health must not fail liveness
            logger.info("Universal legal corpus is not ready: %s", exc)
            retrieval_sources["universal_legal"]["status"] = "unavailable"
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
        "source_snapshot_status": "unknown",
        "legal_readiness_status": "unknown",
        "legal_readiness_sha256": "",
        "legally_ready": False,
        "legal_readiness_issues": [],
    }
    audit: dict[str, Any] = {}
    legal_audit = LegalReadinessAudit(
        ReadinessStatus.INVALID,
        False,
        "invalid",
        "",
        "",
        "",
        "",
        ("legal_readiness_not_checked",),
    )
    enforce_legal_readiness = bool(getattr(settings, "enforce_legal_readiness_gate", False))
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
        corpus["source_snapshot_status"] = str(audit.get("source_snapshot_status") or "technical")

        if "technical_ready" in audit:
            technical_corpus_ready = bool(audit["technical_ready"])
        else:  # Compatibility for injected readiness doubles.
            technical_corpus_ready = not any(
                [*audit["source_errors"], *audit["amendment_errors"], *audit["rule_pack_errors"]]
            )

        expected_sha = corpus_sha256(
            law_path=settings.law_data_path,
            manifest_path=settings.corpus_manifest_path,
            appendix_path=settings.appendix_xxii_data_path,
        )
        corpus["corpus_sha"] = expected_sha
        if settings.appendix_xxii_data_path.exists():
            corpus["appendix_sha256"] = hashlib.sha256(settings.appendix_xxii_data_path.read_bytes()).hexdigest()
        legal_readiness_manifest_path = getattr(settings, "legal_readiness_manifest_path", "")
        if enforce_legal_readiness or legal_readiness_manifest_path:
            legal_audit = audit_legal_readiness(
                legal_readiness_manifest_path,
                corpus_sha256=expected_sha,
                amendment_map_sha256=str(audit.get("amendment_map_sha256") or ""),
                rule_pack_sha256=str(audit.get("rule_pack_sha256") or ""),
            )
        else:
            # Older injected readiness doubles do not expose a manifest path.
            # Production Settings always carries the path, so preview mode
            # still reports the real review state even when it does not enforce it.
            legal_audit = LegalReadinessAudit(
                ReadinessStatus.READY,
                True,
                "ready",
                "not-enforced",
                expected_sha,
                str(audit.get("amendment_map_sha256") or ""),
                str(audit.get("rule_pack_sha256") or ""),
            )
        corpus["legal_readiness_status"] = legal_audit.status.value
        corpus["legal_readiness_sha256"] = legal_audit.manifest_sha256
        corpus["legally_ready"] = legal_audit.legally_ready
        corpus["legal_readiness_issues"] = list(legal_audit.issues)
        from epr_agent.retrieval.retrieval import _get_qdrant_client

        client = _get_qdrant_client()
        info = client.get_collection(settings.law_collection)
        corpus["points_count"] = int(info.points_count or 0)
        retrieval_sources["qdrant_legal"]["points_count"] = corpus["points_count"]
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
        retrieval_sources["qdrant_legal"]["index_matches"] = index_matches
        retrieval_sources["qdrant_legal"]["status"] = "ready" if index_matches else "version_mismatch"
        corpus_ready = audit["ready_for_promotion"] if settings.corpus_runtime_mode == "production" else technical_corpus_ready
        if index_matches and corpus_ready:
            corpus["status"] = "ready" if settings.corpus_runtime_mode == "production" else "preview_ready"
        else:
            corpus["status"] = "promotion_blocked" if not corpus_ready else "version_mismatch"
    except Exception as exc:  # noqa: BLE001 - readiness must be safe when a collection is absent
        logger.info("Legal corpus is not ready: %s", exc)
        dependencies["qdrant"] = "preview" if settings.corpus_runtime_mode == "preview" else "error"
        retrieval_sources["qdrant_legal"]["status"] = (
            "preview_unavailable" if settings.corpus_runtime_mode == "preview" else "unavailable"
        )
        if enforce_legal_readiness and legal_audit.status is ReadinessStatus.INVALID:
            corpus["legal_readiness_status"] = legal_audit.status.value
            corpus["legal_readiness_sha256"] = legal_audit.manifest_sha256
            corpus["legal_readiness_issues"] = list(legal_audit.issues)
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

    corpus_ready = technical_corpus_ready
    universal_source_ready = (
        not universal_retrieval_enabled
        or retrieval_sources["universal_legal"]["status"] == "ready"
    )
    technical_ready = (
        dependencies["database"] == "ok"
        and (dependencies["qdrant"] == "ok" or (settings.corpus_runtime_mode == "preview" and dependencies["qdrant"] in {"ok", "preview"}))
        and dependencies["openai"] == "ok"
        # Preview relaxes legal approval, not index identity. Serving against a
        # stale/unversioned collection produces plausible but unsupported safe
        # stops (or, worse, answers from the wrong corpus).
        and index_matches
        and corpus_ready
        # An explicitly enabled universal supplement is part of the selected
        # runtime corpus. Do not advertise legal chat as ready if the SQLite
        # artifact was omitted from the image or is otherwise unavailable.
        and universal_source_ready
    )
    legal_ready = technical_ready and (legal_audit.status is ReadinessStatus.READY or not enforce_legal_readiness)
    if legal_ready:
        reason = "preview_snapshot" if settings.corpus_runtime_mode == "preview" else "ok"
        capabilities["legal_chat"] = {"status": "ready", "reason": reason}
        capabilities["case_workflow"] = {"status": "ready", "reason": reason}
    else:
        reason = (
            "database_schema_mismatch" if capabilities["history"]["reason"] == "database_schema_mismatch"
            else "legal_readiness_invalid" if legal_audit.status is ReadinessStatus.INVALID and technical_ready
            else "legal_review_pending" if legal_audit.status is ReadinessStatus.PENDING and technical_ready
            else "corpus_promotion_blocked" if not corpus_ready
            else "corpus_index_mismatch" if not index_matches
            else "universal_corpus_unavailable" if universal_retrieval_enabled and not universal_source_ready
            else "dependency_unavailable"
        )
        capabilities["legal_chat"] = {"status": "blocked", "reason": reason}
        capabilities["case_workflow"] = {"status": "blocked", "reason": reason}
    if technical_ready and settings.tavily_api_key:
        capabilities["web_research"] = {"status": "ready", "reason": "official_sources_only"}
    else:
        capabilities["web_research"] = {
            "status": "blocked",
            "reason": "provider_not_configured" if not settings.tavily_api_key else "dependency_unavailable",
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

    # Legal review is a capability gate, not a process-liveness gate.  Keep
    # /ready available with a degraded payload while the technical stack can
    # serve chitchat/history and legal routes safe-stop.
    overall_ready = technical_ready and capabilities["history"]["status"] == "ready"
    return {
        "status": "ready" if overall_ready and legal_ready else "degraded" if overall_ready else "not_ready",
        "runtime_mode": settings.corpus_runtime_mode,
        "preview": settings.corpus_runtime_mode == "preview",
        "dependencies": dependencies,
        "retrieval_sources": retrieval_sources,
        "capabilities": capabilities,
        "corpus": corpus,
        "legal_readiness": legal_audit.to_dict(),
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
