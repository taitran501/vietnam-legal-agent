"""Release-gate tests for source hashes, amendment chains, and rule packs."""

from __future__ import annotations

from pathlib import Path

from scripts.canonical_corpus import corpus_readiness_audit


def test_corpus_audit_blocks_unreviewed_amendment_chain() -> None:
    audit = corpus_readiness_audit()

    assert audit["ready_for_promotion"] is False
    assert audit["source_errors"] == []
    assert "amendment_map_legal_review_pending" in audit["amendment_errors"]
    assert "rule_pack_legal_review_pending" in audit["rule_pack_errors"]
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
