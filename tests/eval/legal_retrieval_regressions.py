"""
Small regression suite for high-value legal retrieval cases.

Usage:
    python -m tests.eval.legal_retrieval_regressions
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vietnam_legal_agent.retrieval.retrieval import retrieve_legal


@dataclass
class RetrievalCase:
    case_id: str
    query: str
    expected_top_1: str | None = None
    expected_in_top_3: str | None = None
    expected_in_top_5: str | None = None


CASES = [
    RetrievalCase(
        case_id="labor_probation_001",
        query="Quy định thời gian thử việc tối đa là bao lâu theo Bộ luật Lao động?",
        expected_top_1="Điều 25",
    ),
    RetrievalCase(
        case_id="civil_interest_001",
        query="Mức trần lãi suất vay theo Điều 468 Bộ luật Dân sự là bao nhiêu?",
        expected_top_1="Điều 468",
    ),
    RetrievalCase(
        case_id="corporate_shareholders_001",
        query="Công ty cổ phần cần tối thiểu bao nhiêu cổ đông theo Điều 111?",
        expected_top_1="Điều 111",
    ),
    RetrievalCase(
        case_id="family_child_custody_001",
        query="Điều 81 Luật Hôn nhân và Gia đình quy định thế nào về người trực tiếp nuôi con?",
        expected_top_1="Điều 81",
    ),
    RetrievalCase(
        case_id="environmental_scope_001",
        query="Điều 1 Luật số 82/2015/QH13 điều chỉnh những vấn đề nào về tài nguyên và môi trường biển?",
        expected_top_1="Điều 1",
    ),
]


def main() -> None:
    passed = 0
    failed = 0

    for case in CASES:
        docs = retrieve_legal(case.query)
        top_3 = [str(doc.metadata.get("Dieu", "")) for doc in docs[:3]]
        top_5 = [str(doc.metadata.get("Dieu", "")) for doc in docs[:5]]

        ok = True
        reasons: list[str] = []

        if case.expected_top_1 and (not top_3 or case.expected_top_1 not in top_3[0]):
            ok = False
            reasons.append(f"expected top1={case.expected_top_1!r}, got={top_3[0] if top_3 else '(none)'}")

        if case.expected_in_top_3 and not any(case.expected_in_top_3 in label for label in top_3):
            ok = False
            reasons.append(f"expected in top3={case.expected_in_top_3!r}, got={top_3}")

        if case.expected_in_top_5 and not any(case.expected_in_top_5 in label for label in top_5):
            ok = False
            reasons.append(f"expected in top5={case.expected_in_top_5!r}, got={top_5}")

        if ok:
            passed += 1
            print(f"[PASS] {case.case_id}: {top_3}")
        else:
            failed += 1
            print(f"[FAIL] {case.case_id}: {', '.join(reasons)}")
            print(f"       top3={top_3}")

    total = passed + failed
    print(f"\nSummary: {passed}/{total} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
