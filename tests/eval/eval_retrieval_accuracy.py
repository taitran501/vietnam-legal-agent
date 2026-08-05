"""
Sophisticated Retrieval Accuracy Evaluation Script

Purpose:
  - Evaluate retrieval accuracy BEFORE and AFTER re-ranking
  - Measure precision@K, recall@K, NDCG@K for legal retrieval
  - Identify specific failure modes of the re-ranker
  - Provide actionable insights to improve accuracy to >0.95

Usage:
    cd epr_chatbot
    python -m tests.eval.eval_retrieval_accuracy
    python -m tests.eval.eval_retrieval_accuracy --verbose
    python -m tests.eval.eval_retrieval_accuracy --output retrieval_eval_results.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Bootstrap ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# Import retrieval functions directly (bypass full pipeline)
from backend.core.retrieval import (
    retrieve_legal,
    retrieve_faq_top1,
    parse_legal_query,
    build_qdrant_filter,
    _get_law_vectorstore,
    ensure_faq_collection,
)
from backend.core.reranker import rerank_documents

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Golden retrieval dataset with known correct answers
# ─────────────────────────────────────────────────────────────────────────────

LEGAL_RETRIEVAL_GOLD = [
    {
        "id": "legal_ret_001",
        "query": "Điều 77 quy định gì về trách nhiệm tái chế?",
        "expected_dieu": ["Điều 77"],
        "expected_topics": ["tái chế", "nhà sản xuất", "nhập khẩu"],
        "category": "legal",
    },
    {
        "id": "legal_ret_002",
        "query": "Trách nhiệm xử lý ắc quy và pin sau khi hết vòng đời",
        "expected_dieu": ["Điều 77", "Điều 78"],
        "expected_topics": ["ắc quy", "pin", "xử lý"],
        "category": "legal",
    },
    {
        "id": "legal_ret_003",
        "query": "Điều kiện để cơ sở tái chế được hoạt động",
        "expected_dieu": ["Điều 80"],
        "expected_topics": ["cơ sở", "điều kiện", "tái chế"],
        "category": "legal",
    },
    {
        "id": "legal_ret_004",
        "query": "Bộ Tài nguyên và Môi trường quản lý EPR như thế nào?",
        "expected_dieu": ["Điều 82"],
        "expected_topics": ["Bộ Tài nguyên", "quản lý"],
        "category": "legal",
    },
    {
        "id": "legal_ret_005",
        "query": "Phương tiện giao thông bắt đầu tái chế từ năm nào?",
        "expected_dieu": ["Điều 77", "Điều 78"],
        "expected_topics": ["phương tiện giao thông", "2027", "lộ trình"],
        "category": "legal",
    },
    {
        "id": "legal_ret_006",
        "query": "Hệ số đóng góp tài chính Fs tính như thế nào?",
        "expected_dieu": ["Điều 80"],
        "expected_topics": ["tài chính", "hệ số", "đóng góp"],
        "category": "legal",
    },
    {
        "id": "legal_ret_007",
        "query": "Xử phạt vi phạm nghĩa vụ tái chế",
        "expected_dieu": ["Điều 81"],
        "expected_topics": ["xử phạt", "vi phạm"],
        "category": "legal",
    },
    {
        "id": "legal_ret_008",
        "query": "Thủ tục đăng ký kế hoạch tái chế hàng năm",
        "expected_dieu": ["Điều 79"],
        "expected_topics": ["đăng ký", "kế hoạch"],
        "category": "legal",
    },
    {
        "id": "legal_ret_009",
        "query": "Quy cách tái chế săm lốp bắt buộc",
        "expected_dieu": ["Điều 78"],
        "expected_topics": ["săm lốp", "quy cách"],
        "category": "legal",
    },
    {
        "id": "legal_ret_010",
        "query": "Điều kiện công nhận đơn vị tái chế ủy quyền EPR",
        "expected_dieu": ["Điều 80"],
        "expected_topics": ["cơ sở", "ủy quyền", "điều kiện"],
        "category": "legal",
    },
    {
        "id": "legal_ret_011",
        "query": "Tỷ lệ tái chế bao bì nhựa PE là bao nhiêu?",
        "expected_dieu": ["Phụ lục XXII"],
        "expected_topics": ["tỷ lệ", "bao bì", "PE"],
        "category": "legal",
    },
    {
        "id": "legal_ret_012",
        "query": "Nhà sản xuất có doanh thu dưới 30 tỷ có phải tái chế không?",
        "expected_dieu": ["Điều 77"],
        "expected_topics": ["doanh thu", "30 tỷ", "miễn"],
        "category": "legal",
    },
]

FAQ_RETRIEVAL_GOLD = [
    {
        "id": "faq_ret_001",
        "query": "Các đối tượng nào phải thực hiện trách nhiệm tái chế?",
        "expected_topics": ["nhà sản xuất", "nhập khẩu", "tái chế"],
        "category": "faq",
    },
    {
        "id": "faq_ret_002",
        "query": "Bao bì thương phẩm là gì?",
        "expected_topics": ["bao bì", "trực tiếp", "ngoài"],
        "category": "faq",
    },
    {
        "id": "faq_ret_003",
        "query": "Khi nào nhà sản xuất phải bắt đầu thực hiện trách nhiệm tái chế?",
        "expected_topics": ["lộ trình", "2024", "2025"],
        "category": "faq",
    },
    {
        "id": "faq_ret_004",
        "query": "Trường hợp nào không phải thực hiện trách nhiệm tái chế?",
        "expected_topics": ["xuất khẩu", "tạm nhập", "nghiên cứu"],
        "category": "faq",
    },
    {
        "id": "faq_ret_005",
        "query": "Dầu nhớt có phải tái chế bắt buộc không?",
        "expected_topics": ["dầu nhớt", "tái chế"],
        "category": "faq",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RetrievalResult:
    query: str
    retrieved_docs: List[Dict] = field(default_factory=list)
    retrieved_dieu: List[str] = field(default_factory=list)
    retrieved_topics: List[str] = field(default_factory=list)
    reranked_docs: List[Dict] = field(default_factory=list)
    reranked_dieu: List[str] = field(default_factory=list)
    original_scores: List[float] = field(default_factory=list)
    rerank_scores: List[float] = field(default_factory=list)


@dataclass
class RetrievalScore:
    case_id: str
    query: str
    category: str
    expected_dieu: List[str]
    expected_topics: List[str]
    # Before re-ranking
    precision_at_1_before: float
    precision_at_3_before: float
    precision_at_5_before: float
    recall_at_3_before: float
    recall_at_5_before: float
    ndcg_at_3_before: float
    ndcg_at_5_before: float
    # After re-ranking
    precision_at_1_after: float
    precision_at_3_after: float
    precision_at_5_after: float
    recall_at_3_after: float
    recall_at_5_after: float
    ndcg_at_3_after: float
    ndcg_at_5_after: float
    # Topic matching
    topic_recall_before: float
    topic_recall_after: float
    # Did re-ranking help?
    reranking_improved: bool
    reranking_degraded: bool
    # Timing
    retrieval_ms: float
    reranking_ms: float


# ─────────────────────────────────────────────────────────────────────────────
# Metric computation functions
# ─────────────────────────────────────────────────────────────────────────────

def _compute_precision(retrieved_dieu: List[str], expected_dieu: List[str], k: int) -> float:
    """Compute precision@K: fraction of top-K retrieved docs that are relevant."""
    if not expected_dieu:
        return 1.0
    retrieved_top_k = retrieved_dieu[:k]
    if not retrieved_top_k:
        return 0.0
    relevant = sum(1 for d in retrieved_top_k if any(_dieu_matches(d, exp) for exp in expected_dieu))
    return relevant / min(k, len(retrieved_top_k))


def _compute_recall(retrieved_dieu: List[str], expected_dieu: List[str], k: int) -> float:
    """Compute recall@K: fraction of expected docs found in top-K."""
    if not expected_dieu:
        return 1.0
    retrieved_top_k = retrieved_dieu[:k]
    found = sum(1 for exp in expected_dieu if any(_dieu_matches(d, exp) for d in retrieved_top_k))
    return found / len(expected_dieu)


def _compute_ndcg(retrieved_dieu: List[str], expected_dieu: List[str], k: int) -> float:
    """Compute NDCG@K with binary relevance using partial matching."""
    if not expected_dieu:
        return 1.0
    retrieved_top_k = retrieved_dieu[:k]
    if not retrieved_top_k:
        return 0.0

    # Compute relevance scores (1 if matches any expected, 0 otherwise)
    relevances = [1.0 if any(_dieu_matches(d, exp) for exp in expected_dieu) else 0.0 for d in retrieved_top_k]

    # DCG
    dcg = sum(rel / (i + 2) for i, rel in enumerate(relevances))

    # Ideal DCG (all relevant docs at top)
    ideal_relevances = sorted([1.0] * min(len(expected_dieu), k) + [0.0] * max(0, k - len(expected_dieu)), reverse=True)
    idcg = sum(rel / (i + 2) for i, rel in enumerate(ideal_relevances))

    return dcg / idcg if idcg > 0 else 0.0


def _compute_topic_overlap(retrieved_topics: List[str], expected_topics: List[str]) -> float:
    """Compute topic-level recall: fraction of expected topics found."""
    if not expected_topics:
        return 1.0
    retrieved_set = set(retrieved_topics)
    expected_set = set(expected_topics)
    found = sum(1 for t in expected_topics if t in retrieved_set)
    return found / len(expected_topics)


def _extract_dieu_from_docs(docs: List[Dict]) -> List[str]:
    """Extract Dieu numbers from document metadata."""
    dieu_list = []
    for doc in docs:
        meta = doc.get("metadata", {})
        dieu = meta.get("Dieu", "")
        if dieu:
            # Extract just the "Điều X" part (before the period)
            import re
            match = re.match(r'(Điều\s+\d+|Phụ lục\s+[A-Z0-9]+)', str(dieu))
            if match:
                dieu_list.append(match.group(1))
            else:
                dieu_list.append(str(dieu))
    return dieu_list


def _dieu_matches(retrieved: str, expected: str) -> bool:
    """Check if a retrieved Dieu matches expected (supports partial matching)."""
    # Exact match
    if retrieved == expected:
        return True
    # Partial: "Điều 77" matches "Điều 77. Trách nhiệm..."
    if expected in retrieved or retrieved in expected:
        return True
    # Number match: extract numbers and compare
    import re
    ret_nums = re.findall(r'(\d+)', retrieved)
    exp_nums = re.findall(r'(\d+)', expected)
    if ret_nums and exp_nums:
        return ret_nums[0] == exp_nums[0]
    return False


def _extract_topics_from_docs(docs: List[Dict]) -> List[str]:
    """Extract topic keywords from document content.
    
    IMPROVED: Now uses up to 2000 chars (was 200) and expanded vocabulary.
    """
    # Use more text for better topic coverage
    all_text = " ".join(doc.get("page_content", "")[:2000] for doc in docs[:5]).lower()
    # Expanded topic vocabulary with synonyms
    topic_vocab = [
        "tái chế", "nhà sản xuất", "nhập khẩu", "ắc quy", "pin", "dầu nhớt",
        "săm lốp", "bao bì", "phương tiện", "tài chính", "hệ số", "đóng góp",
        "xử phạt", "vi phạm", "đăng ký", "kế hoạch", "cơ sở", "điều kiện",
        "quy cách", "tỷ lệ", "lộ trình", "2024", "2025", "2027", "doanh thu",
        "30 tỷ", "miễn", "ủy quyền", "xuất khẩu", "tạm nhập", "nghiên cứu",
        "trực tiếp", "ngoài", "Bộ Tài nguyên", "quản lý", "xử lý",
        # Additional keywords
        "trách nhiệm", "nghĩa vụ", "quỹ", "bảo vệ", "môi trường",
        "hỗ trợ", "tiêu chuẩn", "công nhận", "điều kiện",
    ]
    return [t for t in topic_vocab if t in all_text]


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation runner
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_legal_retrieval(case: Dict, verbose: bool = False) -> RetrievalScore:
    """Evaluate legal retrieval with ensemble method (single pass, no before/after)."""
    query = case["query"]
    expected_dieu = case.get("expected_dieu", [])
    expected_topics = case.get("expected_topics", [])

    # ── Step 1: Retrieve using semantic-only (baseline) ──────────────────
    start = time.perf_counter()

    from backend.core.retrieval import _get_law_vectorstore
    vs = _get_law_vectorstore()
    docs_before = vs.similarity_search(query, k=10)
    from backend.core.retrieval import _enrich_docs_from_qdrant
    docs_before = _enrich_docs_from_qdrant(docs_before, vs.collection_name)

    retrieval_ms = (time.perf_counter() - start) * 1000

    docs_before_data = [
        {
            "page_content": d.page_content[:200],
            "metadata": {
                "Dieu": d.metadata.get("Dieu", ""),
                "Chuong": d.metadata.get("Chuong", ""),
                "filter_matched": d.metadata.get("filter_matched", False),
            },
        }
        for d in docs_before
    ]
    dieu_before = _extract_dieu_from_docs(docs_before_data)
    topics_before = _extract_topics_from_docs(docs_before_data)

    # Compute metrics BEFORE (semantic-only)
    p1_before = _compute_precision(dieu_before, expected_dieu, 1)
    p3_before = _compute_precision(dieu_before, expected_dieu, 3)
    p5_before = _compute_precision(dieu_before, expected_dieu, 5)
    r3_before = _compute_recall(dieu_before, expected_dieu, 3)
    r5_before = _compute_recall(dieu_before, expected_dieu, 5)
    ndcg3_before = _compute_ndcg(dieu_before, expected_dieu, 3)
    ndcg5_before = _compute_ndcg(dieu_before, expected_dieu, 5)
    topic_recall_before = _compute_topic_overlap(topics_before, expected_topics)

    if verbose:
        print(f"  BEFORE (semantic-only):")
        print(f"    Retrieved: {dieu_before[:5]}")
        print(f"    P@1={p1_before:.2f} P@3={p3_before:.2f} P@5={p5_before:.2f}")
        print(f"    R@3={r3_before:.2f} R@5={r5_before:.2f}")
        print(f"    NDCG@3={ndcg3_before:.2f} NDCG@5={ndcg5_before:.2f}")

    # ── Step 2: Retrieve using ensemble + re-ranking ─────────────────────
    start = time.perf_counter()
    from backend.core.retrieval import retrieve_legal
    docs_after = retrieve_legal(query)
    reranking_ms = (time.perf_counter() - start) * 1000

    docs_after_data = [
        {
            "page_content": d.page_content[:200],
            "metadata": {
                "Dieu": d.metadata.get("Dieu", ""),
                "Chuong": d.metadata.get("Chuong", ""),
                "rerank_score": d.metadata.get("rerank_score", 0),
                "filter_matched": d.metadata.get("filter_matched", False),
            },
        }
        for d in docs_after
    ]
    dieu_after = _extract_dieu_from_docs(docs_after_data)
    topics_after = _extract_topics_from_docs(docs_after_data)

    # Compute metrics AFTER (ensemble + rerank)
    p1_after = _compute_precision(dieu_after, expected_dieu, 1)
    p3_after = _compute_precision(dieu_after, expected_dieu, 3)
    p5_after = _compute_precision(dieu_after, expected_dieu, 5)
    r3_after = _compute_recall(dieu_after, expected_dieu, 3)
    r5_after = _compute_recall(dieu_after, expected_dieu, 5)
    ndcg3_after = _compute_ndcg(dieu_after, expected_dieu, 3)
    ndcg5_after = _compute_ndcg(dieu_after, expected_dieu, 5)
    topic_recall_after = _compute_topic_overlap(topics_after, expected_topics)

    if verbose:
        print(f"  AFTER (ensemble + rerank):")
        print(f"    Retrieved: {dieu_after[:3]}")
        print(f"    P@1={p1_after:.2f} P@3={p3_after:.2f} P@5={p5_after:.2f}")
        print(f"    R@3={r3_after:.2f} R@5={r5_after:.2f}")
        print(f"    NDCG@3={ndcg3_after:.2f} NDCG@5={ndcg5_after:.2f}")
        print(f"    Topic recall={topic_recall_after:.2f}")
        print(f"    Total time: {reranking_ms:.0f}ms")

    # Determine if ensemble helped or hurt
    reranking_improved = (p1_after + r3_after + ndcg3_after) > (p1_before + r3_before + ndcg3_before)
    reranking_degraded = (p1_after + r3_after + ndcg3_after) < (p1_before + r3_before + ndcg3_before)

    return RetrievalScore(
        case_id=case["id"],
        query=query,
        category="legal",
        expected_dieu=expected_dieu,
        expected_topics=expected_topics,
        precision_at_1_before=p1_before,
        precision_at_3_before=p3_before,
        precision_at_5_before=p5_before,
        recall_at_3_before=r3_before,
        recall_at_5_before=r5_before,
        ndcg_at_3_before=ndcg3_before,
        ndcg_at_5_before=ndcg5_before,
        precision_at_1_after=p1_after,
        precision_at_3_after=p3_after,
        precision_at_5_after=p5_after,
        recall_at_3_after=r3_after,
        recall_at_5_after=r5_after,
        ndcg_at_3_after=ndcg3_after,
        ndcg_at_5_after=ndcg5_after,
        topic_recall_before=topic_recall_before,
        topic_recall_after=topic_recall_after,
        reranking_improved=reranking_improved,
        reranking_degraded=reranking_degraded,
        retrieval_ms=retrieval_ms,
        reranking_ms=reranking_ms,
    )


def evaluate_faq_retrieval(case: Dict, verbose: bool = False) -> RetrievalScore:
    """Evaluate FAQ retrieval with and without re-ranking."""
    query = case["query"]
    expected_topics = case.get("expected_topics", [])

    # ── Step 1: Retrieve WITHOUT re-ranking ──────────────────────────────
    start = time.perf_counter()
    docs_before = retrieve_faq_top1(query, rerank=False)
    retrieval_ms = (time.perf_counter() - start) * 1000

    docs_before_data = [
        {
            "page_content": d.page_content[:200],
            "metadata": {
                "score": d.metadata.get("score", 0),
                "semantic_score": d.metadata.get("semantic_score", 0),
            },
        }
        for d in docs_before
    ]
    topics_before = _extract_topics_from_docs(docs_before_data)

    topic_recall_before = _compute_topic_overlap(topics_before, expected_topics)
    # For FAQ, we expect 1 doc, so P@1 = 1 if found, 0 otherwise
    p1_before = 1.0 if docs_before else 0.0

    if verbose:
        print(f"  BEFORE reranking:")
        print(f"    Found: {len(docs_before)} docs")
        print(f"    P@1={p1_before:.2f}")
        print(f"    Topic recall={topic_recall_before:.2f}")

    # ── Step 2: Retrieve WITH re-ranking ─────────────────────────────────
    start = time.perf_counter()
    docs_after = retrieve_faq_top1(query, rerank=True)
    reranking_ms = (time.perf_counter() - start) * 1000

    docs_after_data = [
        {
            "page_content": d.page_content[:200],
            "metadata": {
                "score": d.metadata.get("score", 0),
                "rerank_score": d.metadata.get("rerank_score", 0),
            },
        }
        for d in docs_after
    ]
    topics_after = _extract_topics_from_docs(docs_after_data)
    topic_recall_after = _compute_topic_overlap(topics_after, expected_topics)
    p1_after = 1.0 if docs_after else 0.0

    if verbose:
        print(f"  AFTER reranking:")
        print(f"    Found: {len(docs_after)} docs")
        print(f"    P@1={p1_after:.2f}")
        print(f"    Topic recall={topic_recall_after:.2f}")

    reranking_improved = topic_recall_after > topic_recall_before
    reranking_degraded = topic_recall_after < topic_recall_before

    return RetrievalScore(
        case_id=case["id"],
        query=query,
        category="faq",
        expected_dieu=[],
        expected_topics=expected_topics,
        precision_at_1_before=p1_before,
        precision_at_3_before=p1_before,
        precision_at_5_before=p1_before,
        recall_at_3_before=topic_recall_before,
        recall_at_5_before=topic_recall_before,
        ndcg_at_3_before=p1_before,
        ndcg_at_5_before=p1_before,
        precision_at_1_after=p1_after,
        precision_at_3_after=p1_after,
        precision_at_5_after=p1_after,
        recall_at_3_after=topic_recall_after,
        recall_at_5_after=topic_recall_after,
        ndcg_at_3_after=p1_after,
        ndcg_at_5_after=p1_after,
        topic_recall_before=topic_recall_before,
        topic_recall_after=topic_recall_after,
        reranking_improved=reranking_improved,
        reranking_degraded=reranking_degraded,
        retrieval_ms=retrieval_ms,
        reranking_ms=reranking_ms,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main evaluation runner
# ─────────────────────────────────────────────────────────────────────────────

async def run_retrieval_evaluation(verbose: bool = False) -> List[RetrievalScore]:
    """Run comprehensive retrieval evaluation."""
    scores: List[RetrievalScore] = []

    print("\n" + "=" * 70)
    print("  RETRIEVAL ACCURACY EVALUATION (BEFORE vs AFTER RE-RANKING)")
    print("=" * 70)

    # ── Legal retrieval evaluation ───────────────────────────────────────
    print("\n📚 LEGAL RETRIEVAL EVALUATION")
    print("-" * 70)

    for i, case in enumerate(LEGAL_RETRIEVAL_GOLD, 1):
        print(f"\n[{i:02d}/{len(LEGAL_RETRIEVAL_GOLD)}] {case['id']}: {case['query'][:60]}")
        try:
            score = evaluate_legal_retrieval(case, verbose=verbose)
            scores.append(score)

            # Summary
            icon = "✅" if score.precision_at_1_after >= 1.0 else "⚠️" if score.precision_at_1_after >= 0.5 else "❌"
            print(f"  {icon} P@1: {score.precision_at_1_before:.2f} → {score.precision_at_1_after:.2f} | "
                  f"NDCG@3: {score.ndcg_at_3_before:.2f} → {score.ndcg_at_3_after:.2f}")

            if score.reranking_improved:
                print(f"  📈 Re-ranking IMPROVED results")
            elif score.reranking_degraded:
                print(f"  📉 Re-ranking DEGRADED results")

        except Exception as exc:
            print(f"  ❌ ERROR: {exc}")
            import traceback
            if verbose:
                traceback.print_exc()

    # ── FAQ retrieval evaluation ─────────────────────────────────────────
    print("\n📋 FAQ RETRIEVAL EVALUATION")
    print("-" * 70)

    for i, case in enumerate(FAQ_RETRIEVAL_GOLD, 1):
        print(f"\n[{i:02d}/{len(FAQ_RETRIEVAL_GOLD)}] {case['id']}: {case['query'][:60]}")
        try:
            score = evaluate_faq_retrieval(case, verbose=verbose)
            scores.append(score)

            icon = "✅" if score.topic_recall_after >= 0.8 else "⚠️" if score.topic_recall_after >= 0.5 else "❌"
            print(f"  {icon} Topic recall: {score.topic_recall_before:.2f} → {score.topic_recall_after:.2f}")

        except Exception as exc:
            print(f"  ❌ ERROR: {exc}")
            if verbose:
                import traceback
                traceback.print_exc()

    return scores


# ─────────────────────────────────────────────────────────────────────────────
# Report generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_report(scores: List[RetrievalScore]) -> Dict[str, Any]:
    """Generate comprehensive evaluation report."""
    legal_scores = [s for s in scores if s.category == "legal"]
    faq_scores = [s for s in scores if s.category == "faq"]

    def avg(scores_list, attr):
        return sum(getattr(s, attr) for s in scores_list) / len(scores_list) if scores_list else 0

    def count(scores_list, attr):
        return sum(1 for s in scores_list if getattr(s, attr)) if scores_list else 0

    report = {
        "summary": {
            "total_cases": len(scores),
            "legal_cases": len(legal_scores),
            "faq_cases": len(faq_scores),
        },
        "legal_retrieval": {
            "before_reranking": {
                "precision_at_1": avg(legal_scores, "precision_at_1_before"),
                "precision_at_3": avg(legal_scores, "precision_at_3_before"),
                "precision_at_5": avg(legal_scores, "precision_at_5_before"),
                "recall_at_3": avg(legal_scores, "recall_at_3_before"),
                "recall_at_5": avg(legal_scores, "recall_at_5_before"),
                "ndcg_at_3": avg(legal_scores, "ndcg_at_3_before"),
                "ndcg_at_5": avg(legal_scores, "ndcg_at_5_before"),
                "topic_recall": avg(legal_scores, "topic_recall_before"),
            },
            "after_reranking": {
                "precision_at_1": avg(legal_scores, "precision_at_1_after"),
                "precision_at_3": avg(legal_scores, "precision_at_3_after"),
                "precision_at_5": avg(legal_scores, "precision_at_5_after"),
                "recall_at_3": avg(legal_scores, "recall_at_3_after"),
                "recall_at_5": avg(legal_scores, "recall_at_5_after"),
                "ndcg_at_3": avg(legal_scores, "ndcg_at_3_after"),
                "ndcg_at_5": avg(legal_scores, "ndcg_at_5_after"),
                "topic_recall": avg(legal_scores, "topic_recall_after"),
            },
            "reranking_impact": {
                "improved_count": count(legal_scores, "reranking_improved"),
                "degraded_count": count(legal_scores, "reranking_degraded"),
            },
        },
        "faq_retrieval": {
            "before_reranking": {
                "precision_at_1": avg(faq_scores, "precision_at_1_before"),
                "topic_recall": avg(faq_scores, "topic_recall_before"),
            },
            "after_reranking": {
                "precision_at_1": avg(faq_scores, "precision_at_1_after"),
                "topic_recall": avg(faq_scores, "topic_recall_after"),
            },
            "reranking_impact": {
                "improved_count": count(faq_scores, "reranking_improved"),
                "degraded_count": count(faq_scores, "reranking_degraded"),
            },
        },
    }

    # Overall retrieval accuracy score (target >0.95)
    overall_accuracy = (
        report["legal_retrieval"]["after_reranking"]["precision_at_1"] * 0.4 +
        report["legal_retrieval"]["after_reranking"]["ndcg_at_3"] * 0.3 +
        report["legal_retrieval"]["after_reranking"]["topic_recall"] * 0.2 +
        report["faq_retrieval"]["after_reranking"]["topic_recall"] * 0.1
    )
    report["overall_accuracy"] = overall_accuracy
    report["meets_target"] = overall_accuracy >= 0.95

    return report


def print_report(report: Dict[str, Any]) -> None:
    """Print formatted evaluation report."""
    print("\n" + "=" * 70)
    print("  RETRIEVAL ACCURACY REPORT")
    print("=" * 70)

    print(f"\n📊 SUMMARY")
    print(f"  Total cases: {report['summary']['total_cases']}")
    print(f"  Legal cases: {report['summary']['legal_cases']}")
    print(f"  FAQ cases: {report['summary']['faq_cases']}")

    print(f"\n📚 LEGAL RETRIEVAL")
    print(f"  {'Metric':<20} {'Before':<12} {'After':<12} {'Change':<10}")
    print(f"  {'-'*54}")

    before = report["legal_retrieval"]["before_reranking"]
    after = report["legal_retrieval"]["after_reranking"]

    for metric in ["precision_at_1", "precision_at_3", "ndcg_at_3", "recall_at_3", "topic_recall"]:
        b = before[metric]
        a = after[metric]
        change = a - b
        icon = "📈" if change > 0.01 else "📉" if change < -0.01 else "➡️"
        print(f"  {metric:<20} {b:<12.3f} {a:<12.3f} {icon} {change:+.3f}")

    print(f"\n  Re-ranking impact:")
    impact = report["legal_retrieval"]["reranking_impact"]
    print(f"    ✅ Improved: {impact['improved_count']}")
    print(f"    ❌ Degraded: {impact['degraded_count']}")

    print(f"\n📋 FAQ RETRIEVAL")
    faq_before = report["faq_retrieval"]["before_reranking"]
    faq_after = report["faq_retrieval"]["after_reranking"]

    for metric in ["precision_at_1", "topic_recall"]:
        b = faq_before.get(metric, 0)
        a = faq_after.get(metric, 0)
        change = a - b
        icon = "📈" if change > 0.01 else "📉" if change < -0.01 else "➡️"
        print(f"  {metric:<20} {b:<12.3f} {a:<12.3f} {icon} {change:+.3f}")

    print(f"\n🎯 OVERALL RETRIEVAL ACCURACY")
    print(f"  Score: {report['overall_accuracy']:.3f} / 1.000")
    print(f"  Target: 0.950")
    if report["meets_target"]:
        print(f"  Status: ✅ TARGET MET")
    else:
        print(f"  Status: ❌ BELOW TARGET (need +{(0.95 - report['overall_accuracy']):.3f})")


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate retrieval accuracy with/without re-ranking")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--output", "-o", type=str, help="Save results to JSON file")
    args = parser.parse_args()

    # Ensure FAQ collection exists
    print("⏳ Initializing FAQ collection...")
    ensure_faq_collection()

    # Run evaluation
    scores = await run_retrieval_evaluation(verbose=args.verbose)

    # Generate report
    report = generate_report(scores)
    print_report(report)

    # Save results
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "report": report,
                "scores": [asdict(s) for s in scores],
            }, f, ensure_ascii=False, indent=2)
        print(f"\n💾 Results saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
