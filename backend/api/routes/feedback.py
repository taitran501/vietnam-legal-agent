"""Durable, owner-scoped feedback endpoints."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from backend.api.principal import principal_from_request_state
from backend.history import (
    feedback_stats as feedback_stats_persistent,
)
from backend.history import (
    resolve_assistant_message_id,
    save_feedback,
)

router = APIRouter()


class FeedbackPayload(BaseModel):
    rating: int = Field(..., description="1 = thumbs down, 2 = thumbs up")
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, value: int) -> int:
        if value not in (1, 2):
            raise ValueError("Rating must be 1 (thumbs down) or 2 (thumbs up)")
        return value

    @field_validator("comment")
    @classmethod
    def sanitize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", value)
        return cleaned.strip() if cleaned.strip() else None


class FeedbackRequest(FeedbackPayload):
    """Compatibility body retained for one release.

    New clients should use the conversation/message resource endpoint.  The
    legacy array index is resolved inside the authenticated owner namespace.
    """

    session_id: str = Field(..., min_length=1, max_length=128)
    message_index: int = Field(..., ge=0)
    message_id: int | None = Field(default=None, ge=1)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", value):
            raise ValueError("session_id must contain only letters, numbers, hyphens, or underscores")
        return value


async def _persist_feedback(request: Request, conversation_id: str, message_id: int, body: FeedbackPayload):
    principal = principal_from_request_state(request)
    if principal.type == "service" and not principal.has_scope("feedback:write"):
        raise HTTPException(status_code=403, detail="Service token lacks the feedback:write scope")
    saved = await save_feedback(
        principal.id,
        conversation_id,
        message_id,
        body.rating,
        body.comment,
    )
    if saved is None:
        # Do not reveal whether another owner has a matching conversation or
        # message.  The same response covers ownership and missing targets.
        raise HTTPException(status_code=404, detail="Assistant message not found")
    return {"status": "ok", "feedback": saved}


@router.put("/conversations/{conversation_id}/messages/{message_id}/feedback", tags=["feedback"])
async def update_message_feedback(
    conversation_id: str,
    message_id: int,
    body: FeedbackPayload,
    request: Request,
):
    try:
        return await _persist_feedback(request, conversation_id, message_id, body)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Feedback storage is unavailable") from exc


@router.post("/feedback", tags=["feedback"])
async def submit_feedback(body: FeedbackRequest, request: Request):
    """Compatibility endpoint that resolves the legacy message index safely."""

    principal = principal_from_request_state(request)
    try:
        message_id = body.message_id or await resolve_assistant_message_id(
            principal.id,
            body.session_id,
            body.message_index,
        )
        if message_id is None:
            raise HTTPException(status_code=404, detail="Assistant message not found")
        return await _persist_feedback(request, body.session_id, message_id, body)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Feedback storage is unavailable") from exc


@router.get("/feedback/stats", tags=["feedback"])
async def get_feedback_stats(request: Request):
    principal = principal_from_request_state(request)
    if not (principal.has_role("quality_admin") or principal.has_scope("quality:read")):
        raise HTTPException(status_code=403, detail="quality_admin role or quality:read scope required")
    try:
        return await feedback_stats_persistent()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Feedback storage is unavailable") from exc
