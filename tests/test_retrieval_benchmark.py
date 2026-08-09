from pathlib import Path

from scripts.retrieval_benchmark import corpus_manifest


def test_corpus_manifest_is_deterministic_and_counts_committed_sources():
    root = Path(__file__).resolve().parents[1]
    first = corpus_manifest(root / "data" / "law.json", root / "data" / "faq.json")
    second = corpus_manifest(root / "data" / "law.json", root / "data" / "faq.json")
    assert first["law_records"] == 178
    assert first["faq_records"] == 49
    assert first["corpus_version"] == second["corpus_version"]
    assert first["metrics"] is None
