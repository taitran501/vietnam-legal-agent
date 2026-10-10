"""Request, persistence and ownership contracts for V4."""

from __future__ import annotations

import pytest
from backend.api.schemas import ChatRequest
from pydantic import ValidationError


def test_v4_request_accepts_normal_chat_intent_without_form_payloads() -> None:
    request = ChatRequest(
        query="  Tôi bị công ty chậm trả lương.  ",
        conversation_id="conversation-v4",
        intent_hint="case_assessment",
        interaction_source="quick_action",
    )

    assert request.query == "Tôi bị công ty chậm trả lương."
    assert request.operation == "message"
    assert request.intent_hint == "case_assessment"
    assert request.interaction_source == "quick_action"
    assert "case_patch" not in ChatRequest.model_fields
    assert "fact_updates" not in ChatRequest.model_fields


def test_v4_request_rejects_removed_form_operation_and_invalid_identifier() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(query="Điều 25", operation="continue_case")
    with pytest.raises(ValidationError):
        ChatRequest(query="Điều 25", conversation_id="conversation/with/slash")
    with pytest.raises(ValidationError):
        ChatRequest(query="Điều 25", session_id="anonymous")
