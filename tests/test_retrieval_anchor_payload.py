from __future__ import annotations

from types import SimpleNamespace

from vietnam_legal_agent.domain.legal import LegalAnchor, explicit_anchors
from vietnam_legal_agent.retrieval import ensemble_retrieval


def test_explicit_article_lookup_supports_article_title_payload_alias(monkeypatch):
    record = SimpleNamespace(
        id=25,
        payload={
            "article_title": "Điều 20.2.LQ.25. Thời gian thử việc",
            "document_title": "(Điều 25 Bộ luật số 45/2019/QH14, có hiệu lực thi hành)",
            "Text": "Điều 25 quy định thời gian thử việc tối đa theo từng nhóm công việc.",
        },
    )
    decoys = [
        SimpleNamespace(
            id=index,
            payload={
                "article_title": "Điều 10.1.LQ.25. Điều 25 không thuộc Bộ luật Lao động",
                "document_title": "(Điều 25 Luật số 34/2021/QH15)",
                "Text": "Điều 25 của một luật khác.",
            },
        )
        for index in range(1, 26)
    ]
    records = [*decoys, record]
    records_by_id = {item.id: item for item in records}

    class FakeQdrantClient:
        def scroll(self, **_kwargs):
            return records, None

        def retrieve(self, *, ids, **_kwargs):
            return [records_by_id[point_id] for point_id in ids if point_id in records_by_id]

    client = FakeQdrantClient()
    monkeypatch.setattr(ensemble_retrieval, "get_settings", lambda: SimpleNamespace(law_collection="test-laws"))
    monkeypatch.setattr(ensemble_retrieval, "_get_qdrant_client", lambda: client)
    monkeypatch.setattr(
        ensemble_retrieval,
        "_get_law_vectorstore",
        lambda: SimpleNamespace(client=client, collection_name="test-laws"),
    )
    monkeypatch.setattr(ensemble_retrieval, "_article_index", {})
    monkeypatch.setattr(ensemble_retrieval, "_anchor_index", {})
    monkeypatch.setattr(ensemble_retrieval, "_document_article_index", {})
    monkeypatch.setattr(ensemble_retrieval, "_document_anchor_index", {})
    monkeypatch.setattr(ensemble_retrieval, "_index_built", False)
    monkeypatch.setattr(ensemble_retrieval, "_article_index_collection", "")

    retriever = ensemble_retrieval._EnsembleRetriever.__new__(ensemble_retrieval._EnsembleRetriever)
    anchors = explicit_anchors("Điều 25 Luật số 45/2019/QH14")
    assert anchors == [LegalAnchor(document_number="45/2019/QH14", article="Điều 25")]
    documents = retriever._retrieve_explicit_anchors(anchors)

    assert len(documents) == 1
    assert documents[0].metadata["Dieu"] == "Điều 25. Thời gian thử việc"
    assert documents[0].metadata["article_title"] == record.payload["article_title"]
    assert documents[0].metadata["Document_Number"] == "45/2019/QH14"
    assert documents[0].metadata["explicit_match"] is True
    assert retriever._matches_article(documents[0], "Điều 25") is True


def test_document_qualified_anchor_never_falls_back_to_other_laws(monkeypatch):
    point_ids = [
        1,
        2,
    ]
    monkeypatch.setattr(ensemble_retrieval, "_article_index", {"Điều 25": point_ids})
    monkeypatch.setattr(ensemble_retrieval, "_document_article_index", {})
    monkeypatch.setattr(ensemble_retrieval, "_index_built", True)
    monkeypatch.setattr(ensemble_retrieval, "_article_index_collection", "test-laws")
    monkeypatch.setattr(
        ensemble_retrieval,
        "get_settings",
        lambda: SimpleNamespace(law_collection="test-laws"),
    )

    resolved = ensemble_retrieval._get_point_ids_for_anchors(
        [LegalAnchor(document_number="45/2019/QH14", article="Điều 25")]
    )

    assert resolved == []


def test_legacy_payload_uses_source_article_and_document_number():
    payload = ensemble_retrieval._normalise_legal_payload(
        {
            "article_title": "Điều 20.2.LQ.25. Thời gian thử việc",
            "document_title": "(Điều 25 Bộ luật số 45/2019/QH14, có hiệu lực từ ngày 01/01/2021)",
            "text": "Thời gian thử việc đối với công việc cần trình độ cao đẳng trở lên là 60 ngày.",
        }
    )

    assert payload["Dieu"] == "Điều 25. Thời gian thử việc"
    assert payload["Parent_Dieu"] == payload["Dieu"]
    assert payload["Document_Number"] == "45/2019/QH14"
    assert payload["article_title"] == "Điều 20.2.LQ.25. Thời gian thử việc"
