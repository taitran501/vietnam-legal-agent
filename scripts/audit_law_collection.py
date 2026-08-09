"""
Audit quality of Qdrant law collection.

Checks:
1. Schema completeness (Dieu/Chuong/Muc/Text)
2. Text hygiene (zero-width chars, BOM, control chars, excessive spaces/newlines)
3. Exact duplicate detection by normalized text hash
4. Coverage checks for key legal anchors (e.g., Phụ lục XXII)
5. Optional retrieval sanity check via backend retriever

Usage:
    python -m scripts.audit_law_collection
    python -m scripts.audit_law_collection --collection law_collection --output artifacts/law_audit.json
    python -m scripts.audit_law_collection --run-retrieval-check
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200F\uFEFF]")
MULTISPACE_RE = re.compile(r"[ \t]{2,}")
MULTIBLANK_RE = re.compile(r"\n{3,}")
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def _parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def _truthy(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y"}


def _normalise_text(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = ZERO_WIDTH_RE.sub("", cleaned)
    cleaned = MULTISPACE_RE.sub(" ", cleaned)
    cleaned = MULTIBLANK_RE.sub("\n\n", cleaned)
    cleaned = "\n".join(ln.strip() for ln in cleaned.split("\n"))
    return cleaned.strip().lower()


def _contains_any(text: str, patterns: list[str]) -> bool:
    low = text.lower()
    return any(p.lower() in low for p in patterns)


def _build_qdrant_client(env: dict[str, str], project_root: Path) -> tuple[QdrantClient, str]:
    use_cloud = _truthy(env.get("USE_QDRANT_CLOUD"), False)
    if use_cloud:
        url = env.get("QDRANT_CLOUD_URL", "")
        key = env.get("QDRANT_API_KEY", "")
        if not url or not key:
            raise ValueError("USE_QDRANT_CLOUD=true but QDRANT_CLOUD_URL/QDRANT_API_KEY missing")
        return QdrantClient(url=url, api_key=key, timeout=30), f"cloud:{url}"

    local_path = env.get("QDRANT_LOCAL_PATH", "./qdrant_db")
    resolved = (project_root / local_path).resolve() if local_path.startswith(".") else Path(local_path).resolve()
    return QdrantClient(path=str(resolved), timeout=30), f"local:{local_path}"


def _scroll_all_points(client: QdrantClient, collection: str) -> list[Any]:
    points: list[Any] = []
    offset = None
    while True:
        batch, next_offset = client.scroll(
            collection_name=collection,
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not batch:
            break
        points.extend(batch)
        if next_offset is None:
            break
        offset = next_offset
    return points


def _run_retrieval_sanity_check(project_root: Path) -> dict[str, Any]:
    # Lazy import so core audit does not depend on OpenAI access.
    sys.path.insert(0, str(project_root))
    from backend.core.retrieval import retrieve_legal_async  # noqa: WPS433

    testcases = [
        {
            "query": "sản phẩm nào bắt buộc phải tái chế theo luật",
            "expect_any": ["phụ lục xxii", "tái chế", "ắc quy", "dầu nhớt"],
        },
        {
            "query": "điều 77 quy định gì",
            "expect_any": ["điều 77", "trách nhiệm"],
        },
        {
            "query": "tỷ lệ tái chế dầu nhớt là bao nhiêu",
            "expect_any": ["dầu nhớt", "100%"],
        },
    ]

    async def _eval() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for tc in testcases:
            docs = await retrieve_legal_async(tc["query"])
            top = docs[0] if docs else None
            top_text = ""
            if top is not None:
                top_text = f"{top.metadata.get('Dieu', '')} {top.page_content}"
            ok = bool(top) and _contains_any(top_text, tc["expect_any"])
            rows.append(
                {
                    "query": tc["query"],
                    "ok": ok,
                    "docs_count": len(docs),
                    "top_dieu": top.metadata.get("Dieu", "") if top else "",
                    "top_source": top.metadata.get("retrieval_source", "") if top else "",
                    "top_preview": (top.page_content[:180] if top else ""),
                }
            )
        return rows

    results = asyncio.run(_eval())
    passed = sum(1 for r in results if r["ok"])
    return {
        "enabled": True,
        "passed": passed,
        "total": len(results),
        "cases": results,
    }


def run_audit(project_root: Path, collection: str, run_retrieval_check: bool) -> dict[str, Any]:
    env = _parse_env_file(project_root / ".env")
    env.update({key: value for key, value in os.environ.items() if isinstance(value, str)})
    client, target = _build_qdrant_client(env, project_root)

    collections = {c.name for c in client.get_collections().collections}
    if collection not in collections:
        raise ValueError(f"Collection '{collection}' not found in {target}. Available={sorted(collections)}")

    points = _scroll_all_points(client, collection)
    client.close()

    missing = Counter()
    hygiene = Counter()
    short_text_count = 0
    exact_hashes = Counter()
    anchors = {
        "phu_luc_xxii": ["phụ lục xxii"],
        "mandatory_recycling_terms": [
            "ắc quy",
            "pin",
            "dầu nhớt",
            "săm lốp",
            "bao bì",
            "điện",
            "phương tiện giao thông",
            "tỷ lệ tái chế",
        ],
    }
    anchor_hits = Counter()

    for p in points:
        payload = p.payload or {}
        dieu = str(payload.get("Dieu", "") or "")
        chuong = str(payload.get("Chuong", "") or "")
        muc = str(payload.get("Muc", "") or "")
        text = str(payload.get("Text", "") or "")

        if not dieu:
            missing["Dieu"] += 1
        if not chuong:
            missing["Chuong"] += 1
        if "Muc" not in payload:
            missing["Muc"] += 1
        if not text.strip():
            missing["Text"] += 1
            continue

        if len(text.strip()) < 80:
            short_text_count += 1
        if ZERO_WIDTH_RE.search(text):
            hygiene["zero_width"] += 1
        if "\ufeff" in text:
            hygiene["bom"] += 1
        if CONTROL_CHAR_RE.search(text):
            hygiene["control_char"] += 1
        if MULTISPACE_RE.search(text):
            hygiene["multi_space"] += 1
        if MULTIBLANK_RE.search(text):
            hygiene["multi_blankline"] += 1

        normalized = _normalise_text(text)
        parent_dieu = str(payload.get("Parent_Dieu") or dieu).strip().lower()
        hierarchy = str(payload.get("Hierarchy") or "").strip().lower()
        source_start = str(payload.get("Source_Start", ""))
        source_end = str(payload.get("Source_End", ""))
        provenance = f"{parent_dieu}|{hierarchy}|{source_start}|{source_end}|{normalized}"
        digest = hashlib.sha1(provenance.encode("utf-8")).hexdigest()
        exact_hashes[digest] += 1

        combined = f"{dieu}\n{chuong}\n{muc}\n{text}".lower()
        for anchor_name, patterns in anchors.items():
            if _contains_any(combined, patterns):
                anchor_hits[anchor_name] += 1

    dup_docs = sum(cnt - 1 for cnt in exact_hashes.values() if cnt > 1)

    report: dict[str, Any] = {
        "qdrant_target": target,
        "collection": collection,
        "points_total": len(points),
        "schema_missing": dict(missing),
        "hygiene_flags": dict(hygiene),
        "short_text_count_lt_80": short_text_count,
        "exact_duplicate_docs": dup_docs,
        "anchor_hits": dict(anchor_hits),
        "quality_summary": {
            "schema_ok": sum(missing.values()) == 0,
            "hygiene_ok": sum(hygiene.values()) == 0,
            "duplicate_ok": dup_docs == 0,
            "coverage_phu_luc_xxii_ok": anchor_hits.get("phu_luc_xxii", 0) > 0,
        },
    }

    if run_retrieval_check:
        try:
            report["retrieval_sanity"] = _run_retrieval_sanity_check(project_root)
        except Exception as exc:  # noqa: BLE001 - optional live sanity check is reported, not fatal
            report["retrieval_sanity"] = {
                "enabled": True,
                "error": str(exc),
            }
    else:
        report["retrieval_sanity"] = {"enabled": False}

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit quality of law_collection in Qdrant")
    parser.add_argument(
        "--collection",
        default=os.getenv("LAW_COLLECTION", "law_collection"),
        help="Qdrant collection name to audit (default: LAW_COLLECTION env or law_collection)",
    )
    parser.add_argument(
        "--output",
        default="artifacts/law_collection_audit.json",
        help="Output JSON report path",
    )
    parser.add_argument(
        "--run-retrieval-check",
        action="store_true",
        help="Run optional retrieval sanity checks via backend retriever",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    report = run_audit(
        project_root=project_root,
        collection=args.collection,
        run_retrieval_check=args.run_retrieval_check,
    )

    output_path = (project_root / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[audit] collection={report['collection']}")
    print(f"[audit] points_total={report['points_total']}")
    print(f"[audit] schema_missing={report['schema_missing']}")
    print(f"[audit] hygiene_flags={report['hygiene_flags']}")
    print(f"[audit] exact_duplicate_docs={report['exact_duplicate_docs']}")
    print(f"[audit] anchor_hits={report['anchor_hits']}")
    print(f"[audit] summary={report['quality_summary']}")
    if report["retrieval_sanity"].get("enabled"):
        print(f"[audit] retrieval_sanity={report['retrieval_sanity']}")
    print(f"[audit] report_saved={output_path}")


if __name__ == "__main__":
    main()
