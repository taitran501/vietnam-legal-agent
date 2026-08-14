from backend.core.reranker import rerank_by_keyword_boost
from langchain_core.documents import Document


def test_keyword_reranker_uses_canonical_vietnamese_tokenizer() -> None:
    documents = [
        Document("Thông tin về pin và tái chế", metadata={"score": 0.5}),
        Document("Thông tin chung về môi trường", metadata={"score": 0.5}),
    ]

    ranked = rerank_by_keyword_boost("tái chế pin", documents)

    assert ranked[0].page_content.startswith("Thông tin về pin")
    assert ranked[0].metadata["combined_score"] > ranked[1].metadata["combined_score"]
