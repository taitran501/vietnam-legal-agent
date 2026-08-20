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
    # The wire value is a legacy compatibility string; the semantic name is
    # CASE_ASSESSMENT because the same task covers every legal domain.
    CASE_ASSESSMENT = "assess_epr_obligation"
    BUILD_COMPLIANCE_CHECKLIST = "build_compliance_checklist"
    CHITCHAT = "chitchat"


class Action(StrEnum):
    """The only actions a planner or graph may record."""

    LOAD_CONTEXT = "load_context"
    VALIDATE_INPUT = "validate_input"
    UNDERSTAND_TASK = "understand_task"
    CHECK_CACHE = "check_cache"
    ANSWER_CACHE = "answer_cache"
    ASK_USER = "ask_user"
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
    RESEARCH_COMPLETE = "research_complete"
    INVALID_INPUT = "invalid_input"
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
    effective_from: str | None = None
    effective_to: str | None = None
    effective_status: str | None = None
    current_law_support: bool | None = None
    amendment_relationship: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DocumentRecord:
        meta = dict(value.get("metadata") or {})
        return cls(
            content=str(value.get("content", value.get("page_content", ""))),
            metadata=meta,
            document_id=str(value.get("document_id", value.get("id", ""))),
            score=value.get("score"),
            source=str(value.get("source", "legal")),
            effective_from=value.get("effective_from") or meta.get("Effective_From") or meta.get("effective_from"),
            effective_to=value.get("effective_to") or meta.get("Effective_To") or meta.get("effective_to"),
            effective_status=value.get("effective_status") or meta.get("Effective_Status") or meta.get("effective_status"),
            current_law_support=value.get("current_law_support") if value.get("current_law_support") is not None else meta.get("Current_Law_Support") if meta.get("Current_Law_Support") is not None else meta.get("current_law_support"),
            amendment_relationship=list(value.get("amendment_relationship") or meta.get("Amendment_Relationship") or meta.get("amendment_relationship") or []),
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
    has_superseded_sources: bool = False
    temporal_warnings: list[str] = field(default_factory=list)

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
    turn_id: str
    user_message_id: str
    target_assistant_message_id: int | None
    turn_status: str
    query: str
    standalone_query: str
    user_id: str
    conversation_id: str
    legacy_session_id: str
    corpus_id: str
    pipeline_version: str
    corpus_version: str
    corpus_sha: str
    embedding_profile: str
    mode: str
    operation: str
    intent_hint: str
    interaction_source: str
    case_patch: dict[str, str]
    fact_updates: dict[str, dict[str, Any]]
    outcome: str
    result_type: str
    understanding_confidence: float
    required_issues: list[str]
    covered_issues: list[str]
    issue_states: dict[str, Any]
    evidence_bundles: dict[str, list[dict[str, Any]]]
    case_fields: list[dict[str, Any]]
    route: str
    source_scope: str
    available_actions: list[str]
    evidence_status: str
    clarification_required: bool
    run_started_at: str
    run_ended_at: str
    run_duration_ms: float
    cache_status: str

    history: list[dict[str, Any]]
    history_summary: str
    active_case: dict[str, Any] | None
    task_type: str
    is_follow_up: bool
    facts: dict[str, str]
    missing_facts: list[str]
    case_state: dict[str, Any] | None
    follow_up_question: str
    is_legal_scope: bool

    cached_answer: str | None
    cached_evidence: list[dict[str, Any]]
    cached_citations: list[dict[str, Any]]
    cached_source: str
    cache_key: str
    web_answer: str
    explicit_articles: list[str]
    explicit_anchor_details: list[dict[str, str]]
    citation_error: str
    safe_stop_reason: str
    evidence: list[dict[str, Any]]
    evidence_assessment: dict[str, Any]
    tool_results: list[ToolResult]
    trace_events: list[dict[str, Any]]
    answer: str
    citations: list[dict[str, Any]]
    assessment: dict[str, Any] | None
    checklist: list[dict[str, Any]]
    source: str
    assistant_message_id: str
    corpus_as_of_date: str
    preview: bool
    rule_id: str
    sources: list[dict[str, Any]]
    replay_metadata: dict[str, Any]
    validation_errors: dict[str, str]

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
    state.setdefault("trace_events", []).append(
        {
            "sequence": len(sequence),
            "node": action.value,
            "status": "completed",
            "reason_code": "",
            "payload": {},
        }
    )


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
