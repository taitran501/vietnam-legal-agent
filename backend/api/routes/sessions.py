"""
Session management endpoints.

Provides:
- GET /api/v1/sessions - List all conversations
- GET /api/v1/sessions/{id} - Get conversation details
- DELETE /api/v1/sessions/{id} - Delete conversation
- PATCH /api/v1/sessions/{id} - Update conversation (rename)
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from backend.api import metrics
from backend.api.principal import principal_from_request_state
from backend.history import (
    archive_conversation as archive_conversation_persistent,
)
from backend.history import (
    delete_conversation as delete_conversation_persistent,
)
from backend.history import (
    ensure_conversation,
)
from backend.history import (
    get_case_state as get_case_state_persistent,
)
from backend.history import (
    get_conversation as get_conversation_persistent,
)
from backend.history import (
    list_conversations as list_conversations_persistent,
)
from backend.history import (
    list_messages as list_messages_persistent,
)
from backend.history import (
    pin_conversation as pin_conversation_persistent,
)
from backend.history import (
    rename_conversation as rename_conversation_persistent,
)
from backend.history import (
    save_case_state as save_case_state_persistent,
)
from epr_agent.domain.epr_rules import CaseFormResolver
from epr_agent.domain.models import TaskType
from epr_agent.domain.tasks import missing_facts
from epr_agent.domain.v4 import CaseStateV4, FactConfirmationStatus, FactValue

logger = logging.getLogger(__name__)
router = APIRouter()
_case_form_resolver = CaseFormResolver()


class SessionInfo(BaseModel):
    """Session summary info for listing."""
    id: str
    title: str
    created_at: float
    updated_at: float | None = None
    message_count: int
    archived: bool = False
    pinned: bool = False


class SessionDetail(BaseModel):
    """Full session detail with messages."""
    id: str
    title: str
    messages: list[dict]
    created_at: float
    updated_at: float | None = None
    message_count: int


class UpdateSessionRequest(BaseModel):
    """Request body for updating session."""
    title: str | None = Field(default=None, max_length=200)


class CreateSessionRequest(BaseModel):
    """Request body for creating a new conversation."""
    title: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=128)


class ArchiveSessionRequest(BaseModel):
    """Request body for archive state updates."""
    archived: bool = True


class PinSessionRequest(BaseModel):
    """Request body for pin state updates."""
    pinned: bool = True


class MessagePage(BaseModel):
    """Cursor-paginated message response."""
    conversation_id: str
    messages: list[dict]
    next_cursor: int | None = None


class CaseStateResponse(BaseModel):
    """Conversation-scoped facts used by assessment/checklist workflow runs."""

    task_type: Literal["assess_epr_obligation", "build_compliance_checklist"]
    status: Literal["collecting", "ready", "completed"]
    schema_version: str = "legacy-v3"
    facts: dict[str, Any] = Field(default_factory=dict)
    missing_facts: list[str] = Field(default_factory=list)
    last_query: str = ""
    decision_status: str | None = None
    issue_states: dict[str, Any] = Field(default_factory=dict)
    as_of_date: str = ""
    fields: list[dict[str, Any]] = Field(default_factory=list)
    form_version: str = "case-form-v1"
    completed_count: int = 0
    required_count: int = 0
    validation_errors: dict[str, str] = Field(default_factory=dict)
    updated_at: float | None = None


class FactUpdate(BaseModel):
    value: str = Field(default="", max_length=240)
    confirmation_status: FactConfirmationStatus = FactConfirmationStatus.UNKNOWN

    @field_validator("value", mode="before")
    @classmethod
    def clean_value(cls, value: object) -> str:
        return " ".join(str(value or "").split())[:240]


class UpdateCaseRequest(BaseModel):
    """User-editable case facts. Server derives status and missing fields."""

    task_type: Literal["assess_epr_obligation", "build_compliance_checklist"] | None = None
    facts: dict[str, str] = Field(default_factory=dict)
    fact_updates: dict[str, FactUpdate] = Field(default_factory=dict)

    @field_validator("facts")
    @classmethod
    def validate_facts(cls, facts: dict[str, str]) -> dict[str, str]:
        return {key: " ".join(str(value).split())[:160] for key, value in facts.items()}


def _current_user_id(request: Request) -> str:
    return principal_from_request_state(request).id


@router.post("/sessions", response_model=SessionInfo, tags=["sessions"])
async def create_session(request: Request, body: CreateSessionRequest):
    """Create a new conversation explicitly (preferred over implicit creation)."""
    user_id = _current_user_id(request)
    conversation_id = await ensure_conversation(
        user_id=user_id,
        conversation_id=body.session_id,
        title_seed=body.title or "New Conversation",
    )

    if body.title:
        await rename_conversation_persistent(user_id=user_id, conversation_id=conversation_id, title=body.title)

    conversation = await get_conversation_persistent(user_id=user_id, conversation_id=conversation_id)
    if conversation is None:
        raise HTTPException(status_code=500, detail="Failed to create session")

    return SessionInfo(
        id=conversation["id"],
        title=conversation["title"],
        created_at=conversation["created_at"],
        updated_at=conversation.get("updated_at"),
        message_count=conversation.get("message_count", 0),
        archived=conversation.get("archived", False),
        pinned=conversation.get("pinned", False),
    )


@router.get("/sessions", response_model=list[SessionInfo], tags=["sessions"])
async def list_sessions(request: Request, limit: int = 50, offset: int = 0, q: str = ""):
    """
    List all conversations sorted by creation time (newest first).
    
    Returns session summaries with titles, message counts, and timestamps.
    """
    user_id = _current_user_id(request)
    sessions = await list_conversations_persistent(user_id=user_id, limit=limit, offset=offset, search=q[:200])
    return [
        SessionInfo(
            id=s["id"],
            title=s["title"],
            created_at=s["created_at"],
            updated_at=s.get("updated_at"),
            message_count=s.get("message_count", 0),
            archived=s.get("archived", False),
            pinned=s.get("pinned", False),
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}", response_model=SessionDetail, tags=["sessions"])
async def get_session(request: Request, session_id: str):
    """
    Get full conversation details including all messages.
    
    Returns the complete message history with timestamps for reloading a conversation.
    """
    user_id = _current_user_id(request)
    try:
        conversation = await get_conversation_persistent(user_id=user_id, conversation_id=session_id)
    except Exception as exc:
        metrics.track_session_load_failure("storage_unavailable")
        logger.exception("session_load_failure reason=storage_unavailable")
        raise HTTPException(status_code=503, detail="Conversation storage is unavailable") from exc
    if conversation is None:
        metrics.track_session_load_failure("not_found_or_forbidden")
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionDetail(
        id=conversation["id"],
        title=conversation["title"],
        messages=conversation["messages"],
        created_at=conversation["created_at"],
        updated_at=conversation.get("updated_at"),
        message_count=conversation.get("message_count", 0),
    )


@router.delete("/sessions/{session_id}", tags=["sessions"])
async def delete_session(request: Request, session_id: str):
    """
    Delete a conversation and all its messages.
    
    This permanently removes the conversation and its case/run state.
    """
    user_id = _current_user_id(request)
    deleted = await delete_conversation_persistent(user_id=user_id, conversation_id=session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")

    return {"status": "ok", "message": "Session deleted"}


@router.patch("/sessions/{session_id}", response_model=SessionInfo, tags=["sessions"])
async def update_session(request: Request, session_id: str, body: UpdateSessionRequest):
    """
    Update conversation metadata (e.g., rename title).
    
    Allows users to give meaningful names to conversations instead of auto-generated titles.
    """
    if not body.title:
        raise HTTPException(status_code=400, detail="Title is required")
    
    user_id = _current_user_id(request)
    renamed = await rename_conversation_persistent(user_id=user_id, conversation_id=session_id, title=body.title)
    if not renamed:
        raise HTTPException(status_code=404, detail="Session not found")
    conversation = await get_conversation_persistent(user_id=user_id, conversation_id=session_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionInfo(
        id=conversation["id"],
        title=conversation["title"],
        created_at=conversation["created_at"],
        updated_at=conversation.get("updated_at"),
        message_count=conversation.get("message_count", 0),
        archived=conversation.get("archived", False),
        pinned=conversation.get("pinned", False),
    )


@router.patch("/sessions/{session_id}/archive", response_model=SessionInfo, tags=["sessions"])
async def archive_session(request: Request, session_id: str, body: ArchiveSessionRequest):
    """Archive or unarchive a conversation."""
    user_id = _current_user_id(request)
    archived = await archive_conversation_persistent(
        user_id=user_id,
        conversation_id=session_id,
        archived=body.archived,
    )
    if not archived:
        raise HTTPException(status_code=404, detail="Session not found")

    conversation = await get_conversation_persistent(user_id=user_id, conversation_id=session_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionInfo(
        id=conversation["id"],
        title=conversation["title"],
        created_at=conversation["created_at"],
        updated_at=conversation.get("updated_at"),
        message_count=conversation.get("message_count", 0),
        archived=conversation.get("archived", False),
        pinned=conversation.get("pinned", False),
    )


@router.patch("/sessions/{session_id}/pin", response_model=SessionInfo, tags=["sessions"])
async def pin_session(request: Request, session_id: str, body: PinSessionRequest):
    """Pin or unpin a conversation."""
    user_id = _current_user_id(request)
    pinned = await pin_conversation_persistent(
        user_id=user_id,
        conversation_id=session_id,
        pinned=body.pinned,
    )
    if not pinned:
        raise HTTPException(status_code=404, detail="Session not found")

    conversation = await get_conversation_persistent(user_id=user_id, conversation_id=session_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionInfo(
        id=conversation["id"],
        title=conversation["title"],
        created_at=conversation["created_at"],
        updated_at=conversation.get("updated_at"),
        message_count=conversation.get("message_count", 0),
        archived=conversation.get("archived", False),
        pinned=conversation.get("pinned", False),
    )


@router.get("/sessions/{session_id}/case", response_model=CaseStateResponse | None, tags=["case"])
async def get_session_case(request: Request, session_id: str):
    """Hydrate the right-side case workspace without loading all chat history."""

    user_id = _current_user_id(request)
    conversation = await get_conversation_persistent(user_id=user_id, conversation_id=session_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Session not found")
    case_state = await get_case_state_persistent(user_id=user_id, conversation_id=session_id)
    if case_state is None:
        return None
    if case_state.get("schema_version") == "v4":
        parsed = {key: FactValue.model_validate(value) for key, value in dict(case_state.get("facts") or {}).items()}
        resolved = _case_form_resolver.resolve(str(case_state.get("task_type") or TaskType.ASSESS_EPR_OBLIGATION.value), parsed)
        case_state["fields"] = [field.model_dump() for field in resolved.fields]
        case_state["form_version"] = resolved.form_version
        case_state["completed_count"] = resolved.completed_count
        case_state["required_count"] = resolved.required_count
        case_state["validation_errors"] = resolved.validation_errors
    return CaseStateResponse(**case_state)


@router.patch("/sessions/{session_id}/case", response_model=CaseStateResponse, tags=["case"])
async def update_session_case(request: Request, session_id: str, body: UpdateCaseRequest):
    """Persist user-edited facts; the server owns readiness and missing fields."""

    user_id = _current_user_id(request)
    conversation = await get_conversation_persistent(user_id=user_id, conversation_id=session_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Session not found")
    current = await get_case_state_persistent(user_id=user_id, conversation_id=session_id)
    task_value = body.task_type or (current or {}).get("task_type") or TaskType.ASSESS_EPR_OBLIGATION.value
    task = TaskType(task_value)
    if task not in {TaskType.ASSESS_EPR_OBLIGATION, TaskType.BUILD_COMPLIANCE_CHECKLIST}:
        raise HTTPException(status_code=422, detail="Case workspace supports assessment or checklist only")
    if (current or {}).get("schema_version") == "v4":
        facts = {
            key: FactValue.model_validate(value)
            for key, value in dict((current or {}).get("facts") or {}).items()
        }
        # ``facts`` is the one-release compatibility shape.  A typed update
        # carries the authoritative confirmation status when both shapes are
        # present, as the browser sends both during the compatibility window.
        updates: dict[str, FactUpdate] = {
            key: FactUpdate(value=value, confirmation_status=FactConfirmationStatus.UNKNOWN)
            for key, value in body.facts.items()
        }
        updates.update(body.fact_updates)
        resolved = _case_form_resolver.resolve(
            task.value,
            facts,
            {key: update.model_dump(mode="json") for key, update in updates.items()},
        )
        if resolved.validation_errors:
            raise HTTPException(
                status_code=422,
                detail={"validation_errors": resolved.validation_errors},
            )
        state = CaseStateV4(
            task_type=task.value,
            status=resolved.status,
            facts=resolved.facts,
            missing_facts=resolved.missing_facts,
            issue_states=dict((current or {}).get("issue_states") or {}),
            as_of_date=str((current or {}).get("as_of_date") or ""),
            last_query=(current or {}).get("last_query", ""),
            fields=resolved.fields,
            form_version=resolved.form_version,
            validation_errors=resolved.validation_errors,
            completed_count=resolved.completed_count,
            required_count=resolved.required_count,
        ).model_dump(mode="json")
    else:
        legacy_facts: dict[str, str] = {
            str(key): str(value)
            for key, value in dict((current or {}).get("facts") or {}).items()
            if value
        }
        legacy_facts.update(body.facts)
        legacy_facts.update({key: update.value for key, update in body.fact_updates.items()})
        legacy_facts = {key: value for key, value in legacy_facts.items() if value}
        state = {
            "task_type": task.value,
            "facts": legacy_facts,
            "missing_facts": missing_facts(task, legacy_facts),
            "last_query": (current or {}).get("last_query", ""),
        }
    saved = await save_case_state_persistent(user_id=user_id, conversation_id=session_id, state=state)
    if saved.get("schema_version") == "v4":
        parsed = {key: FactValue.model_validate(value) for key, value in dict(saved.get("facts") or {}).items()}
        resolved = _case_form_resolver.resolve(str(saved.get("task_type") or TaskType.ASSESS_EPR_OBLIGATION.value), parsed)
        saved["fields"] = [field.model_dump() for field in resolved.fields]
        saved["form_version"] = resolved.form_version
        saved["completed_count"] = resolved.completed_count
        saved["required_count"] = resolved.required_count
        saved["validation_errors"] = resolved.validation_errors
    return CaseStateResponse(**saved)


@router.get("/sessions/{session_id}/messages", response_model=MessagePage, tags=["sessions"])
async def list_session_messages(
    request: Request,
    session_id: str,
    limit: int = 50,
    cursor: int | None = None,
):
    """List conversation messages with cursor pagination."""
    user_id = _current_user_id(request)
    page = await list_messages_persistent(
        user_id=user_id,
        conversation_id=session_id,
        limit=limit,
        cursor=cursor,
    )
    if not page.get("messages"):
        conversation = await get_conversation_persistent(user_id=user_id, conversation_id=session_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Session not found")
    return MessagePage(
        conversation_id=session_id,
        messages=page.get("messages", []),
        next_cursor=page.get("next_cursor"),
    )
