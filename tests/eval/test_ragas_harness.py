import json
from pathlib import Path
import pytest

from epr_agent.eval.ragas_evaluator import (
    compute_anchor_accuracy,
    compute_context_recall,
)


def test_compute_context_recall():
    docs = [
        {"page_content": "Theo quy định tại Điều 25 Bộ luật Lao động 2019 về thời gian thử việc..."},
        {"page_content": "Điều 98 quy định về tiền lương làm thêm giờ..."},
    ]
    expected = ["Điều 25", "Bộ luật Lao động 2019"]
    recall, found = compute_context_recall(docs, expected)
    assert recall == 1.0
    assert len(found) == 2

    # Partial match
    expected_partial = ["Điều 25", "Điều 41", "Điều 98"]
    recall_part, found_part = compute_context_recall(docs, expected_partial)
    assert recall_part == pytest.approx(0.667, rel=1e-2)
    assert "Điều 25" in found_part
    assert "Điều 98" in found_part


def test_compute_anchor_accuracy():
    answer = "Theo quy định tại Điều 41 Bộ luật Lao động 2019, người sử dụng lao động phải nhận lại làm việc..."
    expected = ["Điều 41", "Bộ luật Lao động 2019"]
    acc, cited = compute_anchor_accuracy(answer, expected)
    assert acc == 1.0
    assert len(cited) == 2


def test_golden_benchmark_file_structure():
    benchmark_path = Path("data/eval/golden_legal_benchmark.json")
    assert benchmark_path.exists()

    with open(benchmark_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "cases" in data
    assert len(data["cases"]) >= 20
    for case in data["cases"]:
        assert "id" in case
        assert "query" in case
        assert "expected_anchors" in case
        assert "ground_truth_summary" in case
