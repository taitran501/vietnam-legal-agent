from pathlib import Path

import pytest
from scripts.retrieval_benchmark import corpus_manifest, promotion_decision, select_live_cases


def test_corpus_manifest_is_deterministic_and_counts_committed_sources():
    root = Path(__file__).resolve().parents[1]
    first = corpus_manifest(root / "data" / "law.json", root / "data" / "faq.json")
    second = corpus_manifest(root / "data" / "law.json", root / "data" / "faq.json")
    assert first["law_records"] == 178
    assert first["faq_records"] == 49
    assert first["corpus_version"] == second["corpus_version"]
    assert first["metrics"] == second["metrics"]
    assert first["metrics"]["query_count"] == 16
    assert 0.0 <= first["metrics"]["p_at_1"] <= 1.0
    assert first["metrics"]["explicit_article_hit_at_3"] == 1.0
    assert first["audit"]["quality_summary"]["schema_ok"] is True


def test_structural_candidate_has_complete_metadata_and_promotion_gate():
    root = Path(__file__).resolve().parents[1]
    baseline = corpus_manifest(root / "data" / "law.json", root / "data" / "faq.json")
    candidate = corpus_manifest(
        root / "data" / "law.json",
        root / "data" / "faq.json",
        "legal_structure_v1",
    )
    decision = promotion_decision(baseline, candidate)
    assert candidate["indexed_records"] >= candidate["law_records"]
    assert candidate["audit"]["quality_summary"]["schema_ok"] is True
    assert decision["offline_gate_passed"] is True
    assert decision["checks"]["offline_explicit_article_hit_at_3_is_100_percent"] is True
    assert decision["promotable"] is False
    assert decision["blocking_reason"] == "live_hybrid_metrics_required"


def test_live_candidate_requires_a_matching_collection_audit():
    metrics = {
        "p_at_1": 1.0,
        "ndcg_at_3": 1.0,
        "recall_at_5": 1.0,
        "explicit_article_hit_at_3": 1.0,
    }
    baseline = {"metrics": metrics, "live_metrics": metrics}
    candidate = {
        "metrics": metrics,
        "live_metrics": metrics,
        "audit": {
            "quality_summary": {
                "schema_ok": True,
                "duplicates_ok": True,
                "hygiene_ok": True,
                "legal_anchor_coverage_ok": True,
            }
        },
    }

    decision = promotion_decision(baseline, candidate)

    assert decision["promotable"] is False
    assert decision["blocking_reason"] == "live_collection_audit_required_or_failed"


def test_live_query_budget_is_a_hard_cap() -> None:
    assert len(select_live_cases(5)) == 5
    assert len(select_live_cases(100)) == 16
    with pytest.raises(ValueError, match="at least 1"):
        select_live_cases(0)
