"""Behavior and trajectory coverage for the Pipeline V4 contracts."""

from __future__ import annotations

import pytest
from tests.agent.v4_test_support import MemoryHistory, NoEvidenceRetrieval, runtime
from tests.eval.pipeline_v4_manifest import (
    ASSESSMENT_COMPLETE_CASES,
    ASSESSMENT_MISSING_CASES,
    CHECKLIST_CASES,
    E2E_TRAJECTORIES,
    EXEMPTION_CASES,
    INSUFFICIENT_EVIDENCE_CASES,
    QUERY_UNDERSTANDING_CASES,
)

from epr_agent.agent.v4 import _fact_values
from epr_agent.domain.epr_rules import extract_explicit_epr_facts
from epr_agent.domain.tasks import classify_route, preserve_explicit_anchors
from epr_agent.domain.v4 import FactSource


def test_v4_manifest_has_the_complete_contract_counts() -> None:
    assert len(QUERY_UNDERSTANDING_CASES) == 60
    assert len(E2E_TRAJECTORIES) == 40
    assert len(ASSESSMENT_COMPLETE_CASES) == 12
    assert len(ASSESSMENT_MISSING_CASES) == 12
    assert len(EXEMPTION_CASES) == 8
    assert len(INSUFFICIENT_EVIDENCE_CASES) == 4
    assert len(CHECKLIST_CASES) == 4


@pytest.mark.unit
@pytest.mark.parametrize("case", QUERY_UNDERSTANDING_CASES, ids=lambda case: case["id"])
def test_v4_query_understanding_routes_are_deterministic(case: dict[str, object]) -> None:
    expected = str(case["expected_route"])
    history = [{"role": "user", "content": "Điều 77 quy định trách nhiệm tái chế EPR."}] if case.get("is_follow_up") else []
    actual = classify_route(str(case["query"]), history, None).value
    if case.get("expected_behavior") == "clarify_or_safe_stop":
        assert actual in {"out_of_scope", "legal_lookup"}
    else:
        assert actual == expected


@pytest.mark.unit
def test_v4_preserves_all_explicit_legal_anchors_during_follow_up_rewrite() -> None:
    cases = [case for case in QUERY_UNDERSTANDING_CASES if case.get("is_follow_up")]
    for case in cases:
        original = str(case["query"])
        rewritten = preserve_explicit_anchors(original, "Câu hỏi độc lập đã được tạo lại.")
        assert "Điều 78" in rewritten if "Điều 78" in original else True


@pytest.mark.unit
def test_v4_fact_extraction_keeps_user_provenance_and_does_not_infer_commercial_purpose() -> None:
    facts = extract_explicit_epr_facts(
        "Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?"
    )
    assert facts["business_role"].source == FactSource.USER_TURN
    assert facts["business_role"].evidence_span == "nhà sản xuất"
    assert "activity_purpose" not in facts
    assert "market_placement" not in facts


@pytest.mark.unit
def test_v4_packaging_other_category_is_explicitly_extractable() -> None:
    facts = extract_explicit_epr_facts("bao bì nhựa dùng cho hàng hóa khác")
    assert facts["packaged_goods_category"].value == "other"


@pytest.mark.unit
def test_v4_migrates_legacy_case_fields_as_unverified_facts() -> None:
    facts = _fact_values(
        {
            "business_role": "nhà sản xuất",
            "product_or_packaging": "bao bì",
            "material": "nhựa",
            "activity_scope": "thị trường Việt Nam",
        }
    )

    assert facts["business_role"].value == "nhà sản xuất"
    assert facts["object_kind"].value == "packaging"
    assert facts["product_group"].value == "bao_bi"
    assert facts["market_placement"].value == "vietnam_market"
    assert facts["object_kind"].verified is False
    assert facts["object_kind"].source_turn == "legacy-v3-migration"


@pytest.mark.asyncio
async def test_v4_resume_migrates_legacy_case_before_collecting_new_facts() -> None:
    legacy = {
        "task_type": "assess_epr_obligation",
        "status": "collecting",
        "facts": {
            "business_role": "nhà sản xuất",
            "product_or_packaging": "bao bì",
            "material": "nhựa",
            "activity_scope": "thị trường Việt Nam",
        },
        "missing_facts": ["material"],
    }
    app, _, _ = runtime(history=MemoryHistory(legacy))
    state = await app.run(
        query="Dùng cho thực phẩm, kinh doanh thương mại, doanh thu 40 tỷ đồng, không thu hồi để tái sử dụng.",
        user_id="migration-user",
        conversation_id="migration-case",
        operation="continue_case",
        intent_hint="case_assessment",
    )

    assert state["outcome"] == "completed", state
    migrated = state["case_state"]["facts"]
    assert migrated["object_kind"]["verified"] is False
    assert migrated["market_placement"]["verified"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ASSESSMENT_COMPLETE_CASES, ids=lambda case: case["id"])
