"""Promptfoo assertions delegating quality semantics to internal reports.

Promptfoo is only the matrix/CI wrapper.  The replay report and the internal
claim/source verifier remain the source of truth; this module checks that the
JSON adapter did not lose any of those fields on the way to Promptfoo.
"""

from __future__ import annotations

import json
from typing import Any

from epr_agent.eval.contracts import EvaluationCase, FailureCode
from epr_agent.eval.replay import load_cases

_ALLOWED_FAILURE_CODES = {code.value for code in FailureCode}
_TERMINAL_TYPES = {"response_complete", "response_stopped", "error"}


def _source_id(document: Any) -> str:
    if not isinstance(document, dict):
        return ""
    metadata = document.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return str(
        document.get("source_id")
        or metadata.get("source_id")
        or document.get("document_id")
        or metadata.get("source_document_id")
        or ""
    ).strip()


def _check_failure_taxonomy(result: dict[str, Any], label: str, errors: list[str]) -> None:
    raw_codes = result.get("failure_codes")
    if not isinstance(raw_codes, list):
        errors.append(f"{label}: failure_codes must be a list")
        return

    codes = [str(code) for code in raw_codes]
    unknown_codes = sorted(set(codes) - _ALLOWED_FAILURE_CODES)
    if unknown_codes:
        errors.append(f"{label}: unknown failure taxonomy {unknown_codes}")
    status = str(result.get("status") or "")
    if status == "pass" and codes:
        errors.append(f"{label}: passing result contains failure_codes {codes}")
    if status == "fail" and not codes:
        errors.append(f"{label}: failed result has no failure code")


