"""Observability and Tracing API endpoints for performance inspection and audit."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from backend.api.principal import Principal, principal_from_request_state
from backend.config import get_settings
from epr_agent.tracing.trace_context import get_trace_store

router = APIRouter(prefix="/traces", tags=["traces"])
logger = logging.getLogger(__name__)


def _require_trace_access(request: Request) -> Principal:
    """Require an explicitly enabled, operational trace capability.

    Trace payloads contain the user's raw query and execution attributes.  The
    middleware authenticates the request, but route-level scope checks are
    still required because ordinary chat credentials must not become trace
    readers by accident.
    """

    if not get_settings().enable_trace_debug_api:
        raise HTTPException(status_code=404, detail="Trace debug API is disabled")
    principal = principal_from_request_state(request)
    if principal.has_scope("ops") or principal.has_role("quality_admin") or principal.has_scope("quality:read"):
        return principal
    raise HTTPException(status_code=403, detail="Trace debug access requires an operational quality scope")


def _can_read_all(principal: Principal) -> bool:
    """Only operations may inspect traces outside their owner namespace."""

    return principal.has_scope("ops")


async def _list_persisted_traces(principal: Principal, limit: int) -> list[dict[str, Any]] | None:
    """Read the durable redacted trace store, returning ``None`` on dependency failure."""

    try:
        from backend.history.store import list_recent_traces

        return await list_recent_traces(user_id=None if _can_read_all(principal) else principal.id, limit=limit)
    except Exception as exc:  # noqa: BLE001 - debug inspection must not break chat traffic
        logger.warning("Persistent trace listing unavailable: %s", exc)
        return None


async def _get_persisted_trace(principal: Principal, trace_id: str) -> dict[str, Any] | None:
    """Read one durable trace through the owner-scoped or operations path."""

    try:
        if _can_read_all(principal):
            from backend.history.store import get_trace_for_ops

            return await get_trace_for_ops(trace_id)
        from backend.history.store import get_trace

        return await get_trace(principal.id, trace_id)
    except Exception as exc:  # noqa: BLE001 - trace inspection is non-critical
        logger.warning("Persistent trace detail unavailable: %s", exc)
        return None


def _persisted_to_waterfall(trace: dict[str, Any]) -> dict[str, Any]:
    """Adapt the durable redacted run contract to the frontend waterfall shape."""

    metadata_keys = (
        "pipeline_version",
        "route",
        "source",
        "outcome",
        "result_type",
        "termination_reason",
        "cache_status",
        "evidence_count",
    )
    spans: list[dict[str, Any]] = []
    for event in trace.get("events") or []:
        payload = dict(event.get("payload") or {}) if isinstance(event, dict) else {}
        error_code = str(event.get("error_code") or "") if isinstance(event, dict) else ""
        spans.append(
            {
                "span_id": f"{trace.get('trace_id', '')}:{event.get('sequence', len(spans) + 1)}",
                "name": str(event.get("node") or "unknown"),
                "status": str(event.get("status") or "completed"),
                "duration_ms": event.get("duration_ms"),
                "error_message": error_code or None,
                "attributes": payload,
            }
        )
    return {
        "trace_id": trace.get("trace_id", ""),
        "conversation_id": trace.get("conversation_id", ""),
        "user_id": "",
        "query": "",
        "start_time": trace.get("started_at"),
        "total_duration_ms": trace.get("duration_ms", 0),
        "spans_count": len(spans),
        "metadata": {key: trace.get(key) for key in metadata_keys if trace.get(key) is not None},
        "spans": spans,
    }


def _public_persisted_summary(trace: dict[str, Any]) -> dict[str, Any]:
    """Keep recent-trace responses free of durable tool-result payloads."""

    fields = (
        "trace_id",
        "conversation_id",
        "pipeline_version",
        "route",
        "source",
        "duration_ms",
        "evidence_count",
        "cache_status",
        "termination_reason",
        "outcome",
        "result_type",
        "started_at",
        "ended_at",
    )
    return {key: trace.get(key) for key in fields if trace.get(key) is not None}


@router.get("/summary", tags=["traces"])
async def traces_summary(request: Request) -> dict[str, Any]:
    """Return aggregated live performance and telemetry metrics."""
    principal = _require_trace_access(request)
    store = get_trace_store()
    return {
        "status": "success",
        "telemetry": store.get_aggregate_metrics(
            owner_id=None if _can_read_all(principal) else principal.id
        ),
    }


@router.get("/recent", tags=["traces"])
async def recent_traces(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """List recent conversation turn traces."""
    principal = _require_trace_access(request)
    store = get_trace_store()
    memory_items = store.list_recent_traces(
        limit=limit,
        owner_id=None if _can_read_all(principal) else principal.id,
    )
    if memory_items:
        return {"status": "success", "items": memory_items}
    persisted = await _list_persisted_traces(principal, limit)
    if persisted is not None:
        return {"status": "success", "items": [_public_persisted_summary(item) for item in persisted]}
    return {
        "status": "success",
        "items": memory_items,
    }


@router.get("/{trace_id}", tags=["traces"])
async def trace_detail(trace_id: str, request: Request) -> dict[str, Any]:
    """Get full waterfall timeline and span breakdown for a specific trace ID."""
    principal = _require_trace_access(request)
    store = get_trace_store()
    trace = store.get_trace(trace_id)
    if trace is not None:
        if not _can_read_all(principal) and trace.user_id != principal.id:
            trace = None
        else:
            return {"status": "success", "waterfall": trace.to_waterfall()}

    persisted = await _get_persisted_trace(principal, trace_id)
    if persisted is None:
        # Do not reveal whether another owner has a matching trace ID.
        return {
            "status": "not_found",
            "trace_id": trace_id,
            "message": "Trace không tồn tại hoặc đã hết hạn trong bộ nhớ tạm và kho lưu trữ.",
        }
    return {"status": "success", "waterfall": _persisted_to_waterfall(persisted)}
