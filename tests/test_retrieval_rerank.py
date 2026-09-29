from __future__ import annotations

from types import SimpleNamespace

from langchain_core.documents import Document

from epr_agent.retrieval import ensemble_retrieval


def test_cross_encoder_shadow_does_not_mutate_primary_rerank_scores(monkeypatch) -> None:
    settings = SimpleNamespace(
        enable_cross_encoder_rerank=True,
        cross_encoder_rollout_percent=0,
        cross_encoder_shadow_mode=True,
        rerank_top_n=10,
        rerank_timeout_ms=1000,
    )
    monkeypatch.setattr(ensemble_retrieval, "get_settings", lambda: settings)
    monkeypatch.setattr(ensemble_retrieval.metrics, "track_rerank_latency_ms", lambda *_args: None)

    class MutatingShadowReranker:
        name = "cross_encoder"
        unavailable_reason = None

        def rerank(self, _query, docs, _top_k):
            self.scored_document = docs[0]
            docs[0].metadata["cross_encoder_score"] = -0.4166
            docs[0].metadata["rerank_score"] = -0.4166
            return docs

    retriever = ensemble_retrieval._EnsembleRetriever.__new__(ensemble_retrieval._EnsembleRetriever)
    retriever.k = 3
    retriever._heuristic_reranker = ensemble_retrieval.HeuristicReranker()
    retriever._cross_encoder_reranker = MutatingShadowReranker()
    retriever._cross_encoder_shadow_available = True
    monkeypatch.setattr(
        ensemble_retrieval,
        "_run_rerank_with_timeout",
        lambda reranker, query, docs, top_k, _timeout: reranker.rerank(query, docs, top_k),
    )
    primary_document = Document(
        page_content="Thời gian thử việc đối với người lao động có trình độ cao đẳng được quy định như sau. " * 3,
        metadata={"Dieu": "Điều 25. Thời gian thử việc", "semantic_score": 0.9333},
    )

    result = retriever._rerank_candidates(
        "Người lao động có trình độ cao đẳng được thử việc tối đa bao lâu?",
        [primary_document],
        [],
    )

    assert result == [primary_document]
    assert retriever._cross_encoder_reranker.scored_document is not primary_document
    assert "cross_encoder_score" not in primary_document.metadata
    assert primary_document.metadata["rerank_score"] == primary_document.metadata["heuristic_rerank_score"]
    assert primary_document.metadata["retrieval_debug"]["shadow_rank"] == 1


def test_semantic_trial_period_evidence_beats_lexical_training_distractor(monkeypatch) -> None:
    query = "Người lao động có trình độ cao đẳng được thử việc tối đa bao lâu? Xin dẫn điều luật."
    monkeypatch.setattr(ensemble_retrieval, "_global_idf", {})
    relevant = Document(
        page_content=(
            "Thời gian thử việc đối với công việc có chức danh nghề nghiệp cần trình độ chuyên môn, "
            "kỹ thuật từ cao đẳng trở lên là không quá 60 ngày."
        ),
        metadata={"Dieu": "Điều 25. Thời gian thử việc", "semantic_score": 0.9333},
    )
    lexical_distractor = Document(
        page_content=(
            "Nội dung và mức hỗ trợ đào tạo nghề cho người lao động, bao gồm hỗ trợ chi phí "
            "đào tạo và tổ chức thực hiện chính sách hỗ trợ."
        ),
        metadata={"Dieu": "Điều 5. Nội dung hỗ trợ đào tạo nghề", "lexical_score": 28.0},
    )

    phrases = ensemble_retrieval._extract_query_phrases(query)
    relevant_score = ensemble_retrieval._score_document(query, relevant)
    distractor_score = ensemble_retrieval._score_document(query, lexical_distractor)

    assert "thử việc" in phrases
    assert "cao đẳng" in phrases
    assert relevant_score > distractor_score


def test_current_law_support_status_does_not_reduce_topical_relevance(monkeypatch) -> None:
    monkeypatch.setattr(ensemble_retrieval, "_global_idf", {})
    query = "Tỷ lệ tái chế bắt buộc đối với bao bì được quy định như thế nào?"
    text = (
        "Điều 78 quy định tỷ lệ tái chế và quy cách tái chế bắt buộc đối với sản phẩm, bao bì. "
        "Tỷ lệ tái chế bắt buộc được xác định theo khối lượng sản xuất, nhập khẩu."
    )
    metadata = {"Dieu": "Điều 78. Tỷ lệ tái chế", "semantic_score": 0.9}
    verified = Document(page_content=text, metadata={**metadata, "Current_Law_Support": True})
    unresolved = Document(page_content=text, metadata={**metadata, "Current_Law_Support": False})

    assert ensemble_retrieval._score_document(query, unresolved) == ensemble_retrieval._score_document(query, verified)


def test_explicitly_superseded_source_still_receives_relevance_penalty(monkeypatch) -> None:
    monkeypatch.setattr(ensemble_retrieval, "_global_idf", {})
    query = "Tỷ lệ tái chế bắt buộc đối với bao bì được quy định như thế nào?"
    current = Document(
        page_content="Điều 78 quy định tỷ lệ tái chế bắt buộc đối với sản phẩm, bao bì.",
        metadata={"Dieu": "Điều 78", "semantic_score": 0.9},
    )
    superseded = Document(
        page_content=current.page_content,
        metadata={**current.metadata, "Effective_Status": "superseded"},
    )

    assert ensemble_retrieval._score_document(query, superseded) < ensemble_retrieval._score_document(query, current)


def test_rrf_score_is_not_misread_as_semantic_score(monkeypatch) -> None:
    monkeypatch.setattr(ensemble_retrieval, "_global_idf", {})
    lexical_document = Document(
        page_content="Nội dung về đào tạo nghề.",
        metadata={"score": 0.0161, "rrf_score": 0.0161, "lexical_score": 0.0},
    )

    breakdown = ensemble_retrieval._score_breakdown("thời gian thử việc", lexical_document)

    assert breakdown["semantic"] == 0.0
