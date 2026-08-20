"""Comprehensive Retrieval Benchmark & RAGAS Evaluation Suite.

Evaluates the Vietnam Legal Agent on the 6-domain Golden Legal Benchmark:
1. Retrieval Metrics:
   - Hit Rate @ 1, 3, 5, 10
   - MRR (Mean Reciprocal Rank) @ 10
   - NDCG @ 3, 10
   - End-to-End Latency
2. RAGAS Metrics:
   - Faithfulness (Độ trung thực)
   - Answer Relevance (Độ trúng đích)
   - Context Precision (Độ chính xác ngữ cảnh)
   - Context Recall (Độ bao phủ ngữ cảnh)
   - Statutory Anchor Accuracy (Độ chuẩn xác căn cứ luật)
   - Composite RAGAS Score
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root in sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.epr_agent.eval.ragas_evaluator import evaluate_ragas_sample

from epr_agent.config import get_settings
from epr_agent.infra.llm_instances import get_llm_smart
from epr_agent.retrieval.ensemble_retrieval import retrieve_legal_ensemble
from epr_agent.retrieval.retrieval import close_qdrant_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ragas_benchmark")


def compute_ndcg(relevant_indices: list[int], k: int = 10) -> float:
    """Compute NDCG@k for a list of 1-based ranks of relevant documents."""
    if not relevant_indices:
        return 0.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank in relevant_indices if rank <= k)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(k, len(relevant_indices))))
    return dcg / ideal if ideal > 0 else 0.0


async def generate_answer(query: str, retrieved_docs: list[dict[str, Any]]) -> str:
    """Generate answer from retrieved context."""
    llm = get_llm_smart()
    context_blocks = []
    for i, doc in enumerate(retrieved_docs[:5], start=1):
        content = doc.get("page_content", "")
        meta = doc.get("metadata", {})
        dieu = meta.get("Dieu") or meta.get("article_title") or ""
        doc_title = meta.get("document_title") or meta.get("law_name") or ""
        header = f"[Tài liệu {i}] {dieu} - {doc_title}".strip()
        context_blocks.append(f"{header}\n{content}")

    context_str = "\n\n---\n\n".join(context_blocks)
    prompt = (
        "Bạn là Trợ lý Pháp luật Việt Nam chuẩn xác và đáng tin cậy. "
        "Hãy căn cứ VÀO CÁC ĐIỀU KHOẢN ĐƯỢC CẤP DƯỚI ĐÂY để trả lời câu hỏi của người dùng. "
        "Trích dẫn rõ ràng tên Điều, Khoản và Văn bản pháp luật làm căn cứ. "
        "Nếu không có đủ căn cứ, hãy nêu rõ giới hạn thông tin.\n\n"
        f"CĂN CỨ PHÁP LUẬT:\n{context_str}\n\n"
        f"CÂU HỎI:\n{query}\n\n"
        "CÂU TRẢ LỜI:"
    )

    response = await llm.ainvoke(prompt)
    return str(response.content if hasattr(response, "content") else response)


async def run_benchmark():
    settings = get_settings()
    benchmark_file = ROOT / "data" / "eval" / "golden_legal_benchmark.json"
    if not benchmark_file.exists():
        logger.error(f"Benchmark file not found at {benchmark_file}")
        return

    data = json.loads(benchmark_file.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    logger.info(f"Loaded {len(cases)} benchmark cases across {len(data.get('domains', []))} domains.")

    # Storage for results
    results_by_case = []
    domain_aggregates: dict[str, list[dict[str, Any]]] = {}

    start_suite = time.perf_counter()

    print("\n" + "="*80)
    print("🚀 VIETNAM LEGAL AGENT - BENCHMARK & RAGAS EVALUATION SUITE")
    print(f"Collection: {settings.law_collection} | Model: {settings.local_embedding_model or settings.embedding_model}")
    print(f"Total Test Cases: {len(cases)}")
    print("="*80 + "\n")

    for idx, case in enumerate(cases, start=1):
        case_id = case["id"]
        domain = case.get("domain", "general")
        query = case["query"]
        expected_anchors = case.get("expected_anchors", [])

        print(f"[{idx:02d}/{len(cases):02d}] Domain: {domain:<25} | Case: {case_id}")
        print(f"   Query: {query}")

        t0 = time.perf_counter()
        
        # 1. Retrieval
        try:
            raw_docs = await asyncio.to_thread(retrieve_legal_ensemble, query=query, k=10)
        except Exception as exc:  # noqa: BLE001 - one failed retrieval must not abort the benchmark report
            logger.error(f"Retrieval error on {case_id}: {exc}")
            raw_docs = []

        t_retrieval = time.perf_counter() - t0

        # Standardize retrieved docs for RAGAS evaluation
        formatted_docs = []
        for d in raw_docs:
            formatted_docs.append({
                "page_content": getattr(d, "page_content", ""),
                "metadata": getattr(d, "metadata", {})
            })

        # Calculate retrieval metrics (Hit@K, MRR, NDCG)
        ranks = []
        for rank_idx, doc in enumerate(formatted_docs, start=1):
            doc_str = f"{doc['page_content']} {json.dumps(doc['metadata'], ensure_ascii=False)}".lower()
            if any(anchor.lower() in doc_str for anchor in expected_anchors):
                ranks.append(rank_idx)

        hit_at_1 = 1 if (ranks and ranks[0] == 1) else 0
        hit_at_3 = 1 if (ranks and any(r <= 3 for r in ranks)) else 0
        hit_at_5 = 1 if (ranks and any(r <= 5 for r in ranks)) else 0
        hit_at_10 = 1 if (ranks and any(r <= 10 for r in ranks)) else 0
        mrr_10 = (1.0 / ranks[0]) if (ranks and ranks[0] <= 10) else 0.0
        ndcg_3 = compute_ndcg(ranks, k=3)
        ndcg_10 = compute_ndcg(ranks, k=10)

        # 2. Generation
        answer = await generate_answer(query, formatted_docs)
        t_total = time.perf_counter() - t0

        # 3. RAGAS Evaluation
        ragas_res = await evaluate_ragas_sample(
            query=query,
            answer=answer,
            retrieved_docs=formatted_docs,
            expected_anchors=expected_anchors,
            sample_id=case_id,
            pass_threshold=0.80
        )

        case_summary = {
            "id": case_id,
            "domain": domain,
            "query": query,
            "latency_retrieval_ms": round(t_retrieval * 1000, 1),
            "latency_total_s": round(t_total, 2),
            "retrieval": {
                "hit_at_1": hit_at_1,
                "hit_at_3": hit_at_3,
                "hit_at_5": hit_at_5,
                "hit_at_10": hit_at_10,
                "mrr_10": round(mrr_10, 4),
                "ndcg_3": round(ndcg_3, 4),
                "ndcg_10": round(ndcg_10, 4),
                "ranks": ranks,
            },
            "ragas": {
                "faithfulness": ragas_res.faithfulness,
                "answer_relevance": ragas_res.answer_relevance,
                "context_precision": ragas_res.context_precision,
                "context_recall": ragas_res.context_recall,
                "anchor_accuracy": ragas_res.anchor_accuracy,
                "overall_score": ragas_res.overall_ragas_score,
                "passed": ragas_res.passed_gate,
            },
            "answer_preview": answer[:150].replace("\n", " ") + "..."
        }

        print(f"   -> Hit@1: {hit_at_1} | Hit@3: {hit_at_3} | Hit@5: {hit_at_5} | MRR@10: {mrr_10:.2f} | NDCG@10: {ndcg_10:.2f}")
        print(f"   -> RAGAS: Faithfulness: {ragas_res.faithfulness:.2f} | Relevance: {ragas_res.answer_relevance:.2f} | Overall: {ragas_res.overall_ragas_score:.2f} | Passed: {ragas_res.passed_gate}")
        print(f"   -> Latency: {t_retrieval*1000:.0f}ms (Retrieval) | {t_total:.1f}s (End-to-End)\n")

        results_by_case.append(case_summary)
        if domain not in domain_aggregates:
            domain_aggregates[domain] = []
        domain_aggregates[domain].append(case_summary)

    total_suite_time = time.perf_counter() - start_suite

    # Aggregate Metrics
    n = len(results_by_case)
    avg_hit_1 = sum(r["retrieval"]["hit_at_1"] for r in results_by_case) / n
    avg_hit_3 = sum(r["retrieval"]["hit_at_3"] for r in results_by_case) / n
    avg_hit_5 = sum(r["retrieval"]["hit_at_5"] for r in results_by_case) / n
    avg_hit_10 = sum(r["retrieval"]["hit_at_10"] for r in results_by_case) / n
    avg_mrr_10 = sum(r["retrieval"]["mrr_10"] for r in results_by_case) / n
    avg_ndcg_3 = sum(r["retrieval"]["ndcg_3"] for r in results_by_case) / n
    avg_ndcg_10 = sum(r["retrieval"]["ndcg_10"] for r in results_by_case) / n

    avg_faith = sum(r["ragas"]["faithfulness"] for r in results_by_case) / n
    avg_relevance = sum(r["ragas"]["answer_relevance"] for r in results_by_case) / n
    avg_precision = sum(r["ragas"]["context_precision"] for r in results_by_case) / n
    avg_recall = sum(r["ragas"]["context_recall"] for r in results_by_case) / n
    avg_anchor = sum(r["ragas"]["anchor_accuracy"] for r in results_by_case) / n
    avg_overall_ragas = sum(r["ragas"]["overall_score"] for r in results_by_case) / n
    pass_rate = sum(1 for r in results_by_case if r["ragas"]["passed"]) / n

    avg_retrieval_lat = sum(r["latency_retrieval_ms"] for r in results_by_case) / n
    avg_total_lat = sum(r["latency_total_s"] for r in results_by_case) / n

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "collection": settings.law_collection,
        "embedding_model": settings.local_embedding_model or settings.embedding_model,
        "sample_size": n,
        "total_suite_duration_s": round(total_suite_time, 2),
        "overall_retrieval_metrics": {
            "hit_at_1": round(avg_hit_1, 4),
            "hit_at_3": round(avg_hit_3, 4),
            "hit_at_5": round(avg_hit_5, 4),
            "hit_at_10": round(avg_hit_10, 4),
            "mrr_at_10": round(avg_mrr_10, 4),
            "ndcg_at_3": round(avg_ndcg_3, 4),
            "ndcg_at_10": round(avg_ndcg_10, 4),
            "avg_retrieval_latency_ms": round(avg_retrieval_lat, 1),
        },
        "overall_ragas_metrics": {
            "faithfulness": round(avg_faith, 4),
            "answer_relevance": round(avg_relevance, 4),
            "context_precision": round(avg_precision, 4),
            "context_recall": round(avg_recall, 4),
            "statutory_anchor_accuracy": round(avg_anchor, 4),
            "composite_ragas_score": round(avg_overall_ragas, 4),
            "pass_rate": round(pass_rate, 4),
            "avg_e2e_latency_s": round(avg_total_lat, 2),
        },
        "domain_breakdown": {},
        "case_details": results_by_case,
    }

    # Domain-specific summaries
    for dom, cases_in_dom in domain_aggregates.items():
        m_count = len(cases_in_dom)
        report["domain_breakdown"][dom] = {
            "count": m_count,
            "hit_at_3": round(sum(c["retrieval"]["hit_at_3"] for c in cases_in_dom) / m_count, 4),
            "mrr_at_10": round(sum(c["retrieval"]["mrr_10"] for c in cases_in_dom) / m_count, 4),
            "ndcg_at_10": round(sum(c["retrieval"]["ndcg_10"] for c in cases_in_dom) / m_count, 4),
            "faithfulness": round(sum(c["ragas"]["faithfulness"] for c in cases_in_dom) / m_count, 4),
            "answer_relevance": round(sum(c["ragas"]["answer_relevance"] for c in cases_in_dom) / m_count, 4),
            "composite_ragas_score": round(sum(c["ragas"]["overall_score"] for c in cases_in_dom) / m_count, 4),
            "pass_rate": round(sum(1 for c in cases_in_dom if c["ragas"]["passed"]) / m_count, 4),
        }

    out_path = ROOT / "data" / "eval" / "ragas_benchmark_results.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Saved evaluation report to {out_path}")

    # Print Final Summary Banner
    print("\n" + "="*80)
    print("📊 BENCHMARK & RAGAS EVALUATION SUMMARY")
    print("="*80)
    print(f"Total Evaluated Scenarios: {n}")
    print(f"Total Execution Time:      {total_suite_time:.1f}s")
    print("\n[1] RETRIEVAL METRICS (Dense 1024-d + BM25 + CrossEncoder):")
    print(f"   • Hit Rate @ 1 (P@1):     {avg_hit_1 * 100:.1f}%")
    print(f"   • Hit Rate @ 3 (Top-3):   {avg_hit_3 * 100:.1f}%")
    print(f"   • Hit Rate @ 5 (Top-5):   {avg_hit_5 * 100:.1f}%")
    print(f"   • Hit Rate @ 10:          {avg_hit_10 * 100:.1f}%")
    print(f"   • MRR @ 10:               {avg_mrr_10:.4f}")
    print(f"   • NDCG @ 3:               {avg_ndcg_3:.4f}")
    print(f"   • NDCG @ 10:              {avg_ndcg_10:.4f}")
    print(f"   • Avg Retrieval Latency:  {avg_retrieval_lat:.1f}ms")

    print("\n[2] RAGAS QUANTITATIVE DIMENSIONS (Vietnamese Legal QA):")
    print(f"   • Faithfulness (Độ trung thực):             {avg_faith * 100:.1f}%")
    print(f"   • Answer Relevance (Độ trúng đích):         {avg_relevance * 100:.1f}%")
    print(f"   • Context Precision (Độ chính xác ngữ cảnh): {avg_precision * 100:.1f}%")
    print(f"   • Context Recall (Độ bao phủ căn cứ luật):  {avg_recall * 100:.1f}%")
    print(f"   • Statutory Anchor Accuracy (Độ chuẩn xác): {avg_anchor * 100:.1f}%")
    print(f"   • Composite RAGAS Score:                    {avg_overall_ragas * 100:.1f}%")
    print(f"   • Gate Pass Rate (>=0.80):                  {pass_rate * 100:.1f}%")

    print("\n[3] DOMAIN-SPECIFIC BREAKDOWN:")
    print(f"{'Domain':<28} | {'Hit@3':<7} | {'MRR@10':<7} | {'NDCG@10':<7} | {'Faith':<7} | {'Relevance':<9} | {'RAGAS':<7} | {'Pass%':<6}")
    print("-" * 92)
    for dom, d_metrics in report["domain_breakdown"].items():
        print(
            f"{dom:<28} | "
            f"{d_metrics['hit_at_3']*100:>5.1f}% | "
            f"{d_metrics['mrr_at_10']:>7.4f} | "
            f"{d_metrics['ndcg_at_10']:>7.4f} | "
            f"{d_metrics['faithfulness']*100:>5.1f}% | "
            f"{d_metrics['answer_relevance']*100:>7.1f}% | "
            f"{d_metrics['composite_ragas_score']*100:>5.1f}% | "
            f"{d_metrics['pass_rate']*100:>5.1f}%"
        )
    print("="*80 + "\n")

    close_qdrant_client()


if __name__ == "__main__":
    asyncio.run(run_benchmark())
