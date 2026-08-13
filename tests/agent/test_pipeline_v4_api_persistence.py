from __future__ import annotations

import pytest
from backend.api.schemas import ChatRequest
from backend.config import get_settings
from pydantic import ValidationError

from epr_agent.agent.graph import default_dependencies
from epr_agent.infra.persistence import PersistenceStore, sqlite_database_url


def test_turn_request_keeps_legacy_message_contract_and_allows_continue_case():
    legacy = ChatRequest(query="Điều 77 quy định gì?")
    assert legacy.operation == "message"
    assert legacy.intent_hint == "auto"
    continued = ChatRequest(operation="continue_case", conversation_id="case-1", case_patch={"market_placement": "vietnam_market"})
    assert continued.query == ""
    assert continued.case_patch["market_placement"] == "vietnam_market"
    with pytest.raises(ValidationError):
        ChatRequest(query="", operation="message")
    replay = ChatRequest(operation="regenerate", target_assistant_message_id=42)
    assert replay.query == ""
    with pytest.raises(ValidationError):
        ChatRequest(operation="retry")
    with pytest.raises(ValidationError):
        ChatRequest(query="Điều 77", target_assistant_message_id=42)


def test_v4_dependency_scope_includes_the_audited_appendix_in_corpus_identity(monkeypatch):
    """A V4 answer must not carry V3's corpus digest in its metadata."""

    from scripts import canonical_corpus

    captured: dict[str, object] = {}

    def capture_digest(**kwargs):
        captured.update(kwargs)
        return "v4-corpus-digest"

    monkeypatch.setenv("AGENT_PIPELINE_VERSION", "pipeline-v4")
    monkeypatch.setattr(canonical_corpus, "corpus_sha256", capture_digest)
    get_settings.cache_clear()
    try:
        deps = default_dependencies()
        assert captured["appendix_path"] == get_settings().appendix_xxii_data_path
        assert deps.corpus and deps.corpus.corpus_sha == "v4-corpus-digest"
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
                "task_type": "assess_epr_obligation",
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
