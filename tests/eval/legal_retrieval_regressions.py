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

from epr_agent.retrieval.retrieval import retrieve_legal


@dataclass
class RetrievalCase:
    case_id: str
    query: str
    expected_top_1: str | None = None
    expected_in_top_3: str | None = None
    expected_in_top_5: str | None = None


CASES = [
    RetrievalCase(
        case_id="pollutant_procedure_001",
        query="giờ tui nhập khẩu hàng hóa có chứa chất ô nhiễm khó phân hủy thì có cần làm thủ tục gì trước khi bán ra thị trường k",
        expected_top_1="Điều 40",
    ),
    RetrievalCase(
        case_id="article_77_001",
        query="Điều 77 quy định gì về trách nhiệm tái chế?",
        expected_top_1="Điều 77",
    ),
    RetrievalCase(
        case_id="recycling_rate_001",
        query="Tỷ lệ tái chế bắt buộc đối với sản phẩm bao bì được quy định ở đâu?",
        expected_top_1="Điều 78",
    ),
    RetrievalCase(
        case_id="battery_import_001",
        query="Công ty tôi nhập khẩu pin lithium từ nước ngoài, chúng tôi phải thực hiện nghĩa vụ gì?",
        expected_top_1="Phụ lục XXII",
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
