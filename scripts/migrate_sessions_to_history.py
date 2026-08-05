"""Migrate legacy Redis session history into persistent conversation store.

Usage:
    python -m scripts.migrate_sessions_to_history

Notes:
- This script is idempotent enough for practical migration runs.
- It uses a dedicated migration user_id to avoid ownership conflicts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.history import init_history_store, ensure_conversation, append_exchange
from backend.memory import session_store

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MIGRATION_USER_ID = "legacy-migrated"


def _pair_messages(messages: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Pair consecutive user->assistant messages into exchanges."""
    pairs: list[tuple[str, str]] = []
    pending_user: str | None = None

    for msg in messages:
        role = msg.get("role")
        content = str(msg.get("content", ""))

        if role == "user":
            pending_user = content
        elif role == "assistant" and pending_user is not None:
            pairs.append((pending_user, content))
            pending_user = None

    return pairs


async def migrate() -> None:
    await init_history_store()

    redis = await session_store.get_redis()
    session_ids = await redis.zrevrange("sessions:registry", 0, -1)

    migrated_sessions = 0
    migrated_exchanges = 0

    for sid in session_ids:
        messages = await session_store.get_history(sid)
        if not messages:
            continue

        pairs = _pair_messages(messages)
        if not pairs:
            continue

        await ensure_conversation(
            user_id=MIGRATION_USER_ID,
            conversation_id=sid,
            title_seed=pairs[0][0],
        )

        for user_msg, assistant_msg in pairs:
            await append_exchange(
                user_id=MIGRATION_USER_ID,
                conversation_id=sid,
                user_msg=user_msg,
                assistant_msg=assistant_msg,
                model="legacy-import",
                metadata={"source": "redis-session-migration"},
            )
            migrated_exchanges += 1

        migrated_sessions += 1

    logger.info(
        "Migration complete: sessions=%d, exchanges=%d",
        migrated_sessions,
        migrated_exchanges,
    )


if __name__ == "__main__":
    asyncio.run(migrate())
