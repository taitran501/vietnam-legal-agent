"""Export accepted quality feedback into replay fixtures.

The export preserves reproducibility metadata but never promotes a user
complaint to legal ground truth. Generated fixtures are inputs for deterministic
replay, debugging, and regression triage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from epr_agent.config import get_settings
from epr_agent.infra.persistence import get_persistence_store, sqlite_database_url


def _database_url() -> str:
    settings = get_settings()
    configured = getattr(settings, "database_url", None)
    return str(configured) if configured else sqlite_database_url(str(settings.history_db_path))


async def _run(output_dir: Path, limit: int) -> int:
    store = await get_persistence_store(_database_url())
    try:
        items = await store.list_quality_feedback(status="accepted", limit=limit)
        output_dir.mkdir(parents=True, exist_ok=True)
        exported = 0
        for item in items:
            query = str(item.get("query") or "").strip()
            snapshot = item.get("evidence_snapshot")
            if not query or not isinstance(snapshot, dict) or not item.get("trace_id"):
                continue
            case_id = str(item.get("dataset_case_id") or f"FEEDBACK_{item['id']}")
            fixture: dict[str, Any] = {
                "case_id": case_id,
                "domain": "feedback_replay",
                "turns": [
                    {
                        "query": query,
                        "expected_behavior": (
                            "Replay the reported failure and preserve the trace, source payload, and failure artifact."
                        ),
                    }
                ],
                "expected_outcome": None,
                "claims": [],
                "sources": [],
                "citations": [],
                "allowed_omissions": [],
                "forbidden_claims": [],
                "follow_up_expected_behavior": [],
                "evidence": {
                    "status": "informational",
                    "corpus_sha": str(snapshot.get("corpus_sha") or ""),
                    "notes": json.dumps(
                        {
                            "quality_feedback_id": item.get("id"),
                            "trace_id": item.get("trace_id"),
                            "failure_category": item.get("failure_category"),
                            "reviewer_id": item.get("reviewer_id"),
                            "review_notes": item.get("review_notes"),
                            "evidence_snapshot": snapshot,
                        },
                        ensure_ascii=False,
                    ),
                },
            }
            path = output_dir / f"{case_id}.json"
            path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
            if not item.get("dataset_case_id"):
                await store.update_quality_feedback(int(item["id"]), dataset_case_id=case_id)
            exported += 1
        print(json.dumps({"accepted": len(items), "exported": exported, "output_dir": str(output_dir)}, ensure_ascii=False))
        return 0
    finally:
        await store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/eval/examples/feedback"),
    )
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100:
        parser.error("--limit must be between 1 and 100")
    return asyncio.run(_run(args.output_dir, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())

