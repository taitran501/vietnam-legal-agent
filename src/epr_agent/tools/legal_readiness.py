"""Independent legal-review readiness for the bounded EPR corpus.

Technical corpus validation and legal sign-off are intentionally separate
contracts.  A source can be extracted, hashed, and indexed while remaining
blocked for legal answer delivery until a reviewer signs the exact source
snapshot and intervals used by the answer.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from epr_agent.domain.models import DocumentRecord
from epr_agent.domain.verification import VerificationStatus

EPR_SCOPE_ANCHORS = [f"Điều {number}" for number in range(77, 87)]
EPR_SCOPE_APPENDICES = ["Phụ lục XXII"]
_TEXT_HASH_SUFFIXES = frozenset({".json", ".jsonl", ".txt", ".md", ".csv"})
_ARTICLE_RE = re.compile(r"(?:điều|dieu)\s+\d+[a-zđ]?", re.IGNORECASE)
_APPENDIX_RE = re.compile(
    r"(?:phụ\s*lục|phu\s*luc)\s*(?:số\s*)?(?:[ivxlcdm]+|\d+)",
    re.IGNORECASE,
)


class ReadinessStatus(StrEnum):
    READY = "ready"
    PENDING = "pending"
    INVALID = "invalid"


class ReviewedInterval(BaseModel):
    """A half-open legal-validity interval reviewed against source hashes."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_date: str = Field(alias="from", min_length=1)
    to_date: str | None = Field(default=None, alias="to")
    base_source_document_id: str = Field(min_length=1)
    applied_operation_ids: list[str] = Field(default_factory=list)
    source_hashes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_interval(self) -> ReviewedInterval:
        try:
            from_date = date.fromisoformat(self.from_date)
            to_date = date.fromisoformat(self.to_date) if self.to_date is not None else None
        except ValueError as exc:
            raise ValueError("reviewed interval dates must be ISO dates") from exc
        if to_date is not None and from_date >= to_date:
            raise ValueError("reviewed interval must use [from,to) with from before to")
        return self


class LegalReadinessEntry(BaseModel):
    """Review record for one production scope anchor."""

    model_config = ConfigDict(extra="forbid")

    anchor: str = Field(min_length=1)
    status: Literal["pending_legal_review", "ready", "legally_ready"] = "pending_legal_review"
    legally_ready: bool = False
    reviewer_id: str | None = None
    reviewed_at: datetime | None = None
    review_record_id: str | None = None
    reviewed_intervals: list[ReviewedInterval] = Field(default_factory=list)
    source_hashes: list[str] = Field(default_factory=list)
    reviewed_subject_hashes: dict[str, str] = Field(default_factory=dict)
    review_notes: str = ""

    @model_validator(mode="after")
    def validate_signoff(self) -> LegalReadinessEntry:
        if self.status in {"ready", "legally_ready"} or self.legally_ready:
            if self.status == "pending_legal_review":
                raise ValueError("legally_ready entries must use a ready status")
            if not self.legally_ready:
                raise ValueError("ready entries must set legally_ready=true")
            if not self.reviewer_id or self.reviewed_at is None:
                raise ValueError("ready entries require reviewer and reviewed_at")
            if not self.review_record_id:
                raise ValueError("ready entries require review_record_id")
            if not self.reviewed_intervals:
                raise ValueError("ready entries require at least one reviewed interval")
            if any(not interval.source_hashes for interval in self.reviewed_intervals):
                raise ValueError("every reviewed interval requires source_hashes")
            if not self.source_hashes:
                raise ValueError("ready entries require source_hashes")
            if not self.reviewed_subject_hashes:
                raise ValueError("ready entries require reviewed_subject_hashes")
        return self


class LegalReadinessScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchors: list[str] = Field(default_factory=list)
    appendices: list[str] = Field(default_factory=list)


