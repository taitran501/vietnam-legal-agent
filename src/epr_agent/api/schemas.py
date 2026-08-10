"""Schemas for optional clients of the new workflow metadata."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WorkflowMetadata(BaseModel):
    task_type: str = "legal_lookup"
    route: str = "legal_lookup"
    source_scope: str = "legal_corpus"
    corpus_version: str = ""
    corpus_sha: str = ""
    embedding_profile: str = ""
    evidence_status: str = "not_evaluated"
    available_actions: list[str] = Field(default_factory=list)
    case_state: dict[str, Any] | None = None
    assessment: dict[str, Any] | None = None
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    evidence_assessment: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""
    termination_reason: str = ""


class ResponseCompleteEvent(BaseModel):
    type: str = "response_complete"
    text: str
    documents: list[dict[str, Any]] = Field(default_factory=list)
    source: str
    stage: str = "complete"
    task_type: str = "legal_lookup"
    route: str = "legal_lookup"
    source_scope: str = "legal_corpus"
    corpus_version: str = ""
    corpus_sha: str = ""
    embedding_profile: str = ""
    evidence_status: str = "not_evaluated"
    available_actions: list[str] = Field(default_factory=list)
    case_state: dict[str, Any] | None = None
    assessment: dict[str, Any] | None = None
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    evidence_assessment: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""
    termination_reason: str = ""
