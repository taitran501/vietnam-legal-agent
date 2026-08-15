"""Synchronize deterministic corpus, rule-pack, source, and index metadata.

Use ``--check`` in CI.  ``--write`` is an explicit maintainer operation and
never changes legal-review or promotion status fields.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from scripts.canonical_corpus import appendix_sha256, corpus_sha256_from_manifest, default_appendix_path, sha256_file

from epr_agent.domain.legal import (
    CHUNKING_PROFILE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    EMBEDDING_PROFILE,
    INDEX_SCHEMA_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "corpus_manifest.json"
DEFAULT_RUNTIME_MANIFEST = ROOT / "data" / "corpus_runtime_manifest.json"


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _json_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain one JSON object")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_bytes(_json_bytes(value))


def _resolve(root: Path, value: object) -> Path:
    path = Path(str(value or ""))
    return path if path.is_absolute() else root / path


def desired_documents(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for raw in manifest.get("documents") or []:
        document = copy.deepcopy(dict(raw))
        source = _resolve(root, document.get("source_file"))
        signed = _resolve(root, document.get("signed_source_file"))
        if not source.is_file():
            raise FileNotFoundError(f"source file is missing: {source}")
        if not signed.is_file():
            raise FileNotFoundError(f"signed source file is missing: {signed}")
        document["source_sha256"] = sha256_file(source).upper()
        document["signed_source_sha256"] = sha256_file(signed).upper()
        records_file = document.get("records_file")
        if records_file:
            records = _resolve(root, records_file)
            if not records.is_file():
                raise FileNotFoundError(f"records file is missing: {records}")
            document["records_sha256"] = sha256_file(records).upper()
        else:
            document.pop("records_sha256", None)
        documents.append(document)
    return documents


def desired_state(
    *,
    root: Path = ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
    runtime_manifest_path: Path = DEFAULT_RUNTIME_MANIFEST,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    del runtime_manifest_path  # The path is part of the caller contract, not the hash.
    manifest = _read(manifest_path)
    desired_manifest = copy.deepcopy(manifest)
    desired_manifest["documents"] = desired_documents(root, manifest)
    desired_manifest["index_contract"] = {
        "alias": "law_collection",
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "chunking_profile": CHUNKING_PROFILE,
        "embedding_profile": EMBEDDING_PROFILE,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
        "collection_identity": "law_{corpus_id}_{corpus_sha12}_{schema}_{embedding_profile}",
    }

    rule_reference = str(desired_manifest.get("rule_pack_file") or "").strip()
    amendment_reference = str(desired_manifest.get("amendment_map_file") or "").strip()
    if not rule_reference:
        raise ValueError("manifest rule_pack_file is required")
    if not amendment_reference:
        raise ValueError("manifest amendment_map_file is required")
    rule_path = _resolve(root, rule_reference)
    amendment_path = _resolve(root, amendment_reference)
    if not rule_path.is_file():
        raise FileNotFoundError(f"rule pack is missing: {rule_path}")
    if not amendment_path.is_file():
        raise FileNotFoundError(f"amendment map is missing: {amendment_path}")

    appendix = default_appendix_path(root)
    if appendix.is_file():
        desired_manifest["appendix_xxii_sha256"] = appendix_sha256(appendix)
    corpus_sha = corpus_sha256_from_manifest(
        desired_manifest,
        law_path=root / "data" / "law.json",
        appendix_path=appendix,
        root=root,
    )
    desired_rule_pack = copy.deepcopy(_read(rule_path))
    desired_rule_pack["corpus_id"] = str(desired_manifest.get("corpus_id") or "")
    desired_rule_pack["corpus_version"] = str(desired_manifest.get("corpus_version") or "")
    desired_rule_pack["corpus_sha256"] = corpus_sha

    schema_slug = INDEX_SCHEMA_VERSION.replace("-", "_")
    profile_slug = EMBEDDING_PROFILE.replace("-", "_")
    collection = f"law_{desired_manifest['corpus_id']}_{corpus_sha[:12]}_{schema_slug}_{profile_slug}"
    source_inventory = [
        {
            "document_id": item["document_id"],
            "source_file": item["source_file"],
            "source_sha256": item["source_sha256"],
            "signed_source_file": item["signed_source_file"],
            "signed_source_sha256": item["signed_source_sha256"],
            "records_file": item.get("records_file"),
            "records_sha256": item.get("records_sha256"),
        }
        for item in desired_manifest["documents"]
    ]
    runtime = {
        "schema_version": "epr-corpus-runtime-v1",
        "generated_by": "python -m scripts.sync_corpus_metadata --write",
        "corpus_id": desired_manifest.get("corpus_id"),
        "corpus_version": desired_manifest.get("corpus_version"),
        "corpus_sha256": corpus_sha,
        "corpus_as_of_date": desired_manifest.get("corpus_as_of_date"),
        "legal_review_status": desired_manifest.get("legal_review_status"),
        "manifest_file": manifest_path.relative_to(root).as_posix(),
        "manifest_sha256": _json_sha256(desired_manifest),
        "amendment_map_file": amendment_reference,
        "amendment_map_sha256": sha256_file(amendment_path),
        "rule_pack_file": rule_reference,
        "rule_pack_sha256": _json_sha256(desired_rule_pack),
        "sources": source_inventory,
        "index": {
            **desired_manifest["index_contract"],
            "immutable_collection": collection,
        },
    }
    return desired_manifest, desired_rule_pack, runtime, rule_path


def synchronize(
    *,
    write: bool,
    root: Path = ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
    runtime_manifest_path: Path = DEFAULT_RUNTIME_MANIFEST,
) -> dict[str, Any]:
    desired_manifest, desired_rule_pack, desired_runtime, rule_path = desired_state(
        root=root,
        manifest_path=manifest_path,
        runtime_manifest_path=runtime_manifest_path,
    )
    issues: list[str] = []
    if _read(manifest_path) != desired_manifest:
        issues.append("corpus_manifest_out_of_sync")
    if _read(rule_path) != desired_rule_pack:
        issues.append("rule_pack_link_out_of_sync")
    if not runtime_manifest_path.is_file():
        issues.append("runtime_manifest_missing")
    elif _read(runtime_manifest_path) != desired_runtime:
        issues.append("runtime_manifest_out_of_sync")

    changed = bool(issues)
    if write and changed:
        _write(manifest_path, desired_manifest)
        _write(rule_path, desired_rule_pack)
        _write(runtime_manifest_path, desired_runtime)
        issues = []
    return {
        "status": "written" if write else "ok" if not issues else "out_of_sync",
        "changed": changed,
        "issues": issues,
        "corpus_sha256": desired_runtime["corpus_sha256"],
        "runtime_manifest": runtime_manifest_path.relative_to(root).as_posix(),
        "immutable_collection": desired_runtime["index"]["immutable_collection"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Fail when checked-in metadata is stale")
    mode.add_argument("--write", action="store_true", help="Rewrite deterministic metadata only")
    args = parser.parse_args(argv)
    try:
        report = synchronize(write=bool(args.write))
    except Exception as exc:  # noqa: BLE001 - CLI reports one stable failure envelope
        print(json.dumps({"status": "error", "error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not report["issues"] else 2


if __name__ == "__main__":
    sys.exit(main())
