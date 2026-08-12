"""Pydantic request/response schemas for the API."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ChatRequest(BaseModel):
    query: str = Field(default="", max_length=3000, description="User's question")
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
    operation: Literal["message", "continue_case"] = "message"
    intent_hint: Literal[
        "auto", "legal_lookup", "legal_explain_compare", "case_assessment", "compliance_checklist"
    ] = "auto"
    interaction_source: Literal["composer", "quick_action", "case_panel"] = "composer"
    case_patch: dict[str, str] = Field(default_factory=dict)
    fact_updates: dict[str, ChatFactUpdate] = Field(default_factory=dict)
    replay_metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_turn_contract(self) -> ChatRequest:
        self.query = " ".join(self.query.split())
        if self.operation == "message" and not self.query:
            raise ValueError("query is required when operation=message")
        self.case_patch = {
            str(key): " ".join(str(value).split())[:240]
            for key, value in self.case_patch.items()
            if str(value).strip()
        }
        return self

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


class ChatFactUpdate(BaseModel):
    """Typed case patch carried through chat and replay metadata."""

    value: str = Field(default="", max_length=240)
    confirmation_status: Literal["user_confirmed", "document_verified", "unknown"] = "unknown"

    @field_validator("value", mode="before")
    @classmethod
    def clean_value(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:240]


class HealthResponse(BaseModel):
    status: str
    qdrant: str
    redis: str
    openai: str = "ok"  # NEW: Track OpenAI API status
