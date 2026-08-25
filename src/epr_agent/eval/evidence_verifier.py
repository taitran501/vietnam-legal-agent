"""Deterministic claim/source verification for replay reports.

This verifier intentionally performs conservative matching.  It does not try
to decide legal semantics from generated prose; it checks that declared claims
and citations are backed by the source records emitted by the runtime.  The
result is engineering evidence, not a legal approval decision.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from epr_agent.eval.contracts import (
    ClaimVerification,
    EvaluationCase,
    EvaluationResult,
    EvaluationStatus,
    ExpectedOutcome,
    FailureCode,
    SourceVerification,
)

_CITATION_RE = re.compile(r"\[(\d+)\]")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _snapshot(document: Mapping[str, Any]) -> dict[str, Any]:
    metadata = dict(document.get("metadata") or {})
    source_id = _text(
        document.get("source_id")
        or metadata.get("source_id")
        or document.get("document_id")
        or metadata.get("source_document_id")
        or metadata.get("parent_id")
        or document.get("id")
    )
    anchor = _text(
        document.get("anchor")
        or metadata.get("anchor")
        or metadata.get("legal_anchor")
        or metadata.get("Dieu")
        or metadata.get("Điều")
    )
    title = _text(document.get("title") or document.get("source_title") or metadata.get("source_title"))
    official_url = _text(
        document.get("official_url")
        or metadata.get("official_url")
        or metadata.get("source_uri")
        or metadata.get("url")
    )
    content = _text(
        document.get("excerpt")
        or document.get("content")
        or document.get("page_content")
        or metadata.get("excerpt")
    )
    instrument = _text(
        document.get("instrument_number")
        or metadata.get("instrument_number")
        or metadata.get("Document_Number")
    )
    return {
        "source_id": source_id,
        "anchor": anchor,
        "title": title,
        "official_url": official_url,
        "instrument_number": instrument,
        "content": content,
        "metadata": metadata,
    }


def _contains(value: str, terms: Sequence[str]) -> list[str]:
    folded = value.casefold()
    return [term for term in terms if _text(term).casefold() in folded]


def _citation_indexes(answer: str) -> set[int]:
    return {int(value) for value in _CITATION_RE.findall(answer)}


def verify_evaluation_case(
    case: EvaluationCase,
    *,
    answer: str,
    documents: list[Mapping[str, Any]],
    source_drawer_documents: list[Mapping[str, Any]] | None = None,
    observed_outcome: ExpectedOutcome | str | None = None,
) -> EvaluationResult:
    """Verify one observed answer against a replay contract."""

    snapshots = [_snapshot(document) for document in documents]
    drawer_snapshots = [_snapshot(document) for document in (source_drawer_documents or documents)]
    answer_text = _text(answer)
    citations = _citation_indexes(answer_text)
    failures: list[FailureCode] = []
    claim_results: list[ClaimVerification] = []
    source_results: list[SourceVerification] = []

    source_positions: dict[str, list[int]] = {}
    for index, snapshot in enumerate(snapshots, start=1):
        if snapshot["source_id"]:
            source_positions.setdefault(snapshot["source_id"], []).append(index)

    drawer_counts = Counter(snapshot["source_id"] for snapshot in drawer_snapshots if snapshot["source_id"])
    for source in case.sources:
        matching = [item for item in snapshots if item["source_id"] == source.source_id]
        drawer_matching = [item for item in drawer_snapshots if item["source_id"] == source.source_id]
        found_anchors = sorted(
            {
                anchor
                for item in matching
                for anchor in source.anchors
                if anchor.casefold() in f"{item['anchor']} {item['content']}".casefold()
            }
        )
        url_matches = bool(source.official_url) and any(
            item["official_url"] == source.official_url for item in drawer_matching
        )
        unique = drawer_counts.get(source.source_id, 0) <= 1
        present = bool(matching)
        source_results.append(
            SourceVerification(
                source_id=source.source_id,
                present=present,
                anchor_matches=found_anchors,
                official_url_matches=url_matches,
                unique_in_drawer=unique,
                reason=(
                    "ok"
                    if present and (not source.anchors or found_anchors)
                    else "source_or_anchor_missing"
                ),
            )
        )
        if not present:
            failures.append(FailureCode.RETRIEVAL_MISS)
        elif source.anchors and not found_anchors:
            failures.append(FailureCode.SOURCE_PROVENANCE_LOSS)
        if source.official_url and drawer_matching and not url_matches:
            failures.append(FailureCode.SOURCE_DRAWER_PAYLOAD_MISMATCH)
        if drawer_matching and not unique:
            failures.append(FailureCode.SOURCE_DRAWER_PAYLOAD_MISMATCH)

    citation_by_claim = {citation.claim_id: citation for citation in case.citations}
    for claim in case.claims:
        expected_sources = set(claim.source_ids)
        available_sources = expected_sources & set(source_positions)
        citation = citation_by_claim.get(claim.claim_id)
        expected_anchor_terms = list(claim.anchors)
        if citation is not None:
            expected_anchor_terms.append(citation.anchor)
        answer_terms = list(claim.match_terms) + expected_anchor_terms
        matched_terms = _contains(answer_text, answer_terms)
        cited = bool(citation and citation.citation_index in citations) if citation else bool(matched_terms)
        supported = bool(available_sources) and bool(matched_terms or cited)
        reason = "ok" if supported else "claim_not_tied_to_answer_and_source"
        claim_results.append(
            ClaimVerification(
                claim_id=claim.claim_id,
                supported=supported,
                cited=cited,
                source_ids=sorted(available_sources),
                anchors=matched_terms,
                reason=reason,
            )
        )
        if claim.required and not supported:
            failures.append(FailureCode.UNSUPPORTED_CLAIM)

    folded_answer = answer_text.casefold()
    if any(term.casefold() in folded_answer for term in case.forbidden_claims):
        failures.append(FailureCode.UNSUPPORTED_CLAIM)

    actual_outcome = _coerce_outcome(observed_outcome)
    if case.expected_outcome is not None and actual_outcome != case.expected_outcome:
        failures.append(
            FailureCode.SAFE_STOP_MISMATCH
            if case.expected_outcome in {ExpectedOutcome.SAFE_STOP, ExpectedOutcome.CLARIFICATION}
            else FailureCode.FOLLOWUP_CONTEXT_LOSS
        )

    unique_failures = list(dict.fromkeys(failures))
    return EvaluationResult(
        case_id=case.case_id,
        status=EvaluationStatus.PASS if not unique_failures else EvaluationStatus.FAIL,
        gate_eligible=True,
        observed_outcome=actual_outcome,
        failure_codes=unique_failures,
        claim_results=claim_results,
        source_results=source_results,
        metadata={"document_count": len(documents), "citation_indexes": sorted(citations)},
    )

def _coerce_outcome(value: ExpectedOutcome | str | None) -> ExpectedOutcome | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, ExpectedOutcome) else ExpectedOutcome(str(value))
    except ValueError:
        return None
