"""
EDA for data/law.json — character & token distributions for chunking plans.

Run from repo root (epr_chatbot/):
    python -m scripts.eda_law
    python -m scripts.eda_law --model gpt-4o
    python -m scripts.eda_law --bins 256 512 1024 2048 4096

Token counts use tiktoken (same stack as backend/core/retrieval.py).
Default model is text-embedding-3-small so token sizes align with embedding limits.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

import tiktoken

# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
DEFAULT_LAW = ROOT / "data" / "law.json"
DEFAULT_TOKEN_MODEL = "text-embedding-3-small"


def load_articles(path: Path) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "meta" in raw:
        return raw["meta"]
    raise ValueError(f"Unexpected law.json format: {type(raw)}")


def get_encoder(model: str):
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, enc) -> int:
    if not text:
        return 0
    return len(enc.encode(text))


def percentile_nearest(values: Sequence[float | int], p: float) -> float:
    """Linear interpolation percentile (p in 0..100)."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n == 1:
        return float(s[0])
    k = (n - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, n - 1)
    return float(s[f] + (k - f) * (s[c] - s[f]))


def histogram_bins(
    values: Sequence[int], edges: Sequence[int]
) -> List[tuple[str, int, float]]:
    """
    Bucket counts for [0, e0), [e0, e1), ... [last, inf).
    edges must be sorted strictly increasing.
    """
    rows: List[tuple[str, int, float]] = []
    n = len(values)
    prev = 0
    for edge in edges:
        cnt = sum(1 for v in values if prev <= v < edge)
        pct = (100.0 * cnt / n) if n else 0.0
        rows.append((f"[{prev}, {edge})", cnt, pct))
        prev = edge
    cnt = sum(1 for v in values if v >= prev)
    pct = (100.0 * cnt / n) if n else 0.0
    rows.append((f"[{prev}, ∞)", cnt, pct))
    return rows


def print_section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def main() -> int:
    ap = argparse.ArgumentParser(description="Law.json length & token EDA for chunking.")
    ap.add_argument(
        "--law-json",
        type=Path,
        default=DEFAULT_LAW,
        help=f"Path to law.json (default: {DEFAULT_LAW})",
    )
    ap.add_argument(
        "--model",
        type=str,
        default=DEFAULT_TOKEN_MODEL,
        help=f"tiktoken model name for counting (default: {DEFAULT_TOKEN_MODEL})",
    )
    ap.add_argument(
        "--bins",
        type=int,
        nargs="+",
        default=[256, 512, 1024, 2048, 4096, 8192],
        metavar="TOK",
        help="Token histogram bin upper bounds (default: 256 512 ... 8192)",
    )
    args = ap.parse_args()

    path: Path = args.law_json
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    articles = load_articles(path)
    texts = [str(a.get("Text") or "") for a in articles]
    titles = [str(a.get("Điều") or "")[:60] for a in articles]

    enc = get_encoder(args.model)
    char_lens = [len(t) for t in texts]
    tok_lens = [count_tokens(t, enc) for t in texts]
    word_lens = [len(t.split()) for t in texts]

    print_section("law.json — overview")
    print(f"Path:           {path}")
    print(f"Records:        {len(articles)}")
    print(f"File size:      {path.stat().st_size:,} bytes")
    print(f"Token model:    {args.model} (tiktoken)")

    for name, vals in (
        ("Characters", char_lens),
        ("Tokens", tok_lens),
        ("Words (split)", word_lens),
    ):
        print_section(f"Distribution — {name}")
        print(f"  min:    {min(vals)}")
        print(f"  max:    {max(vals)}")
        print(f"  mean:   {statistics.mean(vals):.1f}")
        print(f"  stdev:  {statistics.stdev(vals):.1f}" if len(vals) > 1 else "  stdev:  —")
        for p in (50, 75, 90, 95, 99):
            print(f"  p{p}:   {percentile_nearest(vals, p):.1f}")

    edges = sorted(set(args.bins))
    if sorted(args.bins) != list(args.bins) or len(set(args.bins)) != len(args.bins):
        print("(note: --bins deduplicated and sorted ascending)", file=sys.stderr)
    print_section("Histogram — tokens (per article)")
    for label, cnt, pct in histogram_bins(tok_lens, edges):
        bar = "#" * max(1, int(round(pct / 2)))
        print(f"  {label:16} {cnt:4}  ({pct:5.1f}%) {bar}")

    # Chunking hints: how many articles exceed common chunk sizes
    print_section("Chunking hints (single-article as one chunk)")
    for limit in (512, 1024, 2048, 4096):
        over = sum(1 for t in tok_lens if t > limit)
        print(f"  Articles with tokens > {limit}: {over} ({100 * over / len(tok_lens):.1f}%)")

    # Longest articles (for manual inspection)
    print_section("Top 10 longest by tokens")
    idx_sorted = sorted(range(len(tok_lens)), key=lambda i: tok_lens[i], reverse=True)
    for rank, i in enumerate(idx_sorted[:10], start=1):
        print(f"  {rank:2}. {tok_lens[i]:5} tok  |  {char_lens[i]:6} ch  |  {titles[i]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
