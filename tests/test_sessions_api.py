"""Integration tests for sessions API with persistent history enabled."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.testclient import TestClient

from backend.api.routes import sessions as sessions_routes
from backend.history import store


class _InjectUserMiddleware(BaseHTTPMiddleware):
    """Inject test user identity from request header into request state."""

    async def dispatch(self, request: Request, call_next):
        request.state.api_key_hash = request.headers.get("x-test-user", "user-default")
        return await call_next(request)


@pytest.fixture
def persistent_history_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Enable persistent history and isolate SQLite DB per test."""
    db_path = tmp_path / "history_api.sqlite3"

    monkeypatch.setattr(store, "_db_path", lambda: db_path)
    monkeypatch.setattr(
        sessions_routes,
        "get_settings",
        lambda: SimpleNamespace(history_enabled=True),
    )

    async def _legacy_get_history(_session_id: str):
        return []

    async def _legacy_clear_session(_session_id: str):
        return None

    monkeypatch.setattr(sessions_routes.session_store, "get_history", _legacy_get_history)
    monkeypatch.setattr(sessions_routes.session_store, "clear_session", _legacy_clear_session)

    asyncio.run(store.init_history_store())
    return db_path


@pytest.fixture
def app(persistent_history_env: Path):
    test_app = FastAPI()
    test_app.add_middleware(_InjectUserMiddleware)
    test_app.include_router(sessions_routes.router, prefix="/api/v1")
    return test_app


@pytest.fixture
def client(app: FastAPI):
    return TestClient(app)


@pytest.mark.integration
def test_sessions_crud_archive_pin_messages_and_delete_flow(client: TestClient):
    headers = {"x-test-user": "user-a"}

    create_resp = client.post(
        "/api/v1/sessions",
        headers=headers,
        json={"title": "First chat", "session_id": "conv-api-1"},
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["id"] == "conv-api-1"
    assert created["title"] == "First chat"
    assert created["archived"] is False
    assert created["pinned"] is False

    list_resp = client.get("/api/v1/sessions", headers=headers)
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert len(listed) == 1
    assert listed[0]["id"] == "conv-api-1"

    get_resp = client.get("/api/v1/sessions/conv-api-1", headers=headers)
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["id"] == "conv-api-1"
    assert detail["message_count"] == 0

    rename_resp = client.patch(
        "/api/v1/sessions/conv-api-1",
        headers=headers,
        json={"title": "Renamed chat"},
    )
    assert rename_resp.status_code == 200
    assert rename_resp.json()["title"] == "Renamed chat"

    pin_resp = client.patch(
        "/api/v1/sessions/conv-api-1/pin",
        headers=headers,
        json={"pinned": True},
    )
    assert pin_resp.status_code == 200
    assert pin_resp.json()["pinned"] is True

    archive_resp = client.patch(
        "/api/v1/sessions/conv-api-1/archive",
        headers=headers,
        json={"archived": True},
    )
    assert archive_resp.status_code == 200
    assert archive_resp.json()["archived"] is True

    hidden_list_resp = client.get("/api/v1/sessions", headers=headers)
    assert hidden_list_resp.status_code == 200
    assert hidden_list_resp.json() == []

    unarchive_resp = client.patch(
        "/api/v1/sessions/conv-api-1/archive",
        headers=headers,
        json={"archived": False},
    )
    assert unarchive_resp.status_code == 200
    assert unarchive_resp.json()["archived"] is False

    asyncio.run(
        store.append_exchange(
            user_id="user-a",
            conversation_id="conv-api-1",
            user_msg="Q1",
            assistant_msg="A1",
        )
    )
    asyncio.run(
        store.append_exchange(
            user_id="user-a",
            conversation_id="conv-api-1",
            user_msg="Q2",
            assistant_msg="A2",
        )
    )
    asyncio.run(
        store.append_exchange(
            user_id="user-a",
            conversation_id="conv-api-1",
            user_msg="Q3",
            assistant_msg="A3",
        )
    )

    page1_resp = client.get(
        "/api/v1/sessions/conv-api-1/messages",
        headers=headers,
        params={"limit": 4},
    )
    assert page1_resp.status_code == 200
    page1 = page1_resp.json()
    assert page1["conversation_id"] == "conv-api-1"
    assert len(page1["messages"]) == 4
    assert page1["next_cursor"] is not None

    page2_resp = client.get(
        "/api/v1/sessions/conv-api-1/messages",
        headers=headers,
        params={"limit": 4, "cursor": page1["next_cursor"]},
    )
    assert page2_resp.status_code == 200
    page2 = page2_resp.json()
    assert len(page2["messages"]) == 2
    assert page2["next_cursor"] is None

    delete_resp = client.delete("/api/v1/sessions/conv-api-1", headers=headers)
    assert delete_resp.status_code == 200

    get_after_delete_resp = client.get("/api/v1/sessions/conv-api-1", headers=headers)
    assert get_after_delete_resp.status_code == 404


@pytest.mark.integration
def test_sessions_ownership_enforced_between_users(client: TestClient):
    owner_headers = {"x-test-user": "owner-user"}
    other_headers = {"x-test-user": "other-user"}

    create_resp = client.post(
        "/api/v1/sessions",
        headers=owner_headers,
        json={"title": "Private conversation", "session_id": "conv-owned"},
    )
    assert create_resp.status_code == 200

    get_for_other = client.get("/api/v1/sessions/conv-owned", headers=other_headers)
    assert get_for_other.status_code == 404

    pin_for_other = client.patch(
        "/api/v1/sessions/conv-owned/pin",
        headers=other_headers,
        json={"pinned": True},
    )
    assert pin_for_other.status_code == 404

    archive_for_other = client.patch(
        "/api/v1/sessions/conv-owned/archive",
        headers=other_headers,
        json={"archived": True},
    )
    assert archive_for_other.status_code == 404

    delete_for_other = client.delete("/api/v1/sessions/conv-owned", headers=other_headers)
    assert delete_for_other.status_code == 404

    owner_still_can_read = client.get("/api/v1/sessions/conv-owned", headers=owner_headers)
    assert owner_still_can_read.status_code == 200
