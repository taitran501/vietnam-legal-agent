"""
Document re-ranking module for RAG retrieval.

Implements LLM-based cross-encoder re-ranking to improve retrieval accuracy
by scoring (query, document) pairs for relevance.

Why Re-ranking?
---------------
Embedding-based retrieval (semantic search) uses cosine similarity in vector space,
which has limitations:
- Cannot distinguish domain overlap (off-domain scores 0.24-0.38, on-domain 0.27-0.35)
- Misses nuanced relevance signals (e.g., "tái chế bao bì" vs "tái chế ắc quy")
- Treats all dimensions equally, no query-specific weighting

Re-ranking solves this by:
1. Retrieving top-K candidates with fast semantic search (high recall)
2. Re-ranking with LLM cross-encoder (high precision)
3. Returning top-N after re-ranking (N <= K)

Architecture:
-------------
- Uses gpt-4o-mini for fast binary relevance scoring (0-5 scale)
- Batch processing for efficiency (scores all docs in single LLM call)
- Thread executor to avoid blocking event loop
- Configurable top-K retrieval and top-N return count

Integration Points:
-------------------
- Legal retrieval: Re-rank after SelfQuery + semantic search
- FAQ retrieval: Re-rank after hybrid semantic + keyword search

Performance:
------------
- Latency: ~1-2s for 5 docs (single LLM call)
- Cost: ~500 tokens per re-ranking call (very cheap)
- Accuracy improvement: Expected +15-25% relevance (based on LLM-as-judge scores)
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import List, Tuple

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from backend.core.llm_instances import get_llm_smart

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM-based relevance re-ranker
# ---------------------------------------------------------------------------

_RERANK_SYSTEM = """Bạn là chuyên gia đánh giá mức độ phù hợp giữa câu hỏi và tài liệu pháp luật.

NHIỆM VỤ:
Chấm điểm relevance từ 0-5 cho mỗi tài liệu dựa trên câu hỏi.

TIÊU CHÍ CHẤM ĐIỂM:
- 5: Tài liệu TRẢ LỜI TRỰC TIẾP câu hỏi, chứa thông tin chính xác và đầy đủ
- 4: Tài liệu chứa thông tin LIÊN QUAN MẠNH, có thể dùng để trả lời tốt
- 3: Tài liệu có liên quan vừa phải, cần bổ sung thêm thông tin
- 2: Tài liệu chỉ liên quan GIÁN TIẾP, có một số từ khóa chung
- 1: Tài liệu rất ít liên quan, chỉ trùng lặp từ khóa ngẫu nhiên
- 0: Tài liệu KHÔNG LIÊN QUAN hoặc sai chủ đề hoàn toàn

LƯU Ý QUAN TRỌNG:
- Ưu tiên số Điều/Chương/Mục cụ thể khi đánh giá
- "Điều 77 về tái chế" phù hợp điểm 5 với câu hỏi "Điều 77 quy định gì?"
- "Điều 80 về xử phạt" phù hợp điểm 2 với câu hỏi "Điều 77 quy định gì?" (sai Điều)
- Văn bản có chứa từ khóa EPR/tái chế nhưng không trả lời câu hỏi → điểm 0-1

ĐỊNH DẠNG TRẢ LỜI:
Trả về MỘT DÒNG duy nhất chứa các số điểm cách nhau bởi dấu phẩy.
Ví dụ: "5,3,1,4,2" cho 5 tài liệu.
KHÔNG giải thích, KHÔNG thêm text khác."""

_rerank_prompt = ChatPromptTemplate.from_messages([
    ("system", _RERANK_SYSTEM),
    ("human", """Câu hỏi: {query}

Tài liệu 1:
{doc_1}

Tài liệu 2:
{doc_2}

Tài liệu 3:
{doc_3}

Tài liệu 4:
{doc_4}

Tài liệu 5:
{doc_5}

