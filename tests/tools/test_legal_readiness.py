from __future__ import annotations

import json
from pathlib import Path

from epr_agent.domain.models import DocumentRecord
from epr_agent.tools.legal_readiness import (
    EPR_SCOPE_ANCHORS,
    EPR_SCOPE_APPENDICES,
    LegalReadinessGate,
    ReadinessStatus,
    audit_legal_readiness,
)


def _payload(*, subject_hashes: dict[str, str], ready: bool) -> dict[str, object]:
    anchors = [*EPR_SCOPE_ANCHORS, *EPR_SCOPE_APPENDICES]
    entries: list[dict[str, object]] = []
    for anchor in anchors:
        entry: dict[str, object] = {
            "anchor": anchor,
            "status": "ready" if ready else "pending_legal_review",
            "legally_ready": ready,
            "reviewer_id": "reviewer-1" if ready else None,
            "reviewed_at": "2026-09-05T12:00:00Z" if ready else None,
            "review_record_id": "review-1" if ready else None,
            "reviewed_intervals": (
                [
                    {
                        "from": "2025-01-01",
                        "to": None,
                        "base_source_document_id": "nd08-2022",
                        "applied_operation_ids": [],
                        "source_hashes": ["a" * 64],
                    }
                ]
                if ready
                else []
            ),
            "source_hashes": ["a" * 64] if ready else [],
            "reviewed_subject_hashes": subject_hashes if ready else {},
            "review_notes": "synthetic fixture",
        }
        entries.append(entry)
    return {
        "schema_version": "legal-readiness-v1",
        "corpus_id": "epr",
        "corpus_version": "epr-law-structure-v4-amendment-chain",
        "subject_hashes": subject_hashes,
        "scope": {"anchors": EPR_SCOPE_ANCHORS, "appendices": EPR_SCOPE_APPENDICES},
        "aggregate_status": "ready" if ready else "blocked",
        "entries": entries,
    }


def _document() -> DocumentRecord:
    return DocumentRecord(
        content="Điều 77 quy định trách nhiệm tái chế và các điều kiện thực hiện. " * 8,
        document_id="law-77",
        source="legal",
        current_law_support=True,
        metadata={
            "legal_anchor": "Điều 77",
            "Current_Law_Support": True,
            "Corpus_ID": "epr",
            "Document_Number": "08/2022/NĐ-CP",
        },
    )


def test_repository_manifest_is_valid_but_pending() -> None:
    from scripts.canonical_corpus import corpus_sha256

    from epr_agent.config import get_settings
    from epr_agent.tools.legal_readiness import sha256_file

    settings = get_settings()
    corpus_sha = corpus_sha256(
        law_path=settings.law_data_path,
        manifest_path=settings.corpus_manifest_path,
        appendix_path=settings.appendix_xxii_data_path,
    )
    audit = audit_legal_readiness(
        settings.legal_readiness_manifest_path,
        corpus_sha256=corpus_sha,
        amendment_map_sha256=sha256_file(settings.amendment_map_path),
        rule_pack_sha256=sha256_file(settings.rule_pack_path),
    )

    assert audit.status is ReadinessStatus.PENDING
    assert audit.legally_ready is False
    assert audit.aggregate_status == "blocked"


def test_synthetic_ready_manifest_requires_complete_signoff_and_allows_document(tmp_path: Path) -> None:
    subjects = {
        "corpus_sha256": "c" * 64,
        "amendment_map_sha256": "b" * 64,
        "rule_pack_sha256": "d" * 64,
    }
    path = tmp_path / "legal-readiness.json"
    path.write_text(json.dumps(_payload(subject_hashes=subjects, ready=True), ensure_ascii=False), encoding="utf-8")

    gate = LegalReadinessGate(
        path,
        corpus_sha256=subjects["corpus_sha256"],
        amendment_map_sha256=subjects["amendment_map_sha256"],
        rule_pack_sha256=subjects["rule_pack_sha256"],
    )

    assert gate.audit().status is ReadinessStatus.READY
    assert gate.allows_documents([_document()]) == (True, "ok")


def test_pending_scope_is_reported_before_current_law_support(tmp_path: Path) -> None:
    subjects = {
        "corpus_sha256": "c" * 64,
        "amendment_map_sha256": "b" * 64,
        "rule_pack_sha256": "d" * 64,
    }
    path = tmp_path / "legal-readiness.json"
    path.write_text(json.dumps(_payload(subject_hashes=subjects, ready=False), ensure_ascii=False), encoding="utf-8")

    gate = LegalReadinessGate(
        path,
        corpus_sha256=subjects["corpus_sha256"],
        amendment_map_sha256=subjects["amendment_map_sha256"],
        rule_pack_sha256=subjects["rule_pack_sha256"],
    )

    document = _document()
    document.current_law_support = False
    document.metadata["Current_Law_Support"] = False
    assert gate.allows_documents([document]) == (False, "legal_review_pending")


def test_pending_epr_manifest_does_not_block_documents_outside_its_scope(tmp_path: Path) -> None:
    subjects = {
        "corpus_sha256": "c" * 64,
        "amendment_map_sha256": "b" * 64,
        "rule_pack_sha256": "d" * 64,
    }
    path = tmp_path / "legal-readiness.json"
    path.write_text(json.dumps(_payload(subject_hashes=subjects, ready=False), ensure_ascii=False), encoding="utf-8")
    gate = LegalReadinessGate(
        path,
        corpus_sha256=subjects["corpus_sha256"],
        amendment_map_sha256=subjects["amendment_map_sha256"],
        rule_pack_sha256=subjects["rule_pack_sha256"],
    )
    document = _document()
    document.metadata.update(
        {
            "legal_anchor": "Điều 25",
            "Document_Number": "45/2019/QH14",
            "source_title": "Bộ luật Lao động số 45/2019/QH14",
            "Corpus_ID": "labor",
        }
    )

    assert gate.allows_documents([document]) == (True, "outside_readiness_scope")


def test_manifest_hash_mismatch_is_invalid_and_fails_closed(tmp_path: Path) -> None:
    subjects = {
        "corpus_sha256": "c" * 64,
        "amendment_map_sha256": "b" * 64,
        "rule_pack_sha256": "d" * 64,
    }
    path = tmp_path / "legal-readiness.json"
    path.write_text(json.dumps(_payload(subject_hashes=subjects, ready=False)), encoding="utf-8")

    audit = audit_legal_readiness(
        path,
        corpus_sha256="e" * 64,
        amendment_map_sha256=subjects["amendment_map_sha256"],
        rule_pack_sha256=subjects["rule_pack_sha256"],
    )

    assert audit.status is ReadinessStatus.INVALID
    assert "corpus_sha256_mismatch" in audit.issues
    gate = LegalReadinessGate(
        path,
        corpus_sha256="e" * 64,
        amendment_map_sha256=subjects["amendment_map_sha256"],
        rule_pack_sha256=subjects["rule_pack_sha256"],
    )
    assert gate.allows_documents([_document()]) == (False, "legal_readiness_invalid")
