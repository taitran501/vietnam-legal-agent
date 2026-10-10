"""Cross-domain checks for generic routing, evidence, and case persistence."""

from __future__ import annotations

import pytest
from tests.agent.v4_test_support import NoEvidenceRetrieval, runtime

from vietnam_legal_agent.agent.v4 import _fact_values, _hydrate_persisted_case
from vietnam_legal_agent.domain.models import TaskType
from vietnam_legal_agent.domain.routes import RouteType
from vietnam_legal_agent.domain.tasks import (
    ExtractedFacts,
    TaskUnderstanding,
    classify_route,
    detect_legal_domain,
    preserve_explicit_anchors,
)


@pytest.mark.parametrize(
    ("query", "route"),
    [
        ("Xin chào, bạn hỗ trợ được gì?", RouteType.CHITCHAT),
        ("Công ty cổ phần cần tối thiểu bao nhiêu cổ đông?", RouteType.LEGAL_LOOKUP),
        ("Tôi bị công ty chậm trả lương hai tháng, tôi có quyền gì?", RouteType.CASE_ASSESSMENT),
        ("Chủ nhà giữ tiền cọc sau khi tôi trả nhà, tôi nên làm gì?", RouteType.CASE_ASSESSMENT),
        ("Không đội mũ bảo hiểm khi ngồi sau xe máy bị phạt thế nào?", RouteType.LEGAL_LOOKUP),
        ("Điều 1 Luật số 82/2015/QH13 điều chỉnh những vấn đề nào về môi trường biển?", RouteType.LEGAL_LOOKUP),
        ("Hướng dẫn cách nấu phở bò Nam Định?", RouteType.OUT_OF_SCOPE),
    ],
)
def test_route_matrix_is_balanced_across_ordinary_legal_topics(query: str, route: RouteType) -> None:
    assert classify_route(query, [], None) is route


def test_environmental_topic_is_a_normal_legal_domain_without_intake_slots() -> None:
    query = "Điều 1 Luật số 82/2015/QH13 điều chỉnh những vấn đề nào về môi trường biển?"

    assert detect_legal_domain(query) == "environmental"
    understanding = TaskUnderstanding(
        task_type="legal_lookup",
        route=RouteType.LEGAL_LOOKUP,
        standalone_query=query,
        missing_facts=["product_group", "material"],
    )
    assert understanding.missing_facts == []


def test_structured_understanding_keeps_user_facts_as_generic_values() -> None:
    result = TaskUnderstanding(
        task_type="case_assessment",
        route=RouteType.CASE_ASSESSMENT,
        standalone_query="Tôi bị chậm trả lương.",
        facts=ExtractedFacts(values={"employment_issue": "chậm trả lương", "duration": "hai tháng"}),
        missing_facts=["contract_date"],
    )

    assert result.task_type is TaskType.CASE_ASSESSMENT
    assert result.facts.values == {"employment_issue": "chậm trả lương", "duration": "hai tháng"}
    assert result.missing_facts == []


def test_legacy_facts_are_preserved_without_domain_specific_reinterpretation() -> None:
    facts = _fact_values(
        {
            "employment_issue": "chậm trả lương",
            "duration": "hai tháng",
            "user_note": "đã gửi yêu cầu qua email",
        }
    )

    assert set(facts) == {"employment_issue", "duration", "user_note"}
    assert all(fact.verified is False for fact in facts.values())
    assert facts["duration"].source_turn == "legacy-v3-migration"


def test_unknown_legacy_task_is_normalized_to_generic_case_state() -> None:
    case = _hydrate_persisted_case(
        {
            "task_type": "retired_specialized_workflow",
            "facts": {"employment_issue": "chậm trả lương"},
            "fields": [{"key": "retired-field"}],
            "missing_facts": ["retired-field"],
        }
    )

    assert case is not None
    assert case["task_type"] == TaskType.CASE_ASSESSMENT.value
    assert "legal_domain" not in case
    assert case["facts"] == {"employment_issue": "chậm trả lương"}
    assert "fields" not in case
    assert "form_version" not in case
    assert "required_count" not in case


def test_explicit_legal_anchors_survive_follow_up_rewrite() -> None:
    original = "Điều 94 Bộ luật Lao động quy định gì?"

    rewritten = preserve_explicit_anchors(original, "Quy định về trả lương là gì?")

    assert "Điều 94" in rewritten


@pytest.mark.asyncio
async def test_short_labor_case_retrieves_without_collecting_a_fixed_form() -> None:
    app, history, retrieval = runtime()
    state = await app.run(
        query="Tôi bị công ty chậm trả lương, tôi có quyền gì?",
        user_id="general-user",
        conversation_id="labor-short-case",
    )

    assert state["outcome"] == "completed", state
    assert state["route"] == RouteType.LEGAL_LOOKUP.value
    assert state["termination_reason"] == "answer_complete"
    assert state["missing_facts"] == []
    assert state["case_state"] is None or "required_count" not in state["case_state"]
    assert retrieval.requests
    assert history.runs


@pytest.mark.asyncio
async def test_environmental_question_uses_the_same_evidence_workflow() -> None:
    app, _, retrieval = runtime()
    state = await app.run(
        query="Điều 1 Luật số 82/2015/QH13 điều chỉnh những vấn đề nào về môi trường biển?",
        user_id="general-user",
        conversation_id="environmental-lookup",
        intent_hint="auto",
    )

    assert state["outcome"] == "completed", state
    assert state["route"] == RouteType.LEGAL_LOOKUP.value
    assert state["case_state"] is None
    assert state["missing_facts"] == []
    assert retrieval.requests


@pytest.mark.asyncio
async def test_unavailable_corpus_stops_without_generating_unsupported_legal_answer() -> None:
    app, _, retrieval = runtime(retrieval=NoEvidenceRetrieval())
    state = await app.run(
        query="Công ty cổ phần cần tối thiểu bao nhiêu cổ đông?",
        user_id="general-user",
        conversation_id="no-evidence",
        intent_hint="legal_lookup",
    )

    assert state["outcome"] == "insufficient_evidence"
    assert state["termination_reason"] == "insufficient_evidence"
    assert state["result_type"] == "none"
    assert retrieval.requests


@pytest.mark.asyncio
async def test_checklist_is_generic_and_evidence_linked() -> None:
    app, _, retrieval = runtime()
    state = await app.run(
        query="Lập checklist giấy tờ cần bàn giao khi nghỉ việc.",
        user_id="general-user",
        conversation_id="general-checklist",
        intent_hint="compliance_checklist",
    )

    assert state["outcome"] == "completed", state
    assert state["route"] == RouteType.LEGAL_LOOKUP.value
    assert state["task_type"] == TaskType.LEGAL_LOOKUP.value
    assert state["checklist"] == []
    assert state["citations"]
    assert retrieval.requests
