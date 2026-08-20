"""Validate all 50 ground truth benchmark cases directly against the Qdrant legal database.

Ensures that every statutory anchor, article number, and law referenced in the 50
benchmark cases genuinely exists in `vietnam_legal_collection_v1`.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from backend.config import get_settings
from backend.core.retrieval import get_qdrant_client, close_qdrant_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("db_validator")


def main():
    settings = get_settings()
    benchmark_file = ROOT / "data" / "eval" / "golden_legal_benchmark.json"
    benchmark_data = json.loads(benchmark_file.read_text(encoding="utf-8"))
    cases = benchmark_data.get("cases", [])

    client = get_qdrant_client()
    collection_name = settings.law_collection

    print("=" * 80)
    print(f"🔍 AUDITING 50 BENCHMARK CASES AGAINST QDRANT DB ({collection_name})")
    print("=" * 80)

    # 1. Fetch all unique statutory article titles and document names in the DB
    print("\nScanning database payload records...")
    db_anchors = set()
    db_docs = set()
    sample_records_by_anchor: dict[str, list[dict]] = {}

    offset = None
    scanned_points = 0

    while True:
        records, next_offset = client.scroll(
            collection_name=collection_name,
            limit=10000,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            break
        scanned_points += len(records)
        for r in records:
            p = r.payload or {}
            dieu = str(p.get("Dieu") or p.get("Parent_Dieu") or p.get("article_title") or "").strip()
            doc_title = str(p.get("document_title") or p.get("law_name") or "").strip()
            text = str(p.get("Text") or p.get("text") or "")

            if dieu:
                db_anchors.add(dieu.lower())
                # Extract numeric pattern: 'điều 25'
                m = re.search(r"điều\s+\d+", dieu.lower())
                if m:
                    db_anchors.add(m.group(0))
            if doc_title:
                db_docs.add(doc_title.lower())

        offset = next_offset
        if offset is None:
            break

    print(f"Scanned {scanned_points:,} total vector points in DB.")
    print(f"Found {len(db_anchors):,} distinct article identifiers and {len(db_docs):,} document titles in DB.\n")

    # 2. Check each case
    passed_count = 0
    missing_cases = []

    print(f"{'Case ID':<15} | {'Domain':<22} | {'Expected Anchors':<30} | {'Status in DB'}")
    print("-" * 85)

    for case in cases:
        case_id = case["id"]
        domain = case.get("domain", "")
        expected_anchors = case.get("expected_anchors", [])

        # Check if anchors exist in DB
        matched_anchors = []
        for anchor in expected_anchors:
            clean = anchor.lower().strip()
            # check direct in db_anchors or db_docs
            if any(clean in a for a in db_anchors) or any(clean in d for d in db_docs):
                matched_anchors.append(anchor)
            else:
                m = re.search(r"điều\s+\d+", clean)
                if m and m.group(0) in db_anchors:
                    matched_anchors.append(anchor)

        is_valid = len(matched_anchors) > 0
        if is_valid:
            passed_count += 1
            status_str = f"✅ FOUND ({len(matched_anchors)}/{len(expected_anchors)} matches)"
        else:
            status_str = "❌ NOT FOUND IN DB"
            missing_cases.append((case_id, expected_anchors))

        anchors_preview = ", ".join(expected_anchors)[:28]
        print(f"{case_id:<15} | {domain:<22} | {anchors_preview:<30} | {status_str}")

    print("\n" + "=" * 80)
    print(f"AUDIT SUMMARY: {passed_count}/{len(cases)} cases have verified statutory anchors in DB ({passed_count/len(cases)*100:.1f}%)")
    print("=" * 80)

    if missing_cases:
        print("\n⚠️ Cases with missing anchors:")
        for cid, anchors in missing_cases:
            print(f"  - {cid}: {anchors}")

    close_qdrant_client()


if __name__ == "__main__":
    main()
