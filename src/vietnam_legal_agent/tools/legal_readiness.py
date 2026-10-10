"""Domain-neutral legal review gate for a selected source corpus."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from vietnam_legal_agent.domain.models import DocumentRecord
from vietnam_legal_agent.domain.verification import VerificationStatus


class ReadinessStatus(StrEnum):
    READY = "ready"
    PENDING = "pending"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class LegalReadinessAudit:
    status: ReadinessStatus
    legally_ready: bool
    aggregate_status: str
    manifest_sha256: str
    corpus_sha256: str
    issues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def reason(self) -> str:
        if self.issues:
            return self.issues[0]
        return "ok" if self.status is ReadinessStatus.READY else "legal_review_pending"

    @property
    def verification_status(self) -> VerificationStatus:
        if self.status is ReadinessStatus.READY:
            return VerificationStatus.VERIFIED
        if self.status is ReadinessStatus.PENDING:
            return VerificationStatus.INSUFFICIENT_EVIDENCE
        return VerificationStatus.VERIFICATION_UNAVAILABLE

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "legally_ready": self.legally_ready,
            "aggregate_status": self.aggregate_status,
            "manifest_sha256": self.manifest_sha256,
            "corpus_sha256": self.corpus_sha256,
            "issues": list(self.issues),
        }


class LegalReadinessProvider(Protocol):
    @property
    def manifest_sha256(self) -> str: ...

    def audit(self) -> LegalReadinessAudit: ...

    def allows_documents(self, documents: Sequence[DocumentRecord]) -> tuple[bool, str]: ...


def sha256_file(path: str | Path) -> str:
    """Return a stable hash for a file used as legal corpus input."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit_legal_readiness(
    manifest_path: str | Path,
    *,
    corpus_sha256: str,
) -> LegalReadinessAudit:
    """Verify one reviewer record against the complete selected corpus hash."""

    path = Path(manifest_path)
    try:
        raw = path.read_bytes()
    except OSError:
        return LegalReadinessAudit(
            ReadinessStatus.PENDING,
            False,
            "pending",
            "",
            corpus_sha256,
            ("legal_review_manifest_missing",),
        )

    manifest_sha = hashlib.sha256(raw).hexdigest()
    try:
        manifest = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        manifest = None
    if not isinstance(manifest, dict):
        return LegalReadinessAudit(
            ReadinessStatus.INVALID,
            False,
            "invalid",
            manifest_sha,
            corpus_sha256,
            ("legal_review_manifest_invalid",),
        )

    reviewed_at = str(manifest.get("reviewed_at") or "")
    reviewer = str(manifest.get("reviewer_id") or "").strip()
    issues: list[str] = []
    if manifest.get("schema_version") != "legal-corpus-review-v1":
        issues.append("legal_review_schema_mismatch")
    if str(manifest.get("corpus_sha256") or "").lower() != corpus_sha256.lower():
        issues.append("legal_review_corpus_hash_mismatch")
    if manifest.get("status") != "ready":
        issues.append("legal_review_pending")
    if not reviewer:
        issues.append("legal_review_reviewer_missing")
    try:
        datetime.fromisoformat(reviewed_at)
    except ValueError:
        issues.append("legal_review_timestamp_invalid")

    status = ReadinessStatus.INVALID if issues and any(issue != "legal_review_pending" for issue in issues) else (
        ReadinessStatus.PENDING if issues else ReadinessStatus.READY
    )
    return LegalReadinessAudit(
        status,
        status is ReadinessStatus.READY,
        "ready" if status is ReadinessStatus.READY else status.value,
        manifest_sha,
        corpus_sha256,
        tuple(issues),
    )


class LegalReadinessGate:
    """Apply whole-corpus review consistently to all retrieved legal sources."""

    def __init__(self, manifest_path: str | Path, *, corpus_sha256: str) -> None:
        self.manifest_path = Path(manifest_path)
        self.corpus_sha256 = corpus_sha256

    @property
    def manifest_sha256(self) -> str:
        try:
            return sha256_file(self.manifest_path)
        except OSError:
            return ""

    def audit(self) -> LegalReadinessAudit:
        return audit_legal_readiness(self.manifest_path, corpus_sha256=self.corpus_sha256)

    def allows_documents(self, documents: Sequence[DocumentRecord]) -> tuple[bool, str]:
        del documents
        audit = self.audit()
        return audit.legally_ready, "" if audit.legally_ready else audit.reason


class SyntheticReadyLegalReadinessGate:
    """Injectable corpus-wide review state used by deterministic tests."""

    def __init__(self, *, ready: bool = True, manifest_sha256: str = "synthetic-review") -> None:
        self.ready = ready
        self._manifest_sha256 = manifest_sha256

    @property
    def manifest_sha256(self) -> str:
        return self._manifest_sha256

    def audit(self) -> LegalReadinessAudit:
        status = ReadinessStatus.READY if self.ready else ReadinessStatus.PENDING
        return LegalReadinessAudit(
            status,
            self.ready,
            status.value,
            self.manifest_sha256,
            "synthetic-corpus",
            () if self.ready else ("legal_review_pending",),
        )

    def allows_documents(self, documents: Sequence[DocumentRecord]) -> tuple[bool, str]:
        del documents
        return self.ready, "" if self.ready else "legal_review_pending"
