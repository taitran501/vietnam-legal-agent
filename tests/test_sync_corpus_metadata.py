from __future__ import annotations

import json
from pathlib import Path

from scripts.canonical_corpus import corpus_sha256_from_manifest
from scripts.sync_corpus_metadata import synchronize


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / "data"
    data.mkdir()
    (data / "law.json").write_text('{"meta": []}\n', encoding="utf-8")
    (data / "base.pdf").write_bytes(b"signed official source")
    (data / "records.json").write_text('{"meta": []}\n', encoding="utf-8")
    _write_json(data / "amendment.json", {"source_map_status": "technical", "entries": []})
    _write_json(
        data / "rules.json",
        {
            "rule_pack_version": "test-v1",
            "corpus_id": "stale",
            "corpus_version": "stale",
            "corpus_sha256": "0" * 64,
            "source_snapshot_status": "technical",
        },
    )
    manifest = data / "manifest.json"
    _write_json(
        manifest,
        {
            "corpus_id": "epr-test",
            "corpus_version": "v1",
            "corpus_as_of_date": None,
            "source_snapshot_status": "technical",
            "amendment_map_file": "data/amendment.json",
            "rule_pack_file": "data/rules.json",
            "documents": [
                {
                    "document_id": "base",
                    "source_file": "data/base.pdf",
                    "source_sha256": "0" * 64,
                    "signed_source_file": "data/base.pdf",
                    "signed_source_sha256": "0" * 64,
                    "records_file": "data/records.json",
                }
            ],
        },
    )
    return manifest, data / "runtime.json"


def test_sync_write_then_check_is_deterministic_without_legal_approval_metadata(tmp_path: Path) -> None:
    manifest, runtime = _fixture(tmp_path)

    written = synchronize(write=True, root=tmp_path, manifest_path=manifest, runtime_manifest_path=runtime)
    checked = synchronize(write=False, root=tmp_path, manifest_path=manifest, runtime_manifest_path=runtime)

    assert written["status"] == "written"
    assert checked["status"] == "ok"
    assert checked["issues"] == []
    synced_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    synced_rules = json.loads((tmp_path / "data" / "rules.json").read_text(encoding="utf-8"))
    assert synced_manifest["source_snapshot_status"] == "technical"
    assert synced_manifest["corpus_as_of_date"] is None
    assert synced_manifest["documents"][0]["records_sha256"]
    assert synced_manifest["index_contract"]["index_schema_version"] == "legal-structure-v2-v4-appendix1"
    assert synced_rules["source_snapshot_status"] == "technical"
    assert synced_rules["corpus_sha256"] == checked["corpus_sha256"]
    assert checked["changed"] is False


def test_sync_check_detects_source_drift_without_rewriting(tmp_path: Path) -> None:
    manifest, runtime = _fixture(tmp_path)
    synchronize(write=True, root=tmp_path, manifest_path=manifest, runtime_manifest_path=runtime)
    source = tmp_path / "data" / "base.pdf"
    source.write_bytes(b"changed source")

    report = synchronize(write=False, root=tmp_path, manifest_path=manifest, runtime_manifest_path=runtime)

    assert report["status"] == "out_of_sync"
    assert "corpus_manifest_out_of_sync" in report["issues"]
    assert "runtime_manifest_out_of_sync" in report["issues"]


def test_sync_uses_generated_runtime_appendix_artifact(tmp_path: Path) -> None:
    manifest, runtime = _fixture(tmp_path)
    appendix = tmp_path / "artifacts" / "appendix_xxii.jsonl"
    appendix.parent.mkdir(parents=True)
    appendix.write_text(
        json.dumps({"Row_Id": "p1-t0-r0", "Text": "Điều 77", "PDF_SHA256": "converter"}) + "\n",
        encoding="utf-8",
    )

    synchronize(write=True, root=tmp_path, manifest_path=manifest, runtime_manifest_path=runtime)
    checked = synchronize(write=False, root=tmp_path, manifest_path=manifest, runtime_manifest_path=runtime)
    synced_manifest = json.loads(manifest.read_text(encoding="utf-8"))
    with_appendix = corpus_sha256_from_manifest(synced_manifest, root=tmp_path, appendix_path=appendix)
    manifest_without_declared_appendix = dict(synced_manifest)
    manifest_without_declared_appendix.pop("appendix_xxii_sha256")
    without_appendix = corpus_sha256_from_manifest(
        manifest_without_declared_appendix,
        root=tmp_path,
        appendix_path=tmp_path / "missing-appendix.jsonl",
    )

    assert checked["status"] == "ok"
    assert checked["corpus_sha256"] == with_appendix
    assert checked["corpus_sha256"] != without_appendix

    appendix.unlink()
    assert synchronize(write=False, root=tmp_path, manifest_path=manifest, runtime_manifest_path=runtime)["status"] == "ok"