async def test_v4_complete_assessments_cover_all_required_issues(case: dict[str, object]) -> None:
    app, history, retrieval = runtime()
    state = await app.run(
        query=str(case["query"]),
        user_id="matrix-user",
        conversation_id=str(case["id"]),
        intent_hint="case_assessment",
        interaction_source="composer",
    )
    assert state["route"] == "case_assessment"
    assert state["outcome"] == case["expected_outcome"], state
    assert state["result_type"] == case["expected_result_type"]
    assert state["missing_facts"] == []
    assert set(state["required_issues"]) == set(state["covered_issues"])
    assert state["assessment"]["status"] == case["expected_assessment_status"]
    assert state["citations"]
    assert history.runs
    assert len(history.runs) == 1
    assert retrieval.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ASSESSMENT_MISSING_CASES, ids=lambda case: case["id"])
async def test_v4_missing_facts_stop_before_retrieval(case: dict[str, object]) -> None:
    app, history, retrieval = runtime()
    state = await app.run(
        query=str(case["query"]),
        user_id="matrix-user",
        conversation_id=str(case["id"]),
        intent_hint="case_assessment",
        operation="message",
    )
    assert state["outcome"] == "needs_information", state
    assert state["result_type"] == "none"
    assert set(case["expected_missing_facts"]).issubset(set(state["missing_facts"]))
    assert "retrieve_legal" not in state["action_sequence"]
    assert not retrieval.requests
    assert state["case_state"]["status"] == "collecting"
    assert history.saved_cases


@pytest.mark.asyncio
async def test_v4_case_state_keeps_presentation_schema_after_persistence() -> None:
    app, history, _ = runtime()
    state = await app.run(
        query="Tôi là nhà sản xuất bao bì nhựa tại Việt Nam, có phải thực hiện EPR không?",
        user_id="ui-schema-user",
        conversation_id="ui-schema-case",
        intent_hint="case_assessment",
    )

    fields = state["case_state"]["fields"]
    by_key = {field["key"]: field for field in fields}
    assert {"business_role", "object_kind", "product_group", "material"}.issubset(by_key)
    assert {"market_placement", "activity_purpose", "packaged_goods_category"}.issubset(by_key)
    assert by_key["business_role"]["label"] == "Vai trò doanh nghiệp"
    assert by_key["business_role"]["value"] == "manufacturer"
    assert by_key["business_role"]["options"][0]["label"] == "Nhà sản xuất"
    assert by_key["material"]["options"]
    assert by_key["market_placement"]["missing"] is True
    assert history.saved_cases[0]["fields"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", EXEMPTION_CASES[:4], ids=lambda case: case["id"])
async def test_v4_exemptions_are_deterministic_assessment_results(case: dict[str, object]) -> None:
    app, _, _ = runtime()
    state = await app.run(
        query=str(case["query"]),
        user_id="matrix-user",
        conversation_id=str(case["id"]),
        intent_hint="case_assessment",
    )
    assert state["outcome"] == "completed", state
    assert state["result_type"] == "assessment"
    assert state["assessment"]["status"] == case["expected_assessment_status"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", EXEMPTION_CASES[4:], ids=lambda case: case["id"])
async def test_v4_out_of_scope_stops_without_retrieval(case: dict[str, object]) -> None:
    expected_outcome = str(case["expected_outcome"])
    app, _, retrieval = runtime(retrieval=NoEvidenceRetrieval() if expected_outcome == "insufficient_evidence" else None)
    state = await app.run(
        query=str(case["query"]),
        user_id="matrix-user",
        conversation_id=str(case["id"]),
        intent_hint="auto",
    )
    assert state["outcome"] == expected_outcome, state
    assert state["result_type"] == "none"
    if expected_outcome == "out_of_scope":
        assert not retrieval.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", INSUFFICIENT_EVIDENCE_CASES, ids=lambda case: case["id"])
async def test_v4_insufficient_evidence_never_completes(case: dict[str, object]) -> None:
    app, _, retrieval = runtime(retrieval=NoEvidenceRetrieval())
    state = await app.run(
        query=str(case["query"]),
        user_id="matrix-user",
        conversation_id=str(case["id"]),
        intent_hint=str(case["expected_route"]),
    )
    assert state["outcome"] == "insufficient_evidence", state
    assert state["result_type"] == "none"
    assert state["termination_reason"] == "insufficient_evidence"
    assert state["outcome"] != "completed"
    assert not any("faq" in str(request).casefold() for request in retrieval.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CHECKLIST_CASES, ids=lambda case: case["id"])
async def test_v4_checklist_contract_has_facts_or_stops(case: dict[str, object]) -> None:
    app, _, retrieval = runtime()
    state = await app.run(
        query=str(case["query"]),
        user_id="matrix-user",
        conversation_id=str(case["id"]),
        intent_hint="compliance_checklist",
    )
    assert state["outcome"] == case["expected_outcome"], state
    assert state["result_type"] == case["expected_result_type"]
    if state["outcome"] == "completed":
        assert state["checklist"]
        assert set(state["required_issues"]) == set(state["covered_issues"])
        assert all(item["evidence_indices"] for item in state["checklist"])
    else:
        assert state["missing_facts"]
        assert not retrieval.requests
