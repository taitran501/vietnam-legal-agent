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

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from backend.api.schemas import ChatRequest
from backend.api.routes.health import readiness_payload
from epr_agent.api.routes import stream_chat_events as agentic_stream_chat

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", tags=["chat"])
async def chat(request: Request, body: ChatRequest):
    """Stream chatbot responses as Server-Sent Events."""
    # Canonical identifier moving forward: conversation_id.
    # Backward compatibility: accept legacy session_id if conversation_id is missing.
    conversation_id = body.conversation_id or body.session_id or str(uuid.uuid4())

    # User scope for durable history: API key hash set by auth middleware.
    # Fallback keeps local development functional when auth is disabled.
    user_id = getattr(request.state, "api_key_hash", None) or "dev-local"
    runtime = getattr(request.app.state, "workflow_runtime", None)

    readiness, is_ready = await readiness_payload()
    if not is_ready:
        async def _not_ready():
            yield {
                "data": json.dumps(
                    {
                        "type": "error",
                        "code": "corpus_not_ready",
                        "message": "Dữ liệu pháp luật đang chưa sẵn sàng. Vui lòng thử lại sau khi index hoàn tất.",
                        "readiness": readiness,
                    },
                    ensure_ascii=False,
                )
            }
        return EventSourceResponse(_not_ready(), status_code=503)
    
    # Log session creation for audit trail
    logger.info(
        "Chat request: user_id=%s, conversation_id=%s, query_length=%d",
        user_id,
        conversation_id,
        len(body.query),
    )

    async def _event_generator():
        try:
            async for event in agentic_stream_chat(
                query=body.query,
                user_id=user_id,
                conversation_id=conversation_id,
                legacy_session_id=body.session_id,
                runtime=runtime,
            ):
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
            yield {
                "data": json.dumps({
                    "type": "error",
                    "message": "Internal server error. Please try again.",
                })
            }

    return EventSourceResponse(
        _event_generator(),
        headers={
            "X-Conversation-ID": conversation_id,
            # Backward compatibility for current clients.
            "X-Session-ID": conversation_id,
        },
    )
