from __future__ import annotations

import json
from pathlib import Path

from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.tools.legal_readiness import (
    LegalReadinessGate,
    ReadinessStatus,
    SyntheticReadyLegalReadinessGate,
    audit_legal_readiness,
)


def _write_review(path: Path, *, corpus_sha256: str, status: str = "ready") -> None:
    path.write_text(
        json.dumps({
            "schema_version": "legal-corpus-review-v1",
            "status": status,
            "corpus_sha256": corpus_sha256,
            "reviewer_id": "reviewer-1",
            "reviewed_at": "2026-09-30T12:00:00Z",
        }),
        encoding="utf-8",
    )


def test_missing_corpus_review_is_pending(tmp_path: Path) -> None:
    result = audit_legal_readiness(tmp_path / "missing.json", corpus_sha256="abc")

    assert result.status is ReadinessStatus.PENDING
    assert result.legally_ready is False
    assert result.issues == ("legal_review_manifest_missing",)


def test_matching_review_approves_the_whole_corpus(tmp_path: Path) -> None:
    path = tmp_path / "review.json"
    _write_review(path, corpus_sha256="abc")
    gate = LegalReadinessGate(path, corpus_sha256="abc")
    documents = [
        DocumentRecord(content="Labor source", metadata={"legal_domain": "labor"}, document_id="labor"),
        DocumentRecord(content="Environmental source", metadata={"legal_domain": "environmental"}, document_id="environment"),
    ]

    audit = gate.audit()

    assert audit.status is ReadinessStatus.READY
    assert gate.allows_documents(documents) == (True, "")


def test_review_for_a_different_corpus_hash_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "review.json"
    _write_review(path, corpus_sha256="old-hash")

    result = audit_legal_readiness(path, corpus_sha256="new-hash")

    assert result.status is ReadinessStatus.INVALID
    assert "legal_review_corpus_hash_mismatch" in result.issues


def test_pending_review_applies_equally_to_all_legal_topics() -> None:
    gate = SyntheticReadyLegalReadinessGate(ready=False)
    documents = [
        DocumentRecord(content="Labor source", metadata={"legal_domain": "labor"}, document_id="labor"),
        DocumentRecord(content="Civil source", metadata={"legal_domain": "civil"}, document_id="civil"),
    ]

    assert gate.allows_documents(documents) == (False, "legal_review_pending")
