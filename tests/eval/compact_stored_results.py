"""
Compact stored eval JSON files under tests/eval/results_*.json.

Removes bulky fields (especially final_text) and drops empty-string optional
fields so repo stays small. Re-run full eval anytime via:

    python -m tests.eval.run_eval --output tests/eval/results_e2e.json

Usage (from repo root epr_chatbot/):

    python -m tests.eval.compact_stored_results
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVAL_DIR = ROOT

# Always drop (regenerate with run_eval if full answers needed)
DROP_KEYS = frozenset({"final_text"})

# Omit key entirely when value is empty string
STRIP_IF_EMPTY = frozenset({
    "faithfulness_reason",
    "relevance_reason",
    "completeness_reason",
})


def _compact_record(obj: dict) -> dict:
    out: dict = {}
    for k, v in obj.items():
        if k in DROP_KEYS:
            continue
        if k in STRIP_IF_EMPTY and v == "":
            continue
        out[k] = v
    return out


def compact_file(path: Path) -> tuple[int, int]:
    """Return (bytes_before, bytes_after)."""
    raw = path.read_bytes()
    before = len(raw)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        return before, before
    compacted = [_compact_record(x) for x in data if isinstance(x, dict)]
    text = json.dumps(compacted, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")
    return before, len(text.encode("utf-8"))


def main() -> int:
    patterns = sorted(EVAL_DIR.glob("results_*.json"))
    if not patterns:
        print("No tests/eval/results_*.json found.", file=sys.stderr)
        return 1
    total_before = total_after = 0
    for p in patterns:
        b, a = compact_file(p)
        total_before += b
        total_after += a
        print(f"{p.name}: {b} -> {a} bytes")
    print(f"Total: {total_before} -> {total_after} bytes ({100 * total_after / max(total_before, 1):.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
