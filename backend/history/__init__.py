"""Persistent chat history store."""

from .store import (
    init_history_store,
    ensure_conversation,
    append_exchange,
    get_recent_history,
    list_messages,
    list_conversations,
    get_conversation,
    rename_conversation,
    archive_conversation,
    pin_conversation,
    delete_conversation,
)

__all__ = [
    "init_history_store",
    "ensure_conversation",
    "append_exchange",
    "get_recent_history",
    "list_messages",
    "list_conversations",
    "get_conversation",
    "rename_conversation",
    "archive_conversation",
    "pin_conversation",
    "delete_conversation",
]
