from __future__ import annotations

from collections import Counter

from tests.eval.pipeline_v3_manifest import E2E_TRAJECTORIES, QUERY_UNDERSTANDING_CASES, RETRIEVAL_CASES


def test_pipeline_v3_manifest_has_the_required_balanced_contracts() -> None:
    assert len(QUERY_UNDERSTANDING_CASES) == 60
    assert {case["expected_route"] for case in QUERY_UNDERSTANDING_CASES} == {
        "chitchat", "legal_lookup", "legal_explain_compare", "case_assessment",
        "compliance_checklist", "research_web", "out_of_scope",
    }
    assert len(RETRIEVAL_CASES) == 60
    counts = Counter(str(case["id"]).split("_")[0] for case in RETRIEVAL_CASES)
    assert counts == {"explicit": 16, "multi": 10, "semantic": 20, "lexical": 8, "no": 6}
    assert len(E2E_TRAJECTORIES) == 40
