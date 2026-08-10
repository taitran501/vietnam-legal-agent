from __future__ import annotations

import pytest
from tests.eval.pipeline_v3_manifest import QUERY_UNDERSTANDING_CASES

from epr_agent.domain.tasks import deterministic_task_understanding, preserve_explicit_anchors


@pytest.mark.parametrize("case", QUERY_UNDERSTANDING_CASES, ids=[str(case["id"]) for case in QUERY_UNDERSTANDING_CASES])
def test_deterministic_query_plan_covers_the_v3_route_contract(case: dict[str, object]) -> None:
    history = [{"role": "user", "content": "Tôi cần tra cứu EPR về bao bì."}] if case.get("is_follow_up") else []
    understanding = deterministic_task_understanding(str(case["query"]), history, None)

    assert understanding.route.value == case["expected_route"]
    if any(f"Điều {number}" in str(case["query"]) for number in range(1, 1000)):
        assert understanding.explicit_anchors


def test_explicit_anchors_survive_a_bad_follow_up_rewrite() -> None:
    rewritten = preserve_explicit_anchors("So sánh Điều 77 và Điều 78", "Hãy so sánh hai điều đó")

    assert "Điều 77" in rewritten
    assert "Điều 78" in rewritten


def test_document_clause_and_point_survive_follow_up_rewrite() -> None:
    rewritten = preserve_explicit_anchors(
        "Nghị định 08/2022/NĐ-CP Điều 77 Khoản 2 Điểm a quy định gì?",
        "Còn trường hợp đó thì sao?",
    )

    assert "08/2022/NĐ-CP" in rewritten
    assert "Điều 77" in rewritten
    assert "Khoản 2" in rewritten
    assert "Điểm a" in rewritten
