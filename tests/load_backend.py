"""Deterministic two-worker SSE target for the pilot admission load contract."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os

from fastapi import FastAPI, Request
from sse_starlette.sse import EventSourceResponse

from epr_agent.infra.admission import AdmissionUnavailable, RedisAdmissionController

app = FastAPI(title="Pilot admission load target")
admission = RedisAdmissionController(key_prefix="pilot-load")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _stream_with_lease(
    request: Request,
    *,
    scope: str,
    limit: int,
    hold_seconds: float,
) -> EventSourceResponse:
    try:
        lease = await admission.acquire(
            scope,
            limit=limit,
            wait_seconds=2,
            lease_ttl_seconds=300,
        )
    except AdmissionUnavailable:
        lease = None
        error_code = "capacity_unavailable"
    else:
        error_code = "capacity_exceeded"

    async def events():
        if lease is None:
            yield {
                "data": json.dumps(
                    {
                        "type": "error",
                        "code": error_code,
                        "retryable": True,
                        "retry_after_seconds": 5,
                    }
                )
            }
            return
        heartbeat = asyncio.create_task(admission.heartbeat(lease, 30))
        try:
            yield {"data": json.dumps({"type": "status", "stage": "admitted"})}
            await asyncio.sleep(hold_seconds)
            if not await request.is_disconnected():
                yield {"data": json.dumps({"type": "response_complete", "text": "ok"})}
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError, AdmissionUnavailable):
                await heartbeat
            with contextlib.suppress(AdmissionUnavailable):
                await admission.release(lease)

    return EventSourceResponse(events(), ping=15)


@app.post("/load")
async def load(request: Request) -> EventSourceResponse:
    return await _stream_with_lease(
        request,
        scope="agent-turns",
        limit=50,
        hold_seconds=float(os.getenv("PILOT_LOAD_HOLD_SECONDS", "4")),
    )


@app.post("/disconnect")
async def disconnect(request: Request, hold_seconds: float = 30) -> EventSourceResponse:
    return await _stream_with_lease(
        request,
        scope="disconnect-turn",
        limit=1,
        hold_seconds=hold_seconds,
    )
