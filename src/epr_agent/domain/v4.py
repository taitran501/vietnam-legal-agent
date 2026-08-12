"""Typed contracts for Pipeline V4.

V3 stored most state in loose dictionaries.  V4 keeps the graph boundary
serialisable, but gives the important business decisions explicit schemas so a
route cannot accidentally present a safe-stop as a completed assessment.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class TurnOperation(StrEnum):
    MESSAGE = "message"
    CONTINUE_CASE = "continue_case"


class InteractionSource(StrEnum):
    COMPOSER = "composer"
    QUICK_ACTION = "quick_action"
    CASE_PANEL = "case_panel"


class WorkflowOutcome(StrEnum):
    COMPLETED = "completed"
    NEEDS_INFORMATION = "needs_information"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    OUT_OF_SCOPE = "out_of_scope"
    FAILED = "failed"


class ResultType(StrEnum):
    LEGAL_ANSWER = "legal_answer"
    ASSESSMENT = "assessment"
    CHECKLIST = "checklist"
    NONE = "none"


class AssessmentStatus(StrEnum):
    LIKELY_IN_SCOPE = "likely_in_scope"
    LIKELY_OUT_OF_SCOPE = "likely_out_of_scope"
    NEEDS_INFORMATION = "needs_information"
    CANNOT_DETERMINE = "cannot_determine"


class FactSource(StrEnum):
    USER_TURN = "user_turn"
    CASE_PANEL = "case_panel"
    SYSTEM_DEFAULT = "system_default"


class FactConfirmationStatus(StrEnum):
    """How a fact was confirmed without implying legal verification."""

    USER_CONFIRMED = "user_confirmed"
    DOCUMENT_VERIFIED = "document_verified"
    UNKNOWN = "unknown"


class FactValue(BaseModel):
    value: str = Field(max_length=240)
    source: FactSource
    source_turn: str = ""
    evidence_span: str = Field(default="", max_length=300)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    verified: bool = False
    confirmation_status: FactConfirmationStatus = FactConfirmationStatus.UNKNOWN

    @field_validator("value", "evidence_span", mode="before")
    @classmethod
    def _clean(cls, value: object) -> str:
        return " ".join(str(value or "").split())


class CaseField(BaseModel):
    key: str
    label: str
    kind: Literal["text", "select", "number", "boolean"] = "text"
    options: list[dict[str, str]] = Field(default_factory=list)
    required: bool = False
    importance: Literal["required", "conditional", "informational"] = "informational"
    missing: bool = False
    value: str = ""
    help_text: str = ""


class LegalIssue(BaseModel):
    issue_id: str
    label: str
    required_facts: list[str] = Field(default_factory=list)
    query: str
    required_anchors: list[str] = Field(default_factory=list)
    required: bool = True


class IssueState(BaseModel):
    issue_id: str
    status: Literal["pending", "missing_facts", "supported", "insufficient_evidence"] = "pending"
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class EvidenceBundle(BaseModel):
    issue_id: str
    documents: list[dict[str, Any]] = Field(default_factory=list)
    covered: bool = False
    reason: str = ""


class AssessmentReason(BaseModel):
    claim: str
    evidence_ids: list[str] = Field(default_factory=list)


class AssessmentResult(BaseModel):
    status: AssessmentStatus
    conclusion: str
    reasons: list[AssessmentReason] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    rule_id: str = ""
    active_evidence_ids: list[str] = Field(default_factory=list)
    corpus_version: str = ""
    corpus_as_of_date: str = ""


class CaseStateV4(BaseModel):
    schema_version: str = "v4"
    task_type: str = "assess_epr_obligation"
    status: Literal["collecting", "ready", "completed"] = "collecting"
    facts: dict[str, FactValue] = Field(default_factory=dict)
    missing_facts: list[str] = Field(default_factory=list)
    issue_states: dict[str, IssueState] = Field(default_factory=dict)
    decision_status: AssessmentStatus | None = None
    as_of_date: str = ""
    last_query: str = ""


class QueryPlanV4(BaseModel):
    route: str
    confidence: float = Field(ge=0.0, le=1.0)
    standalone_query: str
    explicit_anchors: list[dict[str, str]] = Field(default_factory=list)
    facts: dict[str, FactValue] = Field(default_factory=dict)
    is_follow_up: bool = False


class RetrievalRequest(BaseModel):
    route: str
    issue_id: str = "legal_lookup"
    query: str
    required_anchors: list[str] = Field(default_factory=list)
    metadata_filters: dict[str, str] = Field(default_factory=dict)
    top_k: int = Field(default=10, ge=1, le=20)


CASE_FIELD_LABELS: dict[str, str] = {
    "business_role": "Vai trò doanh nghiệp",
    "quality_label_responsibility": "Trách nhiệm về chất lượng và ghi nhãn",
    "object_kind": "Loại đối tượng",
    "product_group": "Nhóm sản phẩm EPR",
    "packaged_goods_category": "Nhóm hàng hóa được đóng gói",
    "material": "Vật liệu hoặc quy cách",
    "market_placement": "Phạm vi đưa ra thị trường",
    "activity_purpose": "Mục đích sản xuất hoặc nhập khẩu",
    "annual_revenue_vnd": "Doanh thu bán sản phẩm liên quan mỗi năm",
    "reused_by_producer": "Bao bì có được chính doanh nghiệp thu hồi để tái sử dụng không",
    "recovery_rate": "Tỷ lệ thu hồi và tái sử dụng",
}