def _check_result(result: Any, label: str, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        errors.append(f"{label}: result is not an object")
        return None

    _check_failure_taxonomy(result, label, errors)
    metadata = result.get("metadata")
    for status_key in ("evaluator_status", "provider_status"):
        status = result.get(status_key)
        if status is None and isinstance(metadata, dict):
            status = metadata.get(status_key)
        if status is not None and str(status) != "ok":
            errors.append(f"{label}: {status_key} is unavailable ({status})")
    if result.get("status") != "pass":
        errors.append(f"{label}: status is {result.get('status')!r}")
    if result.get("gate_eligible") is not True:
        errors.append(f"{label}: gate_eligible is not true")
    return result


def _load_case_from_context(context: dict[str, Any], errors: list[str]) -> EvaluationCase | None:
    variables = context.get("vars") if isinstance(context, dict) else None
    variables = variables if isinstance(variables, dict) else {}
    fixture = str(variables.get("fixture") or "").strip()
    if not fixture:
        # Keep the assertion useful for callers that only have the raw
        # replay JSON. Promptfoo itself always supplies vars.fixture, which
        # enables the stronger claim/source checks below.
        return None
    try:
        cases = load_cases(fixture)
    except Exception as exc:  # noqa: BLE001 - assertion must fail with a useful reason
        errors.append(f"fixture could not be loaded: {exc}")
        return None
    if len(cases) != 1:
        errors.append(f"fixture must contain exactly one case, got {len(cases)}")
        return None
    return cases[0]


def _check_claims_and_sources(
    case: EvaluationCase,
    result: dict[str, Any],
    final_turn: dict[str, Any],
    errors: list[str],
) -> None:
    claim_results = result.get("claim_results")
    source_results = result.get("source_results")
    if not isinstance(claim_results, list):
        errors.append("result: claim_results must be a list")
        claim_results = []
    if not isinstance(source_results, list):
        errors.append("result: source_results must be a list")
        source_results = []

    claims_by_id = {
        str(item.get("claim_id")): item
        for item in claim_results
        if isinstance(item, dict) and item.get("claim_id")
    }
    sources_by_id = {
        str(item.get("source_id")): item
        for item in source_results
        if isinstance(item, dict) and item.get("source_id")
    }
    citations_by_claim = {citation.claim_id: citation for citation in case.citations}

    for claim in case.claims:
        observed = claims_by_id.get(claim.claim_id)
        if observed is None:
            errors.append(f"claim {claim.claim_id}: missing verifier result")
            continue
        if claim.required and observed.get("supported") is not True:
            errors.append(f"claim {claim.claim_id}: required claim is unsupported")
        citation = citations_by_claim.get(claim.claim_id)
        if citation is not None:
            if observed.get("cited") is not True:
                errors.append(f"claim {claim.claim_id}: expected citation is missing")
            if citation.source_id not in set(observed.get("source_ids") or []):
                errors.append(f"claim {claim.claim_id}: citation source mismatch")
            source_observed = sources_by_id.get(citation.source_id)
            if source_observed is None or citation.anchor not in set(source_observed.get("anchor_matches") or []):
                errors.append(f"claim {claim.claim_id}: citation anchor mismatch")

    for source in case.sources:
        observed = sources_by_id.get(source.source_id)
        if observed is None:
            errors.append(f"source {source.source_id}: missing verifier result")
            continue
        if observed.get("present") is not True:
            errors.append(f"source {source.source_id}: missing from retrieved documents")
        if observed.get("present_in_drawer") is not True:
            errors.append(f"source {source.source_id}: missing from source drawer")
        if source.official_url and observed.get("official_url_matches") is not True:
            errors.append(f"source {source.source_id}: official URL mismatch")
        if observed.get("unique_in_drawer") is not True:
            errors.append(f"source {source.source_id}: duplicated in source drawer")

    drawer = final_turn.get("source_drawer")
    if not isinstance(drawer, list):
        errors.append("final turn: source_drawer must be a list")
        drawer = []
    drawer_ids = {_source_id(document) for document in drawer}
    for source in case.sources:
        if source.source_id not in drawer_ids:
            errors.append(f"source {source.source_id}: source drawer payload mismatch")

    metadata = result.get("metadata")
    citation_indexes = set(metadata.get("citation_indexes") or []) if isinstance(metadata, dict) else set()
    for citation in case.citations:
        if citation.citation_index is not None and citation.citation_index not in citation_indexes:
            errors.append(f"claim {citation.claim_id}: citation index {citation.citation_index} missing")


def _check_replay_report(report: Any, case: EvaluationCase | None) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return ["replay output is not a JSON object"]
    if report.get("schema_version") != "evaluation-replay-v1":
        errors.append(f"unexpected schema_version {report.get('schema_version')!r}")
    if report.get("mode") != "deterministic":
        errors.append("Promptfoo PR provider must run deterministic replay")
    if not str(report.get("commit_sha") or "").strip():
        errors.append("missing commit_sha")
    if not str(report.get("config_hash") or "").strip():
        errors.append("missing config_hash")

    result = _check_result(report.get("result"), "result", errors)
    turns = report.get("turns")
    if not isinstance(turns, list) or not turns:
        errors.append("turns must be a non-empty list")
        turns = []
    if case is not None:
        if report.get("case_id") != case.case_id:
            errors.append(f"case_id mismatch: {report.get('case_id')!r} != {case.case_id!r}")
        if len(turns) != len(case.turns):
            errors.append(f"turn count mismatch: {len(turns)} != {len(case.turns)}")

    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            errors.append(f"turn {index + 1}: not an object")
            continue
        terminal_type = str(turn.get("terminal_type") or "")
        if terminal_type not in _TERMINAL_TYPES:
            errors.append(f"turn {index + 1}: invalid terminal type {terminal_type!r}")
        if not isinstance(turn.get("events"), list):
            errors.append(f"turn {index + 1}: events must be a list")
        _check_result(turn.get("evaluation"), f"turn {index + 1} evaluation", errors)
        if case is not None and index < len(case.turns):
            expected = case.turns[index].expected_outcome
            if expected is None and index == len(case.turns) - 1:
                expected = case.expected_outcome
            if expected is not None and turn.get("observed_outcome") != expected.value:
                errors.append(
                    f"turn {index + 1}: outcome {turn.get('observed_outcome')!r} != {expected.value!r}"
                )

    if case is not None and result is not None and turns and isinstance(turns[-1], dict):
        _check_claims_and_sources(case, result, turns[-1], errors)
    return errors

def get_assert(output: str, context: dict[str, Any]) -> dict[str, Any]:
    try:
        report = json.loads(output)
    except (TypeError, json.JSONDecodeError) as exc:
        return {"pass": False, "score": 0.0, "reason": f"invalid replay report: {exc}"}

    errors: list[str] = []
    case = _load_case_from_context(context, errors)
    errors.extend(_check_replay_report(report, case))
    passed = not errors
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "replay passed" if passed else "replay failed: " + "; ".join(errors),
    }

