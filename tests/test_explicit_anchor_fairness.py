from backend.core.ensemble_retrieval import _EnsembleRetriever, _round_robin_anchor_ids
from langchain_core.documents import Document


def test_explicit_anchor_lookup_reserves_capacity_for_every_named_article():
    selected = _round_robin_anchor_ids(
        [[f"article-77-{index}" for index in range(20)], [f"article-78-{index}" for index in range(20)]],
        limit=20,
    )

    assert len(selected) == 20
    assert any(point_id.startswith("article-77") for point_id in selected)
    assert any(point_id.startswith("article-78") for point_id in selected)
    assert selected[:4] == ["article-77-0", "article-78-0", "article-77-1", "article-78-1"]


def test_multi_anchor_selection_reserves_one_ranked_chunk_per_article():
    retriever = _EnsembleRetriever(k=3)
    ranked = [
        Document("", metadata={"Dieu": "Điều 77"}),
        Document("", metadata={"Dieu": "Điều 98"}),
        Document("", metadata={"Dieu": "Điều 78"}),
    ]

    selected = retriever._select_with_explicit_coverage(ranked, ["Điều 77", "Điều 78"], limit=3)

    assert [document.metadata["Dieu"] for document in selected] == ["Điều 77", "Điều 78", "Điều 98"]
