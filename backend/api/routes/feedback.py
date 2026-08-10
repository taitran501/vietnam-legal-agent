"""
Feedback tracking endpoints.

Provides:
- POST /api/v1/feedback - Submit feedback (thumbs up/down)
- GET /api/v1/feedback/stats - Get feedback statistics (admin only)
"""

from __future__ import annotations

import logging
import re
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from backend.memory.session_store import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()


class FeedbackRequest(BaseModel):
    """Submit feedback on a response."""
    session_id: str = Field(..., min_length=1, max_length=128, description="Session identifier")
    message_index: int = Field(..., ge=0, description="Index of the assistant message (must be >= 0)")
    rating: int = Field(..., description="1 = thumbs down, 2 = thumbs up")
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        """Validate session_id format to prevent injection."""
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "session_id must contain only letters, numbers, hyphens, or underscores"
            )
        return v
    
    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v: int) -> int:
        """Ensure rating is either 1 (down) or 2 (up)."""
        if v not in (1, 2):
            raise ValueError("Rating must be 1 (thumbs down) or 2 (thumbs up)")
        return v
    
    @field_validator("comment")
    @classmethod
    def sanitize_comment(cls, v: str | None) -> str | None:
        """Sanitize comment by stripping potentially dangerous characters."""
        if v is None:
            return v
        # Remove null bytes and control characters
        import re
        cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', v)
        return cleaned.strip() if cleaned.strip() else None


@router.post("/feedback", tags=["feedback"])
async def submit_feedback(body: FeedbackRequest):
    """
    Submit thumbs up/down feedback on a response.

    Feedback is stored in Redis for quality monitoring and future RLHF training.
    Rating validation (1 or 2) is handled by Pydantic schema.
    """
    try:
        redis_client = await get_redis()
        feedback_key = f"feedback:{body.session_id}:{body.message_index}"

        feedback_data = {
            "rating": body.rating,
            "comment": body.comment,
            "timestamp": time.time(),
        }

        # FIX: Use SET NX for atomic idempotency (prevents TOCTOU race)
        import json
        result = await redis_client.set(
            feedback_key,
            json.dumps(feedback_data, ensure_ascii=False),
            ex=86400 * 30,  # Keep for 30 days
            nx=True,  # Only set if key doesn't exist (atomic)
        )
        
        if not result:
            # Key already exists - feedback already recorded
            logger.info(
                "Feedback already recorded for session=%s, msg_idx=%d",
                body.session_id,
                body.message_index,
            )
            return {"status": "ok", "message": "Feedback already recorded"}
        
        # New feedback - increment counters
        counter_key = "feedback:counters"
        await redis_client.hincrby(counter_key, "total", 1)
        await redis_client.hincrby(counter_key, "up" if body.rating == 2 else "down", 1)

        logger.info(
            "Feedback recorded: session=%s, msg_idx=%d, rating=%d",
            body.session_id,
            body.message_index,
            body.rating,
        )
        return {"status": "ok", "message": "Feedback recorded"}
    except Exception as exc:  # noqa: BLE001 - feedback is best-effort and must not break chat responses
        logger.warning("Failed to store feedback: %s", exc)
        return {"status": "error", "detail": "Failed to store feedback"}


@router.get("/feedback/stats", tags=["feedback"])
async def get_feedback_stats():
    """
    Get aggregate feedback statistics.
    
    Returns total counts of upvotes and downvotes for monitoring quality metrics.
    """
    try:
        redis_client = await get_redis()
        counter_key = "feedback:counters"
        
        counters = await redis_client.hgetall(counter_key)
        
        return {
            "total_up": int(counters.get("up", 0)),
            "total_down": int(counters.get("down", 0)),
            "total_feedback": int(counters.get("total", 0)),
            "satisfaction_rate": _calculate_satisfaction(counters),
        }
    except Exception as exc:  # noqa: BLE001 - aggregate feedback remains optional when Redis is unavailable
        logger.warning("Failed to get feedback stats: %s", exc)
        return {"total_up": 0, "total_down": 0, "total_feedback": 0, "satisfaction_rate": 0}


def _calculate_satisfaction(counters: dict) -> float:
    """Calculate satisfaction rate as percentage."""
    total = int(counters.get("total", 0))
    if total == 0:
        return 0.0
    ups = int(counters.get("up", 0))
    return round((ups / total) * 100, 1)
