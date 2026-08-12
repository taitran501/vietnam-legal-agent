"""Regression tests for durable principals, message IDs, and feedback ownership."""

from __future__ import annotations

from pathlib import Path

import pytest
from backend.api.principal import credential_hash, oidc_user_id, principal_from_service_token

from epr_agent.infra.persistence import PersistenceStore, sqlite_database_url


def test_oidc_owner_id_is_stable_but_issuer_and_subject_scoped() -> None:
    first = oidc_user_id("https://sso.example", "user-123")
    assert first == oidc_user_id("https://sso.example/", "user-123")
    assert first.startswith("oidc:")
    assert first != oidc_user_id("https://other.example", "user-123")
    assert first != oidc_user_id("https://sso.example", "user-456")


def test_service_token_lookup_uses_hash_and_preserves_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    token = "integration-secret"
    settings = type(
        "Settings",
        (),
        {"service_token_definitions": f"runner:{credential_hash(token)}:chat|feedback:quality_admin"},
    )()
    monkeypatch.setattr("backend.api.principal.get_settings", lambda: settings)

    principal = principal_from_service_token(token)

    assert principal is not None
    assert principal.id == "service:runner"
    assert principal.has_scope("chat")
    assert principal.has_scope("feedback")
    assert principal.has_role("quality_admin")
    assert principal_from_service_token("wrong-secret") is None


@pytest.mark.asyncio
async def test_feedback_is_owned_by_user_and_updates_durably(tmp_path: Path) -> None:
    store = PersistenceStore(sqlite_database_url(str(tmp_path / "feedback.sqlite3")))
    await store.initialize()
    try:
        await store.ensure_conversation("owner-a", "conversation-a", "A")
        message_id = await store.append_exchange(
            "owner-a",
            "conversation-a",
            "Câu hỏi",
            "Câu trả lời",
            {"sources": [{"source_id": "law-77"}]},
        )
        assert message_id

        saved = await store.save_feedback("owner-a", "conversation-a", message_id, 2, "Có căn cứ")
        assert saved and saved["rating"] == 2
        updated = await store.save_feedback("owner-a", "conversation-a", message_id, 1, "Cần rõ hơn")
        assert updated and updated["rating"] == 1
        assert await store.save_feedback("owner-b", "conversation-a", message_id, 2) is None

        history = await store.get_recent_history("owner-a", "conversation-a", 10)
        assistant = history[-1]
        assert assistant["metadata"]["feedback"] == {"rating": 1, "comment": "Cần rõ hơn"}
        assert (await store.feedback_stats()) == {
            "total_up": 0,
            "total_down": 1,
            "total_feedback": 1,
            "satisfaction_rate": 0.0,
        }
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_delete_conversation_removes_feedback_and_cross_user_history(tmp_path: Path) -> None:
    store = PersistenceStore(sqlite_database_url(str(tmp_path / "delete-feedback.sqlite3")))
    await store.initialize()
    try:
        await store.ensure_conversation("owner-a", "conversation-a")
        message_id = await store.append_exchange("owner-a", "conversation-a", "Q", "A")
        await store.save_feedback("owner-a", "conversation-a", message_id, 2)

        assert await store.get_recent_history("owner-b", "conversation-a", 10) == []
        assert await store.delete_conversation("owner-a", "conversation-a") is True
        assert (await store.feedback_stats())["total_feedback"] == 0
        assert await store.delete_conversation("owner-a", "conversation-a") is False
    finally:
        await store.close()
