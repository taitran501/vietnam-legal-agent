"""Freeze, audit, and compare EPR retrieval candidates.

The default benchmark is deterministic and offline: it evaluates a BM25-style
lexical baseline against versioned legal-anchor cases. ``--run-retrieval`` adds
live hybrid metrics from the configured Qdrant/OpenAI stack without replacing
the reproducible offline record.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

LEGAL_CASES = [
    {"id": "article_77", "query": "Điều 77 quy định gì về trách nhiệm tái chế?", "expected": ["Điều 77"]},
    {"id": "article_78", "query": "Điều 78 quy định gì?", "expected": ["Điều 78"]},
    {"id": "article_80", "query": "Điều 80 quy định về đăng ký kế hoạch tái chế", "expected": ["Điều 80"]},
    {"id": "article_81", "query": "Điều 81 quy định về đóng góp tài chính", "expected": ["Điều 81"]},
    {"id": "article_82", "query": "Điều 82 quy định gì về hỗ trợ tái chế", "expected": ["Điều 82"]},
    {"id": "topic_77", "query": "đối tượng và lộ trình thực hiện trách nhiệm tái chế", "expected": ["Điều 77"]},
    {"id": "topic_78", "query": "tỷ lệ và quy cách tái chế bắt buộc", "expected": ["Điều 78"]},
    {"id": "topic_79", "query": "các hình thức thực hiện trách nhiệm tái chế", "expected": ["Điều 79"]},
    {"id": "topic_80", "query": "đăng ký kế hoạch và báo cáo kết quả tái chế", "expected": ["Điều 80"]},
    {"id": "topic_81", "query": "công thức F bằng R nhân V nhân Fs", "expected": ["Điều 81"]},
    {"id": "topic_82", "query": "hỗ trợ hoạt động tái chế sản phẩm bao bì", "expected": ["Điều 82"]},
    {"id": "topic_83", "query": "đối tượng đóng góp tài chính hỗ trợ xử lý chất thải", "expected": ["Điều 83"]},
    {"id": "topic_84", "query": "kê khai đóng góp tài chính hỗ trợ xử lý chất thải", "expected": ["Điều 84"]},
    {"id": "topic_85", "query": "thực hiện hỗ trợ hoạt động xử lý chất thải", "expected": ["Điều 85"]},
    {"id": "topic_86", "query": "cung cấp thông tin về sản phẩm và bao bì", "expected": ["Điều 86"]},
    {"id": "topic_87", "query": "hệ thống thông tin EPR quốc gia", "expected": ["Điều 87"]},
]

_TOKEN_RE = re.compile(r"[\wđĐ]+", re.UNICODE)
_ARTICLE_RE = re.compile(r"\bđiều\s+\d+[a-zđ]?\b", re.IGNORECASE)
_ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200F\uFEFF]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_STOP_WORDS = {
    "và",
    "của",
    "có",
    "là",
    "về",
    "cho",
    "được",
    "theo",
    "những",
    "gì",
    "các",
    "một",
    "trong",
    "đối",
    "với",
}


def load_json(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else list(raw.get("meta", []))


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall((text or "").lower()) if len(token) > 1 and token not in _STOP_WORDS]


def _anchor(record: dict[str, Any]) -> str:
    return str(record.get("Parent_Dieu") or record.get("Điều") or record.get("Dieu") or "").strip()


def _search_text(record: dict[str, Any]) -> str:
    return "\n".join(
        str(record.get(key) or "")
        for key in ("Parent_Dieu", "Điều", "Dieu", "Chương", "Chuong", "Mục", "Muc", "Hierarchy", "Text")
    )


def _offline_records(laws: list[dict[str, Any]], chunking_strategy: str) -> list[dict[str, Any]]:
    if chunking_strategy != "legal_structure_v1":
        return laws
    from scripts.structural_chunking import structural_chunk_articles

    records, _, _ = structural_chunk_articles(laws, [""] * len(laws))
    return records


def _rank_bm25(query: str, records: list[dict[str, Any]], limit: int = 10) -> list[str]:
    tokenized = [_tokens(_search_text(record)) for record in records]
    query_tokens = _tokens(query)
    if not tokenized or not query_tokens:
        return []
    document_count = len(tokenized)
    average_length = sum(len(tokens) for tokens in tokenized) / max(1, document_count)
    document_frequency = Counter(token for tokens in tokenized for token in set(tokens))
    k1 = 1.5
    b = 0.75
    scores: list[tuple[float, int]] = []
    for index, tokens in enumerate(tokenized):
        frequencies = Counter(tokens)
        length = len(tokens)
        score = 0.0
        for token in query_tokens:
            frequency = frequencies.get(token, 0)
            if not frequency:
                continue
            df = document_frequency[token]
            idf = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1 - b + b * length / max(1.0, average_length))
            score += idf * frequency * (k1 + 1) / denominator
        explicit = _ARTICLE_RE.findall(query)
        anchor_lower = _anchor(records[index]).lower()
        if any(article.lower() in anchor_lower for article in explicit):
            score += 100.0
        if score > 0:
            scores.append((score, index))
    scores.sort(key=lambda item: (-item[0], item[1]))
    ranked: list[str] = []
    seen: set[str] = set()
    for _, index in scores:
        anchor = _anchor(records[index])
        normalized = anchor.lower()
        if not anchor or normalized in seen:
            continue
        seen.add(normalized)
        ranked.append(anchor)
        if len(ranked) >= limit:
            break
    return ranked


def _matches(value: str, expected: list[str]) -> bool:
    return any(target.lower() in value.lower() for target in expected)


def _metrics_from_rankings(rankings: list[tuple[dict[str, Any], list[str]]]) -> dict[str, float | int | str]:
    p1_values: list[float] = []
    recall5_values: list[float] = []
    ndcg3_values: list[float] = []
    explicit_hit3_values: list[float] = []
    for case, ranked in rankings:
        relevance = [_matches(anchor, case["expected"]) for anchor in ranked]
        p1_values.append(float(bool(relevance and relevance[0])))
        recall5_values.append(float(any(relevance[:5])))
        dcg = sum((1.0 / math.log2(index + 2)) for index, relevant in enumerate(relevance[:3]) if relevant)
        ndcg3_values.append(dcg)
        if _ARTICLE_RE.search(case["query"]):
            explicit_hit3_values.append(float(any(relevance[:3])))
    count = max(1, len(rankings))
    return {
        "protocol": "offline_bm25_legal_anchor_v1",
        "p_at_1": round(sum(p1_values) / count, 4),
        "ndcg_at_3": round(sum(ndcg3_values) / count, 4),
        "recall_at_5": round(sum(recall5_values) / count, 4),
        "explicit_article_hit_at_3": round(sum(explicit_hit3_values) / max(1, len(explicit_hit3_values)), 4),
        "query_count": len(rankings),
    }


def offline_metrics(laws: list[dict[str, Any]], chunking_strategy: str) -> dict[str, float | int | str]:
    records = _offline_records(laws, chunking_strategy)
    rankings = [(case, _rank_bm25(case["query"], records)) for case in LEGAL_CASES]
    return _metrics_from_rankings(rankings)


def audit_records(records: list[dict[str, Any]], chunking_strategy: str) -> dict[str, Any]:
    required = ["Text"] if chunking_strategy != "legal_structure_v1" else [
        "Text",
        "Parent_Dieu",
        "Hierarchy",
        "Source_Start",
        "Source_End",
        "Original_Text",
    ]
    missing = Counter()
    hashes = Counter()
    zero_width = 0
    control_chars = 0
    anchors: set[str] = set()
    for record in records:
        for key in required:
            if record.get(key) in (None, ""):
                missing[key] += 1
        text = str(record.get("Text") or "")
        if _ZERO_WIDTH_RE.search(text):
            zero_width += 1
        if _CONTROL_RE.search(text):
            control_chars += 1
        normalized = " ".join(text.lower().split())
        provenance = f"{_anchor(record).lower()}|{str(record.get('Hierarchy') or '').lower()}|{normalized}"
        if normalized:
            hashes[hashlib.sha256(provenance.encode("utf-8")).hexdigest()] += 1
        if _anchor(record):
            anchors.add(_anchor(record).lower())
    duplicates = sum(count - 1 for count in hashes.values() if count > 1)
    return {
        "records": len(records),
        "unique_legal_anchors": len(anchors),
        "schema_missing": dict(missing),
        "exact_duplicate_records": duplicates,
        "hygiene": {"zero_width": zero_width, "control_chars": control_chars},
        "quality_summary": {
            "schema_ok": not missing,
            "duplicates_ok": duplicates == 0,
            "hygiene_ok": zero_width == 0 and control_chars == 0,
            "legal_anchor_coverage_ok": len(anchors) > 0,
        },
    }


def promotion_decision(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    baseline_metrics = baseline.get("metrics") or {}
    candidate_metrics = candidate.get("metrics") or {}
    metric_names = ("p_at_1", "ndcg_at_3", "recall_at_5")
    no_regression = all(
        float(candidate_metrics.get(name, 0.0)) >= float(baseline_metrics.get(name, 0.0))
        for name in metric_names
    )
    explicit_ok = float(candidate_metrics.get("explicit_article_hit_at_3", 0.0)) == 1.0
    quality = (candidate.get("audit") or {}).get("quality_summary") or {}
    audit_ok = all(bool(quality.get(name)) for name in (
        "schema_ok",
        "duplicates_ok",
        "hygiene_ok",
        "legal_anchor_coverage_ok",
    ))
    checks = {
        "offline_no_metric_regression": no_regression,
        "offline_explicit_article_hit_at_3_is_100_percent": explicit_ok,
        "candidate_audit_passed": audit_ok,
    }
    offline_gate_passed = all(checks.values())
    baseline_live = baseline.get("live_metrics") or {}
    candidate_live = candidate.get("live_metrics") or {}
    live_metrics_available = bool(baseline_live and candidate_live)
    live_no_regression = live_metrics_available and all(
        float(candidate_live.get(name, 0.0)) >= float(baseline_live.get(name, 0.0))
        for name in metric_names
    )
    live_explicit_ok = (
        live_metrics_available
        and float(candidate_live.get("explicit_article_hit_at_3", 0.0)) == 1.0
    )
    collection_audit = candidate.get("collection_audit") or {}
    collection_quality = collection_audit.get("quality_summary") or {}
    collection_audit_available = bool(collection_audit)
    collection_audit_passed = collection_audit_available and all(
        bool(collection_quality.get(name))
        for name in (
            "schema_ok",
            "hygiene_ok",
            "duplicate_ok",
            "coverage_phu_luc_xxii_ok",
        )
    )
    checks.update(
        {
            "live_hybrid_metrics_available": live_metrics_available,
            "live_hybrid_no_metric_regression": live_no_regression,
            "live_hybrid_explicit_article_hit_at_3_is_100_percent": live_explicit_ok,
            "live_collection_audit_available": collection_audit_available,
            "live_collection_audit_passed": collection_audit_passed,
        }
    )
    promotable = all(checks.values())
    if promotable:
        blocking_reason = ""
    elif not live_metrics_available:
        blocking_reason = "live_hybrid_metrics_required"
    elif not collection_audit_passed:
        blocking_reason = "live_collection_audit_required_or_failed"
    else:
        blocking_reason = "quality_gate_failed"
    return {
        "offline_gate_passed": offline_gate_passed,
        "promotable": promotable,
        "blocking_reason": blocking_reason,
        "checks": checks,
    }


def corpus_manifest(law_path: Path, faq_path: Path, chunking_strategy: str = "sliding_window") -> dict[str, Any]:
    law_bytes = law_path.read_bytes()
    faq_bytes = faq_path.read_bytes()
    laws = load_json(law_path)
    faqs = load_json(faq_path)
    indexed_records = _offline_records(laws, chunking_strategy)
    anchors = [_anchor(item) for item in laws]
    return {
        "manifest_version": 2,
        "corpus_version": f"law-{hashlib.sha256(law_bytes).hexdigest()[:12]}",
        "law_records": len(laws),
        "faq_records": len(faqs),
        "indexed_records": len(indexed_records),
        "law_sha256": hashlib.sha256(law_bytes).hexdigest(),
        "faq_sha256": hashlib.sha256(faq_bytes).hexdigest(),
        "legal_anchor_count": len([anchor for anchor in anchors if anchor]),
        "chunking_strategy": chunking_strategy,
        "metrics": offline_metrics(laws, chunking_strategy),
        "audit": audit_records(indexed_records, chunking_strategy),
        "live_metrics": None,
        "notes": "Offline metrics are deterministic. live_metrics require a named configured collection.",
    }


def _live_anchor(document: Any) -> str:
    metadata = getattr(document, "metadata", {}) or {}
    return str(metadata.get("Parent_Dieu") or metadata.get("Dieu") or metadata.get("Điều") or "")


def select_live_cases(query_budget: int) -> list[dict[str, Any]]:
    """Apply an explicit hard cap to variable-cost live retrieval calls."""

    if query_budget < 1:
        raise ValueError("Live retrieval query budget must be at least 1")
    return LEGAL_CASES[: min(query_budget, len(LEGAL_CASES))]


async def run_live_metrics(cases: list[dict[str, Any]]) -> dict[str, float | int | str]:
    from epr_agent.retrieval.retrieval import retrieve_legal_async

    rankings: list[tuple[dict[str, Any], list[str]]] = []
    for case in cases:
        documents = await retrieve_legal_async(case["query"])
        rankings.append((case, [_live_anchor(document) for document in documents]))
    metrics = _metrics_from_rankings(rankings)
    metrics["protocol"] = "live_dense_bm25_rerank_v1"
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "retrieval" / "baseline_manifest.json")
    parser.add_argument("--run-retrieval", action="store_true")
    parser.add_argument(
        "--query-budget",
        type=int,
        default=int(os.getenv("LIVE_EVAL_QUERY_BUDGET", str(len(LEGAL_CASES)))),
        help="Hard cap for live retrieval calls (default: LIVE_EVAL_QUERY_BUDGET or all cases).",
    )
    parser.add_argument("--collection", default="", help="Recorded only; set LAW_COLLECTION before execution.")
    parser.add_argument(
        "--collection-audit",
        type=Path,
        help="Audit JSON for the exact named collection; required for production promotion.",
    )
    parser.add_argument("--chunking-strategy", default="sliding_window")
    parser.add_argument("--baseline", type=Path, help="Optional baseline manifest used to compute the promotion gate.")
    args = parser.parse_args()

    manifest = corpus_manifest(
        ROOT / "data" / "law.json",
        ROOT / "data" / "faq.json",
        args.chunking_strategy,
    )
    if args.collection:
        manifest["collection"] = args.collection
    if args.collection_audit:
        collection_audit = json.loads(args.collection_audit.read_text(encoding="utf-8"))
        if args.collection and collection_audit.get("collection") != args.collection:
            raise ValueError("Collection audit does not match --collection")
        manifest["collection_audit"] = collection_audit
        manifest["collection_points"] = int(collection_audit.get("points_total", 0))
    if args.run_retrieval:
        try:
            manifest["live_metrics"] = asyncio.run(run_live_metrics(select_live_cases(args.query_budget)))
        finally:
            from epr_agent.retrieval.retrieval import close_qdrant_client

            close_qdrant_client()
    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        manifest["promotion"] = promotion_decision(baseline, manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