Cho điểm relevance (0-5) cho mỗi tài liệu theo thứ tự trên. Trả về MỘT DÒNG chứa các số cách nhau bởi dấu phẩy."""),
])


def _format_doc_for_rerank(doc: Document, index: int) -> str:
    """Format a document for re-ranking prompt, including metadata."""
    meta = doc.metadata
    citations = []
    if meta.get("Dieu"):
        citations.append(f"Điều {meta['Dieu']}")
    if meta.get("Chuong"):
        citations.append(f"Chương {meta['Chuong']}")
    if meta.get("Muc"):
        citations.append(f"Mục {meta['Muc']}")

    label = ", ".join(citations) if citations else f"Tài liệu {index}"
    content = doc.page_content[:500]  # Truncate to 500 chars for re-ranking

    return f"[{label}]\n{content}"


def _parse_rerank_scores(output: str, num_docs: int) -> List[float]:
    """Parse LLM output into list of scores.

    Expected format: "5,3,1,4,2"
    Returns: [5.0, 3.0, 1.0, 4.0, 2.0]
    """
    try:
        # Extract first line (ignore any extra text)
        lines = output.strip().split("\n")
        score_line = lines[0].strip()

        # Parse comma-separated scores
        scores = []
        for token in score_line.split(","):
            token = token.strip()
            # Extract first digit if token is not clean
            import re
            match = re.search(r'(\d)', token)
            if match:
                score = float(match.group(1))
                scores.append(min(max(score, 0.0), 5.0))  # Clamp to [0, 5]

        # Pad with 0.0 if LLM returned fewer scores than docs
        while len(scores) < num_docs:
            scores.append(0.0)

        # Return only first num_docs scores
        return scores[:num_docs]

    except Exception as exc:
        logger.warning("Failed to parse re-rank scores: %s, output was: %r", exc, output)
        # Fail-safe: return equal scores (no re-ranking)
        return [2.5] * num_docs


@lru_cache(maxsize=1)
def _get_reranker():
    """Get re-ranker chain singleton."""
    return _rerank_prompt | get_llm_smart() | StrOutputParser()


def rerank_documents(
    query: str,
    docs: List[Document],
    top_k: int = 3,
) -> List[Document]:
    """
    Re-rank documents by relevance using LLM cross-encoder.

    Args:
        query: User's question
        docs: List of retrieved documents (from semantic search)
        top_k: Number of documents to return after re-ranking

    Returns:
        Re-ranked list of documents, sorted by relevance (highest first)

    Example:
        >>> docs = retrieve_legal_async("tái chế bao bì nhựa")
        >>> reranked = rerank_documents("tái chế bao bì nhựa", docs, top_k=3)
        >>> # Returns top 3 most relevant docs
    """
    if not docs:
        return []

    if len(docs) == 1:
        # No re-ranking needed for single doc
        return docs

    # Limit to 5 docs for re-ranking (prompt constraint)
    docs_to_rerank = docs[:5]
    num_docs = len(docs_to_rerank)

    # Format documents for prompt
    doc_texts = [_format_doc_for_rerank(doc, i + 1) for i, doc in enumerate(docs_to_rerank)]

    # Build prompt kwargs
    prompt_kwargs = {"query": query}
    for i, doc_text in enumerate(doc_texts, 1):
        prompt_kwargs[f"doc_{i}"] = doc_text

    # Fill remaining slots with empty string if < 5 docs
    for i in range(num_docs + 1, 6):
        prompt_kwargs[f"doc_{i}"] = "(không có)"

    # Get scores from LLM
    try:
        chain = _get_reranker()
        output = chain.invoke(prompt_kwargs)
        scores = _parse_rerank_scores(output, num_docs)

        # Attach scores to metadata
        scored_docs = []
        for doc, score in zip(docs_to_rerank, scores):
            doc.metadata["rerank_score"] = score
            doc.metadata["original_score"] = doc.metadata.get("score", None)
            scored_docs.append((doc, score))

        # Sort by score (descending)
        scored_docs.sort(key=lambda x: x[1], reverse=True)

        # Return top_k
        reranked = [doc for doc, _ in scored_docs[:top_k]]

        logger.info(
            "Re-ranked %d docs → returned top %d, scores: %s",
            num_docs,
            len(reranked),
            [s for _, s in scored_docs[:top_k]],
        )

        return reranked

    except Exception as exc:
        logger.warning("Re-ranking failed: %s, returning original order", exc)
        # Fail-safe: return original docs (no re-ranking)
        return docs_to_rerank[:top_k]


# ---------------------------------------------------------------------------
# Async wrapper for use in async pipeline
# ---------------------------------------------------------------------------

async def rerank_documents_async(
    query: str,
    docs: List[Document],
    top_k: int = 3,
) -> List[Document]:
    """
    Async wrapper for re-ranking to avoid blocking event loop.

    CRITICAL: LLM calls are sync → run in thread executor.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        rerank_documents,
        query,
        docs,
        top_k,
    )


# ---------------------------------------------------------------------------
# Lightweight keyword-based re-ranker (no LLM cost)
# ---------------------------------------------------------------------------

def rerank_by_keyword_boost(
    query: str,
    docs: List[Document],
    boost_weight: float = 0.3,
) -> List[Document]:
    """
    Fast keyword-based re-ranking without LLM cost.

    Uses Vietnamese token overlap to boost scores.
    This is already implemented in FAQ retrieval,
    but extracted here for reuse.

    Args:
        query: User's question
        docs: List of documents with existing scores in metadata
        boost_weight: Weight for keyword boost (0.0-1.0)

    Returns:
        Re-sorted documents by combined score
    """
    from backend.core.retrieval import _tokenize_vietnamese

    if not docs:
        return []

    query_tokens = _tokenize_vietnamese(query)

    for doc in docs:
        doc_tokens = _tokenize_vietnamese(doc.page_content)
        keyword_score = len(query_tokens & doc_tokens) / len(query_tokens) if query_tokens else 0.0

        # Get existing semantic score
        semantic_score = doc.metadata.get("score", doc.metadata.get("semantic_score", 0.5))

        # Combined score
        combined_score = semantic_score + boost_weight * keyword_score
        doc.metadata["combined_score"] = combined_score

    # Sort by combined score
    docs.sort(key=lambda d: d.metadata.get("combined_score", 0), reverse=True)

    return docs
