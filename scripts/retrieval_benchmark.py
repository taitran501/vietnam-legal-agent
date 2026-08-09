"""Freeze and compare retrieval candidates without overwriting a collection.

Default mode creates only a corpus manifest. ``--run-retrieval`` evaluates the
active collection against a small, versioned legal-anchor suite and writes the
same metric fields needed for promotion: P@1, NDCG@3, Recall@5 and explicit
article hit@3.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

LEGAL_CASES = [
    {"id": "article_77", "query": "Điều 77 quy định gì về trách nhiệm tái chế?", "expected": ["Điều 77"]},
    {"id": "article_78", "query": "Điều 78 quy định gì?", "expected": ["Điều 78"]},
    {"id": "article_80", "query": "Điều kiện để cơ sở tái chế được hoạt động", "expected": ["Điều 80"]},
    {"id": "article_81", "query": "Điều 81 quy định về trách nhiệm xử lý chất thải", "expected": ["Điều 81"]},
    {"id": "article_82", "query": "Điều 82 quy định gì về đóng góp tài chính", "expected": ["Điều 82"]},
]


def load_json(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else list(raw.get("meta", []))


def corpus_manifest(law_path: Path, faq_path: Path) -> dict[str, Any]:
    law_bytes = law_path.read_bytes()
    faq_bytes = faq_path.read_bytes()
    laws = load_json(law_path)
    faqs = load_json(faq_path)
    anchors = [str(item.get("Điều") or item.get("Dieu") or "").strip() for item in laws]
    return {
        "manifest_version": 1,
        "corpus_version": f"law-{hashlib.sha256(law_bytes).hexdigest()[:12]}",
        "law_records": len(laws),
        "faq_records": len(faqs),
        "law_sha256": hashlib.sha256(law_bytes).hexdigest(),
        "faq_sha256": hashlib.sha256(faq_bytes).hexdigest(),
        "legal_anchor_count": len([anchor for anchor in anchors if anchor]),
        "chunking_strategy": "sliding_window",
        "metrics": None,
        "notes": "Metrics are populated only by --run-retrieval against a named collection.",
    }


def _anchor(document: Any) -> str:
    metadata = getattr(document, "metadata", {}) or {}
    return str(metadata.get("Dieu") or metadata.get("Điều") or "")


def _matches(value: str, expected: list[str]) -> bool:
    return any(target.lower() in value.lower() for target in expected)


async def run_metrics() -> dict[str, float]:
    from backend.core.retrieval import retrieve_legal_async

    p1_values: list[float] = []
    recall5_values: list[float] = []
    ndcg3_values: list[float] = []
    explicit_hit3_values: list[float] = []
    for case in LEGAL_CASES:
        docs = await retrieve_legal_async(case["query"])
        ranked = [_anchor(document) for document in docs]
        relevance = [_matches(anchor, case["expected"]) for anchor in ranked]
        p1_values.append(float(bool(relevance and relevance[0])))
        recall5_values.append(float(any(relevance[:5])))
        dcg = sum((1.0 / math.log2(index + 2)) for index, relevant in enumerate(relevance[:3]) if relevant)
        ndcg3_values.append(dcg)  # one expected article per benchmark case
        if case["query"].lower().startswith("điều"):
            explicit_hit3_values.append(float(any(relevance[:3])))
    return {
        "p_at_1": round(sum(p1_values) / len(p1_values), 4),
        "ndcg_at_3": round(sum(ndcg3_values) / len(ndcg3_values), 4),
        "recall_at_5": round(sum(recall5_values) / len(recall5_values), 4),
        "explicit_article_hit_at_3": round(sum(explicit_hit3_values) / len(explicit_hit3_values), 4),
        "query_count": float(len(LEGAL_CASES)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "retrieval" / "baseline_manifest.json")
    parser.add_argument("--run-retrieval", action="store_true")
    parser.add_argument("--collection", default="", help="Recorded only; set LAW_COLLECTION before execution.")
    parser.add_argument("--chunking-strategy", default="sliding_window")
    args = parser.parse_args()

    manifest = corpus_manifest(ROOT / "data" / "law.json", ROOT / "data" / "faq.json")
    manifest["chunking_strategy"] = args.chunking_strategy
    if args.collection:
        manifest["collection"] = args.collection
    if args.run_retrieval:
        manifest["metrics"] = asyncio.run(run_metrics())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
