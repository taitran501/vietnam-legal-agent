"""Pydantic request/response schemas for the API."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=3000, description="User's question")
    conversation_id: str = Field(
        default="",
        min_length=0,
        max_length=128,
        description="Persistent conversation identifier (preferred)",
    )
    session_id: str = Field(default="", min_length=0, max_length=128, description="Session identifier (empty = auto-generated UUID)")
    mode: Literal["auto", "research_web"] = Field(
        default="auto",
        description="Explicit workflow mode. Web research is never selected automatically.",
    )

    @field_validator("conversation_id", "session_id")
    @classmethod
    def validate_identifier(cls, v: str) -> str:
        """
        Validate session_id format and reject reserved words.
        
        - Empty string: allowed (will be auto-generated as UUID)
        - Reserved words: rejected to prevent conversation leakage
        - Format: only alphanumeric, hyphens, underscores allowed
        """
        # Allow empty string (will be auto-generated)
        if not v:
            return v
        
        # Reject reserved words that could cause leakage
        reserved = {"default", "admin", "system", "test", "anonymous"}
        if v.lower() in reserved:
            raise ValueError(
                f"'{v}' is a reserved session identifier. Please use a unique value or leave empty for auto-generation."
            )
        
        # Validate format
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "identifier must contain only letters, numbers, hyphens, or underscores"
            )
        return v


class HealthResponse(BaseModel):
    status: str
    qdrant: str
    redis: str
    openai: str = "ok"  # NEW: Track OpenAI API status
