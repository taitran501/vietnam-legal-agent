"""Owner-scoped trace inspection for local debugging only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.config import get_settings
from backend.history import get_trace, list_traces

router = APIRouter()


def _debug_enabled() -> None:
    if not get_settings().enable_trace_debug_api:
        # Keep the endpoint undiscoverable in production by default.
        raise HTTPException(status_code=404, detail="Not found")


def _owner(request: Request) -> str:
    return getattr(request.state, "api_key_hash", None) or "dev-local"


@router.get("/debug/traces/{trace_id}", tags=["debug"])
async def trace_detail(trace_id: str, request: Request):
    _debug_enabled()
    trace = await get_trace(_owner(request), trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return trace


@router.get("/debug/traces", tags=["debug"])
async def trace_list(request: Request, conversation_id: str, limit: int = 20):
    _debug_enabled()
    return {"items": await list_traces(_owner(request), conversation_id, limit)}
