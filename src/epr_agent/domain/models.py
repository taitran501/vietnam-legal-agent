"""Small, serialisable domain models shared by every workflow node.

The graph state intentionally contains plain dictionaries/lists at its edges.
This keeps checkpoints, trace records and tests independent from LangChain
objects and makes migration to PostgreSQL straightforward later.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, TypedDict


class TaskType(StrEnum):
    """Tasks supported by the first bounded workflow."""

    LEGAL_LOOKUP = "legal_lookup"
    ASSESS_EPR_OBLIGATION = "assess_epr_obligation"
    BUILD_COMPLIANCE_CHECKLIST = "build_compliance_checklist"
    CHITCHAT = "chitchat"


class Action(StrEnum):
    """The only actions a planner or graph may record."""

    LOAD_CONTEXT = "load_context"
    UNDERSTAND_TASK = "understand_task"
    CHECK_CACHE = "check_cache"
    ANSWER_CACHE = "answer_cache"
    ASK_USER = "ask_user"
    RETRIEVE_FAQ = "retrieve_faq"
    RETRIEVE_LEGAL = "retrieve_legal"
    RETRIEVE_WEB = "retrieve_web"
    EVALUATE_EVIDENCE = "evaluate_evidence"
    COMPOSE_ANSWER = "compose_answer"
    VERIFY_CITATIONS = "verify_citations"
    REPAIR_ANSWER = "repair_answer"
    FINISH = "finish"
    SAFE_STOP = "safe_stop"


class TerminationReason(StrEnum):
    ANSWER_COMPLETE = "answer_complete"
    CACHE_HIT = "cache_hit"
    AWAITING_USER_INPUT = "awaiting_user_input"
    WEB_FALLBACK = "web_fallback"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    OUT_OF_SCOPE = "out_of_scope"
    CITATION_VERIFICATION_FAILED = "citation_verification_failed"
    ERROR = "error"


class CaseStatus(StrEnum):
    """Lifecycle of one conversation-scoped compliance case."""

    COLLECTING = "collecting"
    READY = "ready"
    COMPLETED = "completed"


@dataclass(slots=True)
class DocumentRecord:
    """Repository-neutral representation of one retrieved source."""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    document_id: str = ""
    score: float | None = None
    source: str = "legal"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DocumentRecord:
        return cls(
            content=str(value.get("content", value.get("page_content", ""))),
            metadata=dict(value.get("metadata") or {}),
            document_id=str(value.get("document_id", value.get("id", ""))),
            score=value.get("score"),
            source=str(value.get("source", "legal")),
        )


@dataclass(slots=True)
class Citation:
    index: int
    document_id: str
    label: str
    claim: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvidenceAssessment:
    sufficient: bool
    reason: str
    documents_considered: int = 0
    total_chars: int = 0
    has_legal_metadata: bool = False
    relevance_checked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ChecklistItem:
    item: str
    action: str
    evidence_indices: list[int] = field(default_factory=list)
    assumption: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ToolResult(TypedDict, total=False):
    tool: str
    ok: bool
    latency_ms: float
    count: int
    error: str
    metadata: dict[str, Any]


class AgentState(TypedDict, total=False):
    """State passed between nodes in the LangGraph workflow."""

    trace_id: str
    query: str
    standalone_query: str
    user_id: str
    conversation_id: str
    legacy_session_id: str
    faq_threshold: float
    corpus_version: str

    history: list[dict[str, Any]]
    history_summary: str
    active_case: dict[str, Any] | None
    task_type: str
    is_follow_up: bool
    facts: dict[str, str]
    missing_facts: list[str]
    case_state: dict[str, Any] | None
    follow_up_question: str
    is_epr_scope: bool

    cached_answer: str | None
    cache_key: str
    web_answer: str
    faq_hit: bool
    citation_error: str
    evidence: list[dict[str, Any]]
    evidence_assessment: dict[str, Any]
    tool_results: list[ToolResult]
    answer: str
    citations: list[dict[str, Any]]
    assessment: dict[str, Any] | None
    checklist: list[dict[str, Any]]
    source: str

    current_action: str
    action_sequence: list[str]
    retrieval_actions: int
    repair_count: int
    iteration: int
    citation_valid: bool
    termination_reason: str
    awaiting_user_input: bool
    error: str


def append_action(state: AgentState, action: Action) -> None:
    """Record an action and reject unbounded state growth."""

    sequence = state.setdefault("action_sequence", [])
    sequence.append(action.value)
    state["current_action"] = action.value
    state["iteration"] = int(state.get("iteration", 0)) + 1


def documents_to_dict(documents: list[DocumentRecord]) -> list[dict[str, Any]]:
    return [doc.to_dict() for doc in documents]


def documents_from_dict(documents: list[dict[str, Any]] | None) -> list[DocumentRecord]:
    return [DocumentRecord.from_dict(doc) for doc in (documents or [])]


class WorkflowResult(TypedDict):
    """Stable result returned by the runtime after graph execution."""

    trace_id: str
    answer: str
    documents: list[dict[str, Any]]
    source: str
    metadata: dict[str, Any]
