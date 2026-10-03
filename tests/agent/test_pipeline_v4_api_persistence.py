from __future__ import annotations

import hashlib
import json

import pytest
from backend.api.schemas import ChatRequest
from pydantic import ValidationError

from vietnam_legal_agent.agent.graph import default_dependencies
from vietnam_legal_agent.config import get_settings
from vietnam_legal_agent.infra.persistence import PersistenceStore, sqlite_database_url


def test_turn_request_keeps_ordinary_message_and_replay_contract():
    legacy = ChatRequest(query="Điều 36 Bộ luật Lao động quy định gì?")
    assert legacy.operation == "message"
    assert legacy.intent_hint == "auto"
    with pytest.raises(ValidationError):
        ChatRequest(operation="continue_case", conversation_id="case-1")
    with pytest.raises(ValidationError):
        ChatRequest(query="", operation="message")
    replay = ChatRequest(operation="regenerate", target_assistant_message_id=42)
    assert replay.query == ""
    with pytest.raises(ValidationError):
        ChatRequest(operation="retry")
    with pytest.raises(ValidationError):
        ChatRequest(query="Điều 36", target_assistant_message_id=42)


def test_v4_dependency_scope_uses_the_locked_multi_domain_corpus_hash(monkeypatch, tmp_path):
    manifest_path = tmp_path / "universal-corpus.json"
    manifest_path.write_text(json.dumps({"corpus_id": "vietnamese_law", "corpus_version": "test-v1"}), encoding="utf-8")
    expected_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    monkeypatch.setenv("UNIVERSAL_CORPUS_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("AGENT_PIPELINE_VERSION", "pipeline-v4")
    monkeypatch.setenv("ENABLE_UNIVERSAL_RETRIEVAL", "true")
    get_settings.cache_clear()
    try:
        deps = default_dependencies()
        assert deps.corpus and deps.corpus.corpus_id == "vietnamese_law"
        assert deps.corpus.corpus_sha == expected_digest
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_v4_case_payload_and_first_turn_title_are_durable(tmp_path):
    store = PersistenceStore(sqlite_database_url(str(tmp_path / "v4.sqlite3")))
    await store.initialize()
    try:
        await store.ensure_conversation("owner", "conversation-v4")
        await store.save_case(
            "owner",
            "conversation-v4",
            {
                "schema_version": "v4",
                "task_type": "case_assessment",
                "status": "collecting",
                "facts": {"business_role": {"value": "manufacturer", "source": "user_turn"}},
                "missing_facts": ["market_placement"],
                "issue_states": {"actor": {"status": "supported"}},
                "as_of_date": "2026-08-10",
            },
        )
        await store.append_exchange("owner", "conversation-v4", "Câu hỏi đầu tiên", "Cần bổ sung phạm vi thị trường.")
        case = await store.get_case("owner", "conversation-v4")
        conversation = await store.get_conversation("owner", "conversation-v4")
        assert case and case["schema_version"] == "v4"
        assert case["issue_states"]["actor"]["status"] == "supported"
        assert conversation and conversation["title"] == "Câu hỏi đầu tiên"
    finally:
        await store.close()
