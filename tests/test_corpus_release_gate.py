"""Release-gate tests for source hashes, amendment chains, and rule packs."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import canonical_corpus
from scripts.canonical_corpus import corpus_readiness_audit, corpus_sha256_from_manifest, sha256_file


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_corpus_audit_blocks_unreviewed_amendment_chain() -> None:
    audit = corpus_readiness_audit()

    assert audit["ready_for_promotion"] is False
    assert audit["technical_ready"] is True
    assert audit["source_errors"] == []
    assert "amendment_map_legal_review_pending" in audit["amendment_errors"]
    assert "rule_pack_legal_review_pending" in audit["rule_pack_errors"]
    assert "manifest_legal_review_pending" in audit["approval_errors"]
    assert not any(item.endswith("active_source_pages_missing") for item in audit["amendment_errors"])
    assert not any(item.endswith("operations_missing") for item in audit["amendment_errors"])


def test_corpus_audit_detects_source_hash_tampering(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"documents":[{"document_id":"test-document","source_file":"missing.doc",'
        '"source_sha256":"' + "0" * 64 + '","source_uri":"https://example.test/source",'
        '"signed_source_file":"missing.pdf","signed_source_sha256":"' + "0" * 64 + '"}]}',
        encoding="utf-8",
    )
    audit = corpus_readiness_audit(manifest_path=manifest)

    assert "test-document:source_missing" in audit["source_errors"]
    assert "test-document:signed_source_missing" in audit["source_errors"]
    assert audit["ready_for_promotion"] is False


def test_approved_labels_still_require_named_reviewers_and_dates(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    source = data / "official.pdf"
    source.write_bytes(b"signed official source")
    records = data / "law.json"
    records.write_text('{"records": []}\n', encoding="utf-8")
    source_hash = sha256_file(source)
    records_hash = sha256_file(records)
    manifest = {
        "corpus_id": "epr-test",
        "corpus_version": "approved-without-review-metadata",
        "legal_review_status": "approved",
        "corpus_as_of_date": None,
        "amendment_map_file": "data/amendment.json",
        "rule_pack_file": "data/rules.json",
        "documents": [
            {
                "document_id": "base",
                "source_file": "data/official.pdf",
                "source_sha256": source_hash,
                "source_uri": "https://vanban.chinhphu.vn/example",
                "signed_source_file": "data/official.pdf",
                "signed_source_sha256": source_hash,
                "records_file": "data/law.json",
                "records_sha256": records_hash,
                "precedence": 1,
            }
        ],
    }
    anchors = [*(f"Điều {number}" for number in range(77, 87)), "Phụ lục XXII"]
    amendment_map = {
        "review_status": "approved",
        "reviewed_by": "reviewer@example.test",
        "reviewed_at": None,
        "technical_validation_status": "complete",
        "generated_consolidated_text": False,
        "entries": [
            {
                "anchor": anchor,
                "substantive_source_document_id": "base",
                "substantive_source_pages": "1",
                "resolution_status": "verified",
                "verified_by": "reviewer@example.test",
                "verified_at": "2026-08-13",
                "operations": [
                    {
                        "document_id": "base",
                        "operation": "replace_term",
                        "target": anchor,
                        "source_pages": "1",
                        "effective_from": "2026-01-01",
                        "summary": "Technical fixture only.",
                    }
                ],
            }
            for anchor in anchors
        ],
    }
    manifest_path = data / "manifest.json"
    amendment_path = data / "amendment.json"
    rules_path = data / "rules.json"
    _write_json(manifest_path, manifest)
    _write_json(amendment_path, amendment_map)
    monkeypatch.setattr(canonical_corpus, "ROOT", tmp_path)
    corpus_hash = corpus_sha256_from_manifest(manifest, root=tmp_path)
    _write_json(
        rules_path,
        {
            "corpus_version": manifest["corpus_version"],
            "corpus_sha256": corpus_hash,
            "legal_review_status": "approved",
            "legal_reviewed_by": "reviewer@example.test",
            "legal_reviewed_at": "2026-08-13",
        },
    )

    audit = corpus_readiness_audit(
        manifest_path=manifest_path,
        amendment_map_path=amendment_path,
        rule_pack_path=rules_path,
    )

    assert audit["technical_ready"] is True
    assert audit["ready_for_promotion"] is False
    assert "manifest_legal_reviewed_by_missing" in audit["approval_errors"]
    assert "manifest_legal_reviewed_at_missing" in audit["approval_errors"]
    assert "manifest_corpus_as_of_date_missing" in audit["approval_errors"]
    assert "amendment_map_reviewed_at_missing" in audit["approval_errors"]
