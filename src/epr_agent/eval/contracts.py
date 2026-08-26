"""Versioned contracts for replayable legal evaluation cases.

The runtime deliberately keeps generated prose out of the golden oracle.  An
evaluation case describes expected behavior, claims, and source metadata that
the replay/verifier layer can inspect.  It is an engineering fixture, not a
human-approved legal ground truth.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceStatus(StrEnum):
    INFORMATIONAL = "informational"
    READY = "ready"
    REJECTED = "rejected"


class ExpectedOutcome(StrEnum):
    ANSWER_COMPLETE = "answer_complete"
    SAFE_STOP = "safe_stop"
    CLARIFICATION = "clarification"


class EvaluationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INFORMATIONAL = "informational"
    EVALUATION_UNAVAILABLE = "evaluation_unavailable"


class FailureCode(StrEnum):
    RETRIEVAL_MISS = "retrieval_miss"
    SOURCE_PROVENANCE_LOSS = "source_provenance_loss"
    FOLLOWUP_CONTEXT_LOSS = "followup_context_loss"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    WRONG_EFFECTIVE_DATE = "wrong_effective_date"
    SOURCE_DRAWER_PAYLOAD_MISMATCH = "source_drawer_payload_mismatch"
    SAFE_STOP_MISMATCH = "safe_stop_mismatch"
    EVALUATOR_UNAVAILABLE = "evaluator_unavailable"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    LATENCY = "latency"


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvalTurn(_ContractModel):
    """One user turn in a replayable conversation."""

    query: str = Field(min_length=1)
    expected_outcome: ExpectedOutcome | None = None
    expected_claim_ids: list[str] = Field(default_factory=list)
    expected_behavior: str = ""


class ExpectedClaim(_ContractModel):
    """A claim-level oracle that does not require exact generated wording."""

    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1, description="Source-backed claim description")
    kind: str = Field(default="legal_rule", min_length=1)
    required: bool = True
    source_ids: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    match_terms: list[str] = Field(default_factory=list)


class AuthoritativeSource(_ContractModel):
    """Canonical source metadata used by the evidence verifier."""

    source_id: str = Field(min_length=1)
    instrument_number: str = ""
    title: str = ""
    authority: str = ""
    official_url: str = ""
    anchors: list[str] = Field(default_factory=list)
    corpus_sha: str = ""
    effective_from: str | None = None
    effective_to: str | None = None
    effective_status: str = ""


class ExpectedCitation(_ContractModel):
    """Mapping from an expected claim to a canonical source anchor."""

    claim_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    citation_index: int | None = Field(default=None, ge=1)


class EvidenceMetadata(_ContractModel):
    status: EvidenceStatus = EvidenceStatus.INFORMATIONAL
    corpus_sha: str = ""
    notes: str = ""


class EvaluationCase(_ContractModel):
    """Replayable multi-turn evaluation fixture."""

    case_id: str = Field(min_length=1)
    domain: str = "legal"
    turns: list[EvalTurn] = Field(min_length=1)
    expected_outcome: ExpectedOutcome | None = None
    claims: list[ExpectedClaim] = Field(default_factory=list)
    sources: list[AuthoritativeSource] = Field(default_factory=list)
    citations: list[ExpectedCitation] = Field(default_factory=list)
    allowed_omissions: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    follow_up_expected_behavior: list[ExpectedOutcome] = Field(default_factory=list)
    evidence: EvidenceMetadata = Field(default_factory=EvidenceMetadata)

    @model_validator(mode="after")
    def validate_references(self) -> EvaluationCase:
        claim_ids = {claim.claim_id for claim in self.claims}
        source_ids = {source.source_id for source in self.sources}
        if len(claim_ids) != len(self.claims):
            raise ValueError("claims must have unique claim_id values")
        if len(source_ids) != len(self.sources):
            raise ValueError("sources must have unique source_id values")
        unknown_claims = {
            citation.claim_id for citation in self.citations if citation.claim_id not in claim_ids
        }
        if unknown_claims:
            raise ValueError(f"citations reference unknown claims: {sorted(unknown_claims)}")
        unknown_sources = {
            citation.source_id for citation in self.citations if citation.source_id not in source_ids
        }
        if unknown_sources:
            raise ValueError(f"citations reference unknown sources: {sorted(unknown_sources)}")
        return self


class ClaimVerification(_ContractModel):
    claim_id: str
    supported: bool
    cited: bool = False
    source_ids: list[str] = Field(default_factory=list)
    anchors: list[str] = Field(default_factory=list)
    reason: str = ""


class SourceVerification(_ContractModel):
    source_id: str
    present: bool
    present_in_drawer: bool = False
    anchor_matches: list[str] = Field(default_factory=list)
    official_url_matches: bool = False
    unique_in_drawer: bool = True
    reason: str = ""


class EvaluationResult(_ContractModel):
    """Structured report emitted by deterministic or live replay."""

    case_id: str
    status: EvaluationStatus
    gate_eligible: bool = False
    observed_outcome: ExpectedOutcome | None = None
    failure_codes: list[FailureCode] = Field(default_factory=list)
    claim_results: list[ClaimVerification] = Field(default_factory=list)
    source_results: list[SourceVerification] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_evaluation_case(path: str | Path) -> EvaluationCase:
    """Load and validate one replay fixture from disk."""

    fixture_path = Path(path)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    return EvaluationCase.model_validate(payload)
