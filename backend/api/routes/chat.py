"""
SSE streaming chat endpoint.

POST /chat
  Body : ChatRequest  (JSON)
  Returns: text/event-stream

Each SSE event is a JSON object matching the pipeline yield format:
  {"type": "status"|"response_chunk"|"response_complete", ...}
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request

try:
    from sse_starlette.sse import EventSourceResponse
except ImportError:  # pragma: no cover - production installs sse-starlette
    from starlette.responses import StreamingResponse

    class EventSourceResponse(StreamingResponse):
        """Small test/runtime fallback when the optional SSE package is absent."""

        def __init__(self, content, *, status_code=200, headers=None, ping=None):
            async def frames():
                async for item in content:
                    payload = item.get("data", item) if isinstance(item, dict) else item
                    yield f"data: {payload}\n\n"

            super().__init__(frames(), status_code=status_code, headers=headers, media_type="text/event-stream")

from backend.api import metrics
from backend.api.principal import principal_from_request_state
from backend.api.routes.health import readiness_payload
from backend.api.schemas import ChatRequest
from backend.history import cancel_turn as cancel_turn_persistent
from epr_agent.api.routes import stream_chat_events as agentic_stream_chat

logger = logging.getLogger(__name__)
router = APIRouter()

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@router.post("/chat", tags=["chat"])
async def chat(request: Request, body: ChatRequest):
    """Stream chatbot responses as Server-Sent Events."""
    # Canonical identifier moving forward: conversation_id.
    # Backward compatibility: accept legacy session_id if conversation_id is missing.
    conversation_id = body.conversation_id or body.session_id or str(uuid.uuid4())
    turn_id = body.turn_id or str(uuid.uuid4())

    # User scope for durable history: API key hash set by auth middleware.
    # Fallback keeps local development functional when auth is disabled.
    principal = principal_from_request_state(request)
    if principal.type == "service" and not principal.has_scope("chat"):
        raise HTTPException(status_code=403, detail="Service token lacks the chat scope")
    user_id = principal.id
    trace_id = str(uuid.uuid4())
    runtime = getattr(request.app.state, "workflow_runtime", None)
    typed_case_patch = {
        key: value.value
        for key, value in body.fact_updates.items()
        if value.value.strip()
    }
    typed_fact_updates = {
        key: value.model_dump(mode="json")
        for key, value in body.fact_updates.items()
    }
    # Keep the legacy string patch for one compatibility release, but pass
    # typed updates separately so confirmation status survives into V4 state.
    case_patch = {**body.case_patch, **typed_case_patch}

    readiness, _ = await readiness_payload()
    legal_capability = readiness.get("capabilities", {}).get("legal_chat", {})
    if legal_capability.get("status") != "ready":
        async def _not_ready():
            reason = str(legal_capability.get("reason") or "corpus_not_ready")
            retryable = reason not in {"database_schema_mismatch", "corpus_promotion_blocked"}
            metrics.track_sse_error(reason, retryable)
            logger.info("sse_error code=%s retryable=%s trace_id=%s", reason, retryable, trace_id)
            yield {
                "data": json.dumps(
                    {
                        "type": "error",
                        "code": reason,
                        "message": (
                            "Cơ sở dữ liệu lịch sử cần được nâng cấp trước khi tiếp tục."
                            if reason == "database_schema_mismatch"
                            else "Dữ liệu pháp luật đang chưa sẵn sàng. Vui lòng thử lại sau khi index hoàn tất."
                        ),
                        "retryable": retryable,
                        "retry_after_seconds": 30 if retryable else None,
                        "trace_id": trace_id,
                        "pipeline_version": "pipeline-v4",
                        "readiness": readiness,
                    },
                    ensure_ascii=False,
                )
            }
        return EventSourceResponse(_not_ready(), status_code=503, headers=_SSE_HEADERS)
    
    # Log session creation for audit trail
    logger.info(
        "Chat request: user_id=%s, conversation_id=%s, query_length=%d",
        user_id,
        conversation_id,
        len(body.query),
    )

    replay_descriptor = dict(body.replay_metadata)
    replay_descriptor.update({
        "query_mode": body.mode,
        "intent": body.intent_hint,
        "operation": body.operation,
        "interaction_source": body.interaction_source,
        "case_patch": case_patch,
        "fact_updates": typed_fact_updates,
    })

    async def _event_generator():
        replay_result_recorded = False
        try:
            async for event in agentic_stream_chat(
                query=body.query,
                user_id=user_id,
                conversation_id=conversation_id,
                legacy_session_id=body.session_id,
                mode=body.mode,
                operation=body.operation,
                intent_hint=body.intent_hint,
                interaction_source=body.interaction_source,
                case_patch=case_patch,
                fact_updates=typed_fact_updates,
                replay_metadata=replay_descriptor,
                turn_id=turn_id,
                target_assistant_message_id=body.target_assistant_message_id,
                runtime=runtime,
            ):
                # Readiness is the authoritative runtime gate for this request.
                event["preview"] = bool(readiness.get("preview"))
                event_type = str(event.get("type") or "")
                if event_type == "error":
                    code = str(event.get("code") or "pipeline_error")
                    retryable = bool(event.get("retryable"))
                    metrics.track_sse_error(code, retryable)
                    logger.info("sse_error code=%s retryable=%s trace_id=%s", code, retryable, trace_id)
                    if body.operation in {"retry", "regenerate"} and not replay_result_recorded:
                        metrics.track_replay_operation(body.operation, "failed")
                        replay_result_recorded = True
                elif event_type == "response_stopped":
                    metrics.track_turn_termination("stopped", "user_cancelled")
                    if body.operation in {"retry", "regenerate"} and not replay_result_recorded:
                        metrics.track_replay_operation(body.operation, "stopped")
                        replay_result_recorded = True
                elif event_type == "response_complete":
                    metrics.track_turn_termination(
                        str(event.get("turn_status") or "complete"),
                        str(event.get("safe_stop_reason") or event.get("outcome") or "none"),
                    )
                    if body.operation in {"retry", "regenerate"} and not replay_result_recorded:
                        metrics.track_replay_operation(body.operation, "complete")
                        replay_result_recorded = True
                # CRITICAL: Check if client disconnected
                if await request.is_disconnected():
                    logger.info(
                        "Client disconnected, stopping pipeline for conversation=%s",
                        conversation_id,
                    )
                    return  # Stop immediately, don't waste LLM calls
                yield {"data": json.dumps(event, ensure_ascii=False)}
        except asyncio.CancelledError:
            # Client disconnected mid-stream
            logger.info("Stream cancelled for conversation=%s", conversation_id)
            return
        except Exception:
            logger.exception("Pipeline error")
            metrics.track_sse_error("pipeline_error", True)
            if body.operation in {"retry", "regenerate"} and not replay_result_recorded:
                metrics.track_replay_operation(body.operation, "failed")
            yield {
                "data": json.dumps({
                    "type": "error",
                    "code": "pipeline_error",
                    "message": "Không thể hoàn tất yêu cầu. Bạn có thể thử lại.",
                    "retryable": True,
                    "retry_after_seconds": 2,
                    "trace_id": trace_id,
                    "pipeline_version": "pipeline-v4",
                })
            }

    return EventSourceResponse(
        _event_generator(),
        headers={
            **_SSE_HEADERS,
            "X-Conversation-ID": conversation_id,
            "X-Turn-ID": turn_id,
            # Backward compatibility for current clients.
            "X-Session-ID": conversation_id,
        },
        ping=15,
    )


@router.put("/conversations/{conversation_id}/turns/{turn_id}/cancel", tags=["chat"])
async def cancel_turn(request: Request, conversation_id: str, turn_id: str):
    """Idempotently stop an owned pending/streaming turn and retain partial text."""

    principal = principal_from_request_state(request)
    if principal.type == "service" and not principal.has_scope("chat"):
        raise HTTPException(status_code=403, detail="Service token lacks the chat scope")
    result = await cancel_turn_persistent(principal.id, conversation_id, turn_id)
    if result is None:
        # Ownership failures intentionally look identical to missing records.
        raise HTTPException(status_code=404, detail="Turn not found")
    return {
        "turn_id": result["turn_id"],
        "conversation_id": result["conversation_id"],
        "assistant_message_id": result["assistant_message_id"],
        "status": result["status"],
    }
