"""
Redis-backed conversation session store.

Replaces the original in-process ConversationBufferMemory so that
multiple backend workers share the same session state.

Key schema  : session:{session_id}
Value       : JSON list of {"role": "user"|"assistant", "content": str}
TTL         : settings.cache_ttl_seconds (default 86400 = 24 h)
Max exchanges kept: settings.max_chat_history_exchanges (default 3 pairs)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import List

import redis.asyncio as aioredis

from backend.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis client singleton with thread-safe initialization
# ---------------------------------------------------------------------------
_redis_pool: aioredis.ConnectionPool | None = None
_redis_client: aioredis.Redis | None = None
_init_lock: asyncio.Lock | None = None  # Prevents race condition on init


async def get_redis() -> aioredis.Redis:
    """Get Redis client with thread-safe lazy initialization.
    
    CRITICAL FIX: Uses asyncio lock to prevent race condition where
    multiple concurrent requests create separate connection pools.
    """
    global _redis_client, _redis_pool, _init_lock
    
    if _redis_client is not None:
        return _redis_client
    
    # Lazy initialize lock
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    
    async with _init_lock:
        # Double-check pattern
        if _redis_client is not None:
            return _redis_client
        
        settings = get_settings()
        
        # Create connection pool with optimized settings for production
        if _redis_pool is None:
            _redis_pool = aioredis.ConnectionPool.from_url(
                settings.redis_url,
                max_connections=50,  # Support high concurrency
                decode_responses=True,
                socket_keepalive=True,
                socket_keepalive_options={},
                health_check_interval=30,
                retry_on_timeout=True,
                socket_timeout=5,  # CRITICAL: Add timeout
                socket_connect_timeout=5,
            )
        _redis_client = aioredis.Redis(connection_pool=_redis_pool)
    
    return _redis_client


async def close_redis() -> None:
    """Close Redis client AND connection pool on shutdown.
    
    CRITICAL FIX: Previously only closed client, leaving pool connections open.
    This caused TIME_WAIT accumulation during redeployments.
    """
    global _redis_client, _redis_pool
    
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
    
    if _redis_pool is not None:
        await _redis_pool.disconnect()
        _redis_pool = None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _key(session_id: str) -> str:
    return f"session:{session_id}"


def _meta_key(session_id: str) -> str:
    return f"session:{session_id}:meta"


def _registry_key() -> str:
    return "sessions:registry"


async def get_history(session_id: str) -> List[dict]:
    """Return the stored message list, newest-last. Empty list if missing.
    
    Supports both old format (JSON string) and new format (Redis list).
    Migrates from old to new format on read for backward compatibility.
    """
    try:
        r = await get_redis()
        settings = get_settings()
        
        # Try new format first (Redis list)
        msg_list = await r.lrange(_key(session_id), 0, -1)
        if msg_list:
            return [json.loads(msg) for msg in msg_list]
        
        # Fallback to old format (JSON string)
        raw = await r.get(_key(session_id))
        if raw:
            messages = json.loads(raw)
            # Migrate to new format (list)
            if messages:
                pipe = r.pipeline()
                pipe.delete(_key(session_id))
                for msg in messages:
                    pipe.rpush(_key(session_id), json.dumps(msg, ensure_ascii=False))
                pipe.expire(_key(session_id), settings.cache_ttl_seconds)
                await pipe.execute()
            return messages
        
        return []
    except Exception as exc:
        logger.warning("get_history failed for %s: %s", session_id, exc)
        return []


async def append_exchange(session_id: str, user_msg: str, assistant_msg: str) -> None:
    """Append one user+assistant exchange with timestamps and auto-title.
    
    Uses atomic Redis RPUSH/LTRIM operations to prevent read-modify-write
    race conditions under concurrent requests to the same session.
    """
    from datetime import datetime

    settings = get_settings()
    try:
        r = await get_redis()
        timestamp = datetime.utcnow().isoformat() + "Z"
        
        # Serialize messages
        user_entry = json.dumps({
            "role": "user",
            "content": _sanitize_user_input(user_msg),
            "timestamp": timestamp,
        }, ensure_ascii=False)
        
        assistant_entry = json.dumps({
            "role": "assistant",
            "content": assistant_msg,
            "timestamp": timestamp,
        }, ensure_ascii=False)
        
        # Atomic append with trim using Redis list
        max_msgs = settings.max_chat_history_exchanges * 2
        pipe = r.pipeline()
        pipe.rpush(_key(session_id), user_entry, assistant_entry)
        pipe.ltrim(_key(session_id), -max_msgs, -1)  # Keep only last N messages
        pipe.expire(_key(session_id), settings.cache_ttl_seconds)
        await pipe.execute()

        # Keep metadata operations best-effort so history persistence still succeeds.
        try:
            await _auto_title(session_id, user_msg, assistant_msg)
        except Exception as exc:
            logger.debug("_auto_title failed for %s: %s", session_id, exc)

        try:
            await _update_meta(session_id)
        except Exception as exc:
            logger.debug("_update_meta failed for %s: %s", session_id, exc)

        try:
            await _register_session(session_id)
        except Exception as exc:
            logger.debug("_register_session failed for %s: %s", session_id, exc)
        
    except Exception as exc:
        logger.error("append_exchange failed for %s: %s", session_id, exc)
        raise


async def get_session_meta(session_id: str) -> dict:
    """Get session metadata (title, created_at, updated_at, message_count)."""
    try:
        r = await get_redis()
        raw = await r.get(_meta_key(session_id))
        return json.loads(raw) if raw else {}
    except Exception as exc:
        logger.debug("get_session_meta failed for %s: %s", session_id, exc)
        return {}


async def set_session_meta(session_id: str, meta: dict) -> None:
    """Update session metadata."""
    import time
    try:
        r = await get_redis()
        # Merge with existing meta
        existing = await get_session_meta(session_id)
        existing.update(meta)
        
        # Set created_at if not exists
        if "created_at" not in existing:
            existing["created_at"] = time.time()
        
        await r.set(_meta_key(session_id), json.dumps(existing, ensure_ascii=False))
        await r.expire(_meta_key(session_id), get_settings().cache_ttl_seconds)
    except Exception as exc:
        logger.warning("set_session_meta failed for %s: %s", session_id, exc)


def _derive_title_from_message(user_msg: str, max_len: int = 80) -> str:
    """Build a stable session title from the first user message."""
    text = _sanitize_user_input(user_msg, max_length=max_len).replace("\n", " ").strip()
    text = " ".join(text.split())
    if not text:
        return "New Conversation"
    if len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


async def _auto_title(session_id: str, user_msg: str, assistant_msg: str) -> None:
    """Set title once on the first exchange if none exists."""
    # assistant_msg is intentionally accepted to preserve call compatibility.
    _ = assistant_msg
    try:
        meta = await get_session_meta(session_id)
        current_title = str(meta.get("title", "")).strip()
        if current_title and current_title != "New Conversation":
            return

        title = _derive_title_from_message(user_msg)
        await set_session_meta(session_id, {"title": title})
    except Exception as exc:
        logger.debug("_auto_title failed for %s: %s", session_id, exc)


async def _update_meta(session_id: str) -> None:
    """Refresh mutable session metadata after each appended exchange."""
    import time

    try:
        messages = await get_history(session_id)
        await set_session_meta(
            session_id,
            {
                "updated_at": time.time(),
                "message_count": len(messages),
            },
        )
    except Exception as exc:
        logger.debug("_update_meta failed for %s: %s", session_id, exc)


async def _register_session(session_id: str) -> None:
    """Add session ID to registry sorted by creation time."""
    import time
    try:
        r = await get_redis()
        # Check if already registered
        exists = await r.zscore(_registry_key(), session_id)
        if exists is None:
            await r.zadd(_registry_key(), {session_id: time.time()})
            await r.expire(_registry_key(), get_settings().cache_ttl_seconds)
    except Exception as exc:
        logger.debug("_register_session failed: %s", exc)


async def list_sessions(limit: int = 50, offset: int = 0) -> List[dict]:
    """
    List all sessions sorted by creation time (newest first).
    Returns list of {id, title, created_at, updated_at, message_count}.
    """
    try:
        r = await get_redis()
        
        # Get session IDs sorted by creation time (newest first)
        session_ids = await r.zrevrange(_registry_key(), offset, offset + limit - 1, withscores=True)
        
        sessions = []
        for session_id, created_at in session_ids:
            meta = await get_session_meta(session_id)
            messages = await get_history(session_id)
            
            sessions.append({
                "id": session_id,
                "title": meta.get("title", "New Conversation"),
                "created_at": meta.get("created_at", created_at),
                "updated_at": meta.get("updated_at"),
                "message_count": len(messages),
            })
        
        return sessions
    except Exception as exc:
        logger.warning("list_sessions failed: %s", exc)
        return []


async def clear_session(session_id: str) -> None:
    """Delete session and remove from registry."""
    try:
        r = await get_redis()
        pipe = r.pipeline()
        pipe.delete(_key(session_id))
        pipe.delete(_meta_key(session_id))
        pipe.zrem(_registry_key(), session_id)
        await pipe.execute()
    except Exception as exc:
        logger.warning("clear_session failed for %s: %s", session_id, exc)


def format_history_for_llm(messages: List[dict]) -> str:
    """
    Format the stored messages as a plain-text block for LLM prompts.
    Example output:
        Người dùng: ...
        Trợ lý: ...

    MEDIUM FIX: Add prompt injection defenses by escaping user input
    to prevent instruction injection attacks through conversation history.
    """
    if not messages:
        return "(trống)"
    lines: List[str] = []
    for m in messages:
        role = "Người dùng" if m["role"] == "user" else "Trợ lý"
        # CRITICAL: Sanitize user input to prevent prompt injection
        content = _sanitize_user_input(m["content"])
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _sanitize_user_input(text: str, max_length: int = 2000) -> str:
    """
    Sanitize user input to prevent prompt injection attacks.

    Defenses:
    - Truncate to max_length to prevent overflow
    - Remove or escape dangerous patterns ONLY at line-start positions
      (allows legitimate questions containing these terms in the middle)
    - Filters role impersonation and system prompt overrides

    Args:
        text: Raw user input
        max_length: Maximum allowed length

    Returns:
        Sanitized text safe for LLM prompts
    """
    import re
    
    if not text:
        return ""

    # Truncate to prevent overflow (leave room for "..." suffix)
    if len(text) > max_length:
        text = text[:max_length - 3] + "..."

    # FIX: Only filter role impersonation at line-start positions
    # This allows legitimate questions like "What does system: mean?"
    # but blocks injection attempts at the start of lines
    text = re.sub(
        r'^(system|assistant|user|hệ thống|trợ lý)\s*:',
        '[role filtered]:',
        text,
        flags=re.IGNORECASE | re.MULTILINE
    )

    # Only filter instruction overrides that span full lines
    override_patterns = [
        r'(?i)^(.{0,30})(bỏ qua hướng dẫn|ignore all? previous|ignore all? instructions|quên hết|hãy quên|forget all? previous|forget all? instructions)',
        r'(?i)^(.{0,30})(đừng làm theo|don\'t follow|do not follow|thay đổi hướng dẫn|change instructions)',
    ]
    
    for pattern in override_patterns:
        text = re.sub(pattern, r'[filtered]', text, flags=re.MULTILINE)

    return text
