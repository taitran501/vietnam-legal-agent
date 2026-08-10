from __future__ import annotations

from tests.eval.legal_first_manifest import LEGAL_FIRST_CASES


def test_legal_first_manifest_contains_50_cases_and_no_faq_action():
    assert len(LEGAL_FIRST_CASES) == 50
    assert all("retrieve_faq" not in case["required_actions"] for case in LEGAL_FIRST_CASES)
    assert {case["expected_task_type"] for case in LEGAL_FIRST_CASES} >= {"chitchat", "legal_lookup", "assess_epr_obligation", "build_compliance_checklist"}
