"""Durable, owner-scoped feedback endpoints."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from backend.api.principal import principal_from_request_state
from backend.history import (
    feedback_stats as feedback_stats_persistent,
)
from backend.history import (
    list_quality_feedback,
    resolve_assistant_message_id,
    save_feedback,
    update_quality_feedback,
)
from epr_agent.infra import metrics

router = APIRouter()
logger = logging.getLogger(__name__)


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


class QualityReviewRequest(BaseModel):
    status: str | None = Field(default=None, max_length=32)
    failure_category: str | None = Field(default=None, max_length=64)
    review_notes: str | None = Field(default=None, max_length=2000)
    dataset_case_id: str | None = Field(default=None, max_length=128)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in {"new", "reproduced", "accepted", "rejected", "deferred"}:
            raise ValueError("Invalid quality feedback status")
        return value

    @field_validator("failure_category")
    @classmethod
    def validate_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = re.sub(r"[^a-z0-9_\-]", "", value.casefold())
        if not cleaned:
            raise ValueError("failure_category must contain letters, numbers, hyphens, or underscores")
        return cleaned


def _require_quality_access(request: Request, *, write: bool = False) -> str:
    principal = principal_from_request_state(request)
    required_scope = "quality:write" if write else "quality:read"
    if principal.has_scope("ops") or principal.has_role("quality_admin") or principal.has_scope(required_scope):
        return principal.id
    raise HTTPException(status_code=403, detail=f"{required_scope} scope or quality_admin role required")


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
        metrics.track_feedback_failure("put", "not_found_or_forbidden")
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
        metrics.track_feedback_failure("put", "storage_unavailable")
        logger.exception("feedback_failure operation=put reason=storage_unavailable")
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
        metrics.track_feedback_failure("legacy_post", "storage_unavailable")
        logger.exception("feedback_failure operation=legacy_post reason=storage_unavailable")
        raise HTTPException(status_code=503, detail="Feedback storage is unavailable") from exc


@router.get("/feedback/stats", tags=["feedback"])
async def get_feedback_stats(request: Request):
    principal = principal_from_request_state(request)
    if not (principal.has_role("quality_admin") or principal.has_scope("quality:read")):
        raise HTTPException(status_code=403, detail="quality_admin role or quality:read scope required")
    try:
        return await feedback_stats_persistent()
    except Exception as exc:
        metrics.track_feedback_failure("stats", "storage_unavailable")
        logger.exception("feedback_failure operation=stats reason=storage_unavailable")
        raise HTTPException(status_code=503, detail="Feedback storage is unavailable") from exc


@router.get("/quality/feedback", tags=["quality"])
async def get_quality_feedback(
    request: Request,
    status: str | None = Query(default=None, max_length=32),
    failure_category: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=100),
):
    """List redacted feedback items for the quality triage queue."""

    _require_quality_access(request)
    try:
        items = await list_quality_feedback(
            status=status,
            failure_category=failure_category,
            limit=limit,
        )
        return {"status": "ok", "items": items}
    except Exception as exc:
        logger.exception("quality_feedback_list_failed")
        raise HTTPException(status_code=503, detail="Quality feedback storage is unavailable") from exc


@router.post("/quality/feedback/{quality_id}/review", tags=["quality"])
async def review_quality_feedback(
    quality_id: int,
    body: QualityReviewRequest,
    request: Request,
):
    """Record a reproduced/accepted/rejected triage decision."""

    reviewer_id = _require_quality_access(request, write=True)
    try:
        item = await update_quality_feedback(
            quality_id,
            status=body.status,
            failure_category=body.failure_category,
            reviewer_id=reviewer_id,
            review_notes=body.review_notes,
            dataset_case_id=body.dataset_case_id,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Quality feedback item not found")
        return {"status": "ok", "item": item}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("quality_feedback_review_failed")
        raise HTTPException(status_code=503, detail="Quality feedback storage is unavailable") from exc


@router.get("/quality/feedback/export", tags=["quality"])
async def export_quality_feedback(
    request: Request,
    limit: int = Query(default=100, ge=1, le=100),
):
    """Return accepted redacted items for the fixture-export CLI."""

    _require_quality_access(request)
    try:
        items = await list_quality_feedback(status="accepted", limit=limit)
        exportable = [
            item
            for item in items
            if item.get("trace_id") and isinstance(item.get("evidence_snapshot"), dict)
        ]
        return {
            "schema_version": "quality-feedback-export-v1",
            "items": exportable,
            "skipped": len(items) - len(exportable),
        }
    except Exception as exc:
        logger.exception("quality_feedback_export_failed")
        raise HTTPException(status_code=503, detail="Quality feedback storage is unavailable") from exc
