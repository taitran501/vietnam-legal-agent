"""Request, persistence and ownership contracts for V4."""

from __future__ import annotations

import pytest
from backend.api.schemas import ChatRequest
from pydantic import ValidationError


def test_v4_request_accepts_intent_source_and_case_patch_without_changing_legacy_shape() -> None:
    request = ChatRequest(
        query="  Tôi là nhà sản xuất bao bì nhựa.  ",
        conversation_id="conversation-v4",
        intent_hint="case_assessment",
        interaction_source="quick_action",
        case_patch={"market_placement": "  vietnam_market  ", "empty": "   "},
    )

    assert request.query == "Tôi là nhà sản xuất bao bì nhựa."
    assert request.operation == "message"
    assert request.intent_hint == "case_assessment"
    assert request.interaction_source == "quick_action"
    assert request.case_patch == {"market_placement": "vietnam_market"}


def test_v4_request_rejects_invalid_operation_and_identifier() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(query="Điều 77", operation="not-an-operation")
    with pytest.raises(ValidationError):
        ChatRequest(query="Điều 77", conversation_id="conversation/with/slash")
    with pytest.raises(ValidationError):
        ChatRequest(query="Điều 77", session_id="anonymous")


def test_continue_case_can_be_patch_only_for_legacy_clients() -> None:
    request = ChatRequest(
        operation="continue_case",
        conversation_id="conversation-v4",
        case_patch={"activity_purpose": "kinh doanh thương mại"},
    )

    assert request.query == ""
    assert request.operation == "continue_case"
    assert request.case_patch["activity_purpose"] == "kinh doanh thương mại"


def test_typed_fact_updates_validate_confirmation_status() -> None:
    request = ChatRequest(
        operation="continue_case",
        conversation_id="conversation-v4",
        fact_updates={"annual_revenue_vnd": {"value": "30000000000", "confirmation_status": "user_confirmed"}},
    )
    assert request.fact_updates["annual_revenue_vnd"].confirmation_status == "user_confirmed"
    with pytest.raises(ValidationError):
        ChatRequest(
            operation="continue_case",
            conversation_id="conversation-v4",
            fact_updates={"annual_revenue_vnd": {"value": "30000000000", "confirmation_status": "guessed"}},
        )
