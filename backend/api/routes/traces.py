"""Observability and Tracing API endpoints for performance inspection and audit."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from backend.api.principal import principal_from_request_state
from epr_agent.tracing.trace_context import get_trace_store

router = APIRouter(prefix="/traces", tags=["traces"])


def _owner(request: Request) -> str:
    return principal_from_request_state(request).id


@router.get("/summary", tags=["traces"])
async def traces_summary() -> dict[str, Any]:
    """Return aggregated live performance and telemetry metrics."""
    store = get_trace_store()
    return {
        "status": "success",
        "telemetry": store.get_aggregate_metrics(),
    }


@router.get("/recent", tags=["traces"])
async def recent_traces(limit: int = 20) -> dict[str, Any]:
    """List recent conversation turn traces."""
    store = get_trace_store()
    return {
        "status": "success",
        "items": store.list_recent_traces(limit=limit),
    }


@router.get("/{trace_id}", tags=["traces"])
async def trace_detail(trace_id: str) -> dict[str, Any]:
    """Get full waterfall timeline and span breakdown for a specific trace ID."""
    store = get_trace_store()
    trace = store.get_trace(trace_id)
    if trace is None:
        # Check fallback placeholder
        return {
            "status": "not_found",
            "trace_id": trace_id,
            "message": "Trace không tồn tại hoặc đã hết hạn trong memory buffer.",
        }
    return {
        "status": "success",
        "waterfall": trace.to_waterfall(),
    }