class LegalReadinessManifest(BaseModel):
    """Versioned manifest whose aggregate state is audited, never trusted."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["legal-readiness-v1"]
    corpus_id: str = Field(min_length=1)
    corpus_version: str = Field(min_length=1)
    subject_hashes: dict[str, str] = Field(default_factory=dict)
    scope: LegalReadinessScope
    aggregate_status: Literal["blocked", "ready"] = "blocked"
    entries: list[LegalReadinessEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scope(self) -> LegalReadinessManifest:
        anchors = [entry.anchor for entry in self.entries]
        if len(set(anchors)) != len(anchors):
            raise ValueError("legal readiness entries must have unique anchors")
        expected = set(self.scope.anchors) | set(self.scope.appendices)
        if set(anchors) != expected:
            raise ValueError("legal readiness entries must exactly cover the declared scope")
        required_hashes = {"corpus_sha256", "amendment_map_sha256", "rule_pack_sha256"}
        if not required_hashes.issubset(self.subject_hashes):
            raise ValueError("manifest subject_hashes must include corpus, amendment-map, and rule-pack hashes")
        return self


@dataclass(frozen=True, slots=True)
class LegalReadinessAudit:
    status: ReadinessStatus
    legally_ready: bool
    aggregate_status: str
    manifest_sha256: str
    corpus_sha256: str
    amendment_map_sha256: str
    rule_pack_sha256: str
    issues: tuple[str, ...] = field(default_factory=tuple)
    reviewed_anchors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def reason(self) -> str:
        if self.issues:
            return self.issues[0]
        if self.status is ReadinessStatus.READY:
            return "ok"
        return "legal_review_pending"

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
            "amendment_map_sha256": self.amendment_map_sha256,
            "rule_pack_sha256": self.rule_pack_sha256,
            "issues": list(self.issues),
            "reviewed_anchors": list(self.reviewed_anchors),
        }


class LegalReadinessProvider(Protocol):
    @property
    def manifest_sha256(self) -> str: ...

    def audit(self) -> LegalReadinessAudit: ...

    def allows_documents(self, documents: Sequence[DocumentRecord]) -> tuple[bool, str]: ...


def sha256_file(path: str | Path) -> str:
    """Hash logical text content consistently across Windows and POSIX."""

    file_path = Path(path)
    payload = file_path.read_bytes()
    if file_path.suffix.lower() in _TEXT_HASH_SUFFIXES:
        payload = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(payload).hexdigest()


def _manifest_sha(path: Path) -> str:
    try:
        return sha256_file(path)
    except OSError:
        return ""


def audit_legal_readiness(
    manifest_path: str | Path,
    *,
    corpus_sha256: str,
    amendment_map_sha256: str,
    rule_pack_sha256: str,
) -> LegalReadinessAudit:
    """Load and audit the manifest against the exact technical subjects."""

    path = Path(manifest_path)
    manifest_sha = _manifest_sha(path)
    if not path.is_file():
        return LegalReadinessAudit(
            ReadinessStatus.INVALID,
            False,
            "invalid",
            manifest_sha,
            corpus_sha256,
            amendment_map_sha256,
            rule_pack_sha256,
            ("legal_readiness_manifest_missing",),
        )
    try:
        manifest = LegalReadinessManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - malformed review input is a safe-stop condition
        return LegalReadinessAudit(
            ReadinessStatus.INVALID,
            False,
            "invalid",
            manifest_sha,
            corpus_sha256,
            amendment_map_sha256,
            rule_pack_sha256,
            ("legal_readiness_manifest_invalid",),
        )

    expected = {
        "corpus_sha256": corpus_sha256,
        "amendment_map_sha256": amendment_map_sha256,
        "rule_pack_sha256": rule_pack_sha256,
    }
    issues = [
        f"{key}_mismatch"
        for key, value in expected.items()
        if manifest.subject_hashes.get(key) != value
    ]
    declared_scope = set(manifest.scope.anchors) | set(manifest.scope.appendices)
    expected_scope = set(EPR_SCOPE_ANCHORS) | set(EPR_SCOPE_APPENDICES)
    if declared_scope != expected_scope:
        issues.append("legal_readiness_scope_mismatch")

    for entry in manifest.entries:
        if entry.legally_ready and entry.reviewed_subject_hashes != expected:
            issues.append(f"{entry.anchor}_reviewed_subject_hash_mismatch")

    ready_entries = [entry.anchor for entry in manifest.entries if entry.legally_ready]
    if issues:
        return LegalReadinessAudit(
            ReadinessStatus.INVALID,
            False,
            "invalid",
            manifest_sha,
            corpus_sha256,
            amendment_map_sha256,
            rule_pack_sha256,
            tuple(issues),
            tuple(sorted(ready_entries)),
        )
    all_ready = len(ready_entries) == len(manifest.entries)
    return LegalReadinessAudit(
        ReadinessStatus.READY if all_ready else ReadinessStatus.PENDING,
        all_ready,
        "ready" if all_ready else "blocked",
        manifest_sha,
        corpus_sha256,
        amendment_map_sha256,
        rule_pack_sha256,
        (),
        tuple(sorted(ready_entries)),
    )


def _normalise_label(value: str) -> str:
    return " ".join(value.casefold().split())


def _document_scope_labels(document: DocumentRecord) -> set[str]:
    metadata = document.metadata or {}
    values = [
        str(metadata.get(key) or "")
        for key in (
            "legal_anchor",
            "Dieu",
            "Điều",
            "Parent_Dieu",
            "article",
            "Article",
            "appendix",
            "Phụ lục",
            "Phu_luc",
            "source_title",
            "title",
        )
    ]
    labels: set[str] = set()
    for value in values:
        labels.update(_normalise_label(match.group(0)) for match in _ARTICLE_RE.finditer(value))
        labels.update(_normalise_label(match.group(0)) for match in _APPENDIX_RE.finditer(value))
    return labels


class LegalReadinessGate:
    """Runtime gate backed by a re-audited independent manifest."""

    def __init__(
        self,
        manifest_path: str | Path,
        *,
        corpus_sha256: str,
        amendment_map_sha256: str,
        rule_pack_sha256: str,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.corpus_sha256 = corpus_sha256
        self.amendment_map_sha256 = amendment_map_sha256
        self.rule_pack_sha256 = rule_pack_sha256

    @property
    def manifest_sha256(self) -> str:
        return _manifest_sha(self.manifest_path)

    def audit(self) -> LegalReadinessAudit:
        return audit_legal_readiness(
            self.manifest_path,
            corpus_sha256=self.corpus_sha256,
            amendment_map_sha256=self.amendment_map_sha256,
            rule_pack_sha256=self.rule_pack_sha256,
        )

    def allows_documents(self, documents: Sequence[DocumentRecord]) -> tuple[bool, str]:
        audit = self.audit()
        if audit.status is ReadinessStatus.INVALID:
            return False, "legal_readiness_invalid"
        if not audit.legally_ready:
            if not documents:
                return False, "legal_review_pending"
            ready = set(audit.reviewed_anchors)
        else:
            if not documents:
                return False, VerificationStatus.INSUFFICIENT_EVIDENCE.value
            ready = set(EPR_SCOPE_ANCHORS) | set(EPR_SCOPE_APPENDICES)
        normalized_ready = {_normalise_label(item) for item in ready}
        normalized_scope = {
            _normalise_label(item) for item in (*EPR_SCOPE_ANCHORS, *EPR_SCOPE_APPENDICES)
        }
        for document in documents:
            if document.source != "legal":
                return False, "legal_readiness_source_not_legal"
            labels = _document_scope_labels(document)
            scoped_labels = labels.intersection(normalized_scope)
            if not scoped_labels or not scoped_labels.issubset(normalized_ready):
                return False, "legal_review_pending"
            if not _is_true(document.current_law_support, document.metadata):
                return False, "current_law_support_unverified"
        return True, "ok"


class SyntheticReadyLegalReadinessGate:
    """Explicit test dependency for synthetic legal documents.

    Production dependencies use :class:`LegalReadinessGate`; this adapter is
    intentionally named and injected by tests/replay fixtures rather than
    selected by an environment flag.
    """

    def __init__(self, *, ready: bool = True, manifest_sha256: str = "synthetic-ready") -> None:
        self.ready = ready
        self._manifest_sha256 = manifest_sha256

    @property
    def manifest_sha256(self) -> str:
        return self._manifest_sha256

    def audit(self) -> LegalReadinessAudit:
        return LegalReadinessAudit(
            ReadinessStatus.READY if self.ready else ReadinessStatus.PENDING,
            self.ready,
            "ready" if self.ready else "blocked",
            self._manifest_sha256,
            "synthetic",
            "synthetic",
            "synthetic",
            () if self.ready else ("legal_review_pending",),
        )

    def allows_documents(self, documents: Sequence[DocumentRecord]) -> tuple[bool, str]:
        return (True, "ok") if self.ready else (False, "legal_review_pending")


def _is_true(value: object, metadata: dict[str, object]) -> bool:
    if value is None:
        value = metadata.get("Current_Law_Support")
        if value is None:
            value = metadata.get("current_law_support")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"true", "1", "yes", "y", "đúng"}
