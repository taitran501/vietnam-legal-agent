"""
Lightweight retrieval trace tool for debugging legal candidate generation.

Examples:
    python -m tests.eval.retrieval_trace --query "Điều 40 quy định gì?"
    python -m tests.eval.retrieval_trace --query "nhập khẩu hàng hóa có chứa chất ô nhiễm khó phân hủy cần làm thủ tục gì trước khi bán ra thị trường"
    python -m tests.eval.retrieval_trace --from-cases
    python -m tests.eval.retrieval_trace --from-cases --category legal
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.retrieval import retrieve_legal  # noqa: E402


def _format_doc(doc: Any, rank: int) -> str:
    meta = doc.metadata
    dieu = meta.get("Dieu", "")
    chuong = meta.get("Chuong", "")
    source = meta.get("retrieval_source", "")
    semantic = meta.get("semantic_score", 0)
    lexical = meta.get("lexical_score", 0)
    rerank = meta.get("rerank_score", 0)
    explicit = meta.get("explicit_match", False)
    breakdown = meta.get("retrieval_debug", {}).get("breakdown", {})
    snippet = " ".join(doc.page_content.split())[:220]
    breakdown_text = ""
    if breakdown:
        breakdown_text = (
            "    breakdown="
            f"overlap={breakdown.get('overlap', 0):.4f} "
            f"metadata={breakdown.get('metadata', 0):.4f} "
            f"tf={breakdown.get('tf', 0):.4f} "
            f"phrase={breakdown.get('phrase', 0):.4f} "
            f"ordered={breakdown.get('ordered_phrase', 0):.4f} "
            f"rare={breakdown.get('rare_token', 0):.4f} "
            f"salient={breakdown.get('salient_token', 0):.4f} "
            f"lead={breakdown.get('lead', 0):.4f} "
            f"semantic={breakdown.get('semantic', 0):.4f} "
            f"lexical={breakdown.get('lexical', 0):.4f}\n"
        )
    return (
        f"[{rank}] {dieu or '(không có Điều)'}\n"
        f"    source={source or '-'} semantic={semantic:.4f} lexical={lexical:.4f} "
        f"rerank={rerank:.4f} explicit={explicit}\n"
        f"{breakdown_text}"
        f"    chuong={chuong or '-'}\n"
        f"    snippet={snippet}\n"
    )


def _load_case_queries(category: str | None = None) -> Iterable[tuple[str, str]]:
    path = ROOT / "tests" / "eval" / "test_cases.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for case in data.get("cases", []):
        if category and case.get("category") != category:
            continue
        yield case["id"], case["query"]


def trace_query(query: str, label: str | None = None) -> str:
    docs = retrieve_legal(query)
    header = f"=== {label or 'query'} ===\n{query}\n"
    if not docs:
        return header + "  (no docs)\n"

    body = "\n".join(_format_doc(doc, idx + 1) for idx, doc in enumerate(docs[:5]))
    return header + body


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug legal retrieval ranking.")
    parser.add_argument("--query", action="append", help="One or more queries to trace")
    parser.add_argument(
        "--from-cases",
        action="store_true",
        help="Load queries from tests/eval/test_cases.json",
    )
    parser.add_argument(
        "--category",
        choices=["faq", "legal", "edge", "web_search", "chitchat"],
        help="Optional category filter when using --from-cases",
    )
    args = parser.parse_args()

    outputs: list[str] = []

    if args.query:
        for idx, query in enumerate(args.query, 1):
            outputs.append(trace_query(query, f"query_{idx}"))

    if args.from_cases:
        for case_id, query in _load_case_queries(args.category):
            outputs.append(trace_query(query, case_id))

    if not outputs:
        parser.error("Provide --query or --from-cases")

    print("\n".join(outputs))


if __name__ == "__main__":
    main()
