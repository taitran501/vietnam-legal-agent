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
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.history import (
    ensure_conversation,
    list_conversations as list_conversations_persistent,
    list_messages as list_messages_persistent,
    get_conversation as get_conversation_persistent,
    rename_conversation as rename_conversation_persistent,
    archive_conversation as archive_conversation_persistent,
    pin_conversation as pin_conversation_persistent,
    delete_conversation as delete_conversation_persistent,
)
from backend.memory import session_store

logger = logging.getLogger(__name__)
router = APIRouter()


class SessionInfo(BaseModel):
    """Session summary info for listing."""
    id: str
    title: str
    created_at: float
    updated_at: Optional[float] = None
    message_count: int
    archived: bool = False
    pinned: bool = False


class SessionDetail(BaseModel):
    """Full session detail with messages."""
    id: str
    title: str
    messages: list[dict]
    created_at: float
    updated_at: Optional[float] = None
    message_count: int


class UpdateSessionRequest(BaseModel):
    """Request body for updating session."""
    title: Optional[str] = Field(default=None, max_length=200)


class CreateSessionRequest(BaseModel):
    """Request body for creating a new conversation."""
    title: Optional[str] = Field(default=None, max_length=200)
    session_id: Optional[str] = Field(default=None, max_length=128)


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
    next_cursor: Optional[int] = None


def _current_user_id(request: Request) -> str:
    return getattr(request.state, "api_key_hash", None) or "dev-local"


@router.post("/sessions", response_model=SessionInfo, tags=["sessions"])
async def create_session(request: Request, body: CreateSessionRequest):
    """Create a new conversation explicitly (preferred over implicit creation)."""
    settings = get_settings()
    if not settings.history_enabled:
        raise HTTPException(status_code=400, detail="Persistent history is disabled")

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
async def list_sessions(request: Request, limit: int = 50, offset: int = 0):
    """
    List all conversations sorted by creation time (newest first).
    
    Returns session summaries with titles, message counts, and timestamps.
    """
    settings = get_settings()
    if settings.history_enabled:
        user_id = _current_user_id(request)
        sessions = await list_conversations_persistent(user_id=user_id, limit=limit, offset=offset)
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

    # Legacy fallback
    sessions = await session_store.list_sessions(limit=limit, offset=offset)
    return [SessionInfo(**s) for s in sessions]


@router.get("/sessions/{session_id}", response_model=SessionDetail, tags=["sessions"])
async def get_session(request: Request, session_id: str):
    """
    Get full conversation details including all messages.
    
    Returns the complete message history with timestamps for reloading a conversation.
    """
    settings = get_settings()
    if settings.history_enabled:
        user_id = _current_user_id(request)
        conversation = await get_conversation_persistent(user_id=user_id, conversation_id=session_id)
        if conversation is not None:
            return SessionDetail(
                id=conversation["id"],
                title=conversation["title"],
                messages=conversation["messages"],
                created_at=conversation["created_at"],
                updated_at=conversation.get("updated_at"),
                message_count=conversation.get("message_count", 0),
            )

    # Legacy fallback
    messages = await session_store.get_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Session not found")

    meta = await session_store.get_session_meta(session_id)
    return SessionDetail(
        id=session_id,
        title=meta.get("title", "New Conversation"),
        messages=messages,
        created_at=meta.get("created_at", 0),
        updated_at=meta.get("updated_at"),
        message_count=len(messages),
    )


@router.delete("/sessions/{session_id}", tags=["sessions"])
async def delete_session(request: Request, session_id: str):
    """
    Delete a conversation and all its messages.
    
    This permanently removes the conversation from Redis and cannot be undone.
    """
    settings = get_settings()
    deleted = False
    legacy_exists = False

    # Check legacy existence before deletion for proper 404 semantics.
    try:
        legacy_exists = bool(await session_store.get_history(session_id))
    except Exception:
        legacy_exists = False

    if settings.history_enabled:
        user_id = _current_user_id(request)
        deleted = await delete_conversation_persistent(user_id=user_id, conversation_id=session_id)

    # Keep legacy cleanup during migration
    await session_store.clear_session(session_id)

    if settings.history_enabled and not deleted and not legacy_exists:
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
    
    settings = get_settings()
    if settings.history_enabled:
        user_id = _current_user_id(request)
        renamed = await rename_conversation_persistent(user_id=user_id, conversation_id=session_id, title=body.title)
        if renamed:
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

    # Legacy fallback
    messages = await session_store.get_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Session not found")

    await session_store.set_session_meta(session_id, {"title": body.title})
    meta = await session_store.get_session_meta(session_id)

    return SessionInfo(
        id=session_id,
        title=body.title,
        created_at=meta.get("created_at", 0),
        updated_at=meta.get("updated_at"),
        message_count=len(messages),
    )


@router.patch("/sessions/{session_id}/archive", response_model=SessionInfo, tags=["sessions"])
async def archive_session(request: Request, session_id: str, body: ArchiveSessionRequest):
    """Archive or unarchive a conversation."""
    settings = get_settings()
    if not settings.history_enabled:
        raise HTTPException(status_code=400, detail="Persistent history is disabled")

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
    settings = get_settings()
    if not settings.history_enabled:
        raise HTTPException(status_code=400, detail="Persistent history is disabled")

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


@router.get("/sessions/{session_id}/messages", response_model=MessagePage, tags=["sessions"])
async def list_session_messages(
    request: Request,
    session_id: str,
    limit: int = 50,
    cursor: Optional[int] = None,
):
    """List conversation messages with cursor pagination."""
    settings = get_settings()
    if settings.history_enabled:
        user_id = _current_user_id(request)
        page = await list_messages_persistent(
            user_id=user_id,
            conversation_id=session_id,
            limit=limit,
            cursor=cursor,
        )
        return MessagePage(
            conversation_id=session_id,
            messages=page.get("messages", []),
            next_cursor=page.get("next_cursor"),
        )

    # Legacy fallback without true pagination support.
    messages = await session_store.get_history(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Session not found")

    normalized = [
        {
            "id": idx,
            "role": m.get("role"),
            "content": m.get("content"),
            "timestamp": m.get("timestamp"),
        }
        for idx, m in enumerate(messages, start=1)
    ]
    return MessagePage(conversation_id=session_id, messages=normalized, next_cursor=None)
