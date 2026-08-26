"""Replay deterministic natural-language SSE contracts against a running API.

The runner deliberately evaluates structured routing, termination, context and
source provenance fields. It never compares generated prose byte-for-byte and
does not enable a live provider.

Usage:
    python scripts/run_natural_language_smoke.py \
        --base-url http://127.0.0.1:8010 \
        --report artifacts/natural-language-smoke.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "data" / "eval" / "natural_language_smoke.json"


def _source_records(terminal: dict[str, Any]) -> list[dict[str, Any]]:
    sources = terminal.get("sources")
    if isinstance(sources, list):
        return [item for item in sources if isinstance(item, dict)]
    return []


def _documents(terminal: dict[str, Any]) -> list[dict[str, Any]]:
    documents = terminal.get("documents")
    if isinstance(documents, list):
        return [item for item in documents if isinstance(item, dict)]
    return []


def _retrieval_count(events: list[dict[str, Any]]) -> int:
    """Count retrieval/evidence phases without depending on generated prose."""

    actions = {
        str(event.get("action") or "")
        for event in events
        if event.get("type") == "workflow_step"
    }
    return sum(action in {"retrieve_legal", "retrieve_web", "check_evidence"} for action in actions)


def evaluate_turn_contract(
    events: list[dict[str, Any]],
    expected: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    terminals = [
        event
        for event in events
        if event.get("type") in {"response_complete", "response_stopped", "error"}
    ]
    terminal = terminals[-1] if terminals else {}
    sources = _source_records(terminal)
    documents = _documents(terminal)
    source_ids = [str(source.get("source_id") or "") for source in sources if source.get("source_id")]
    anchors = [str(source.get("anchor") or "") for source in sources if source.get("anchor")]
    instruments = [
        str(source.get("instrument_number") or "")
        for source in sources
        if source.get("instrument_number")
    ]
    observed = {
        "terminal_type": str(terminal.get("type") or ""),
        "route": str(terminal.get("route") or ""),
        "termination_reason": str(terminal.get("termination_reason") or ""),
        "safe_stop_reason": str(terminal.get("safe_stop_reason") or ""),
        "context_loaded": terminal.get("context_loaded"),
        "history_messages": terminal.get("history_messages"),
        "is_follow_up": terminal.get("is_follow_up"),
        "standalone_query": str(terminal.get("standalone_query") or ""),
        "source_ids": source_ids,
        "anchors": anchors,
        "instruments": instruments,
        "sources_count": len(sources),
        "documents_count": len(documents),
        "retrieval_count": _retrieval_count(events),
        "trace_id": str(terminal.get("trace_id") or ""),
    }
    failures: list[str] = []

    def check_equal(field: str) -> None:
        if field in expected and observed.get(field) != expected[field]:
            failures.append(f"{field}: expected {expected[field]!r}, got {observed.get(field)!r}")

    check_equal("route")
    check_equal("termination_reason")
    check_equal("safe_stop_reason")
    check_equal("context_loaded")
    check_equal("history_messages")
    check_equal("is_follow_up")
    if expected.get("source_empty") and sources:
        failures.append(f"source_empty: expected no canonical sources, got {len(sources)}")
    if expected.get("source_nonempty") and not sources:
        failures.append("source_nonempty: no canonical source snapshot was returned")
    if "retrieval_count_exact" in expected and observed["retrieval_count"] != expected["retrieval_count_exact"]:
        failures.append(
            f"retrieval_count: expected exactly {expected['retrieval_count_exact']}, got {observed['retrieval_count']}"
        )
    if "retrieval_count_min" in expected and observed["retrieval_count"] < expected["retrieval_count_min"]:
        failures.append(
            f"retrieval_count: expected at least {expected['retrieval_count_min']}, got {observed['retrieval_count']}"
        )
    anchor = str(expected.get("anchor_contains") or "")
    if anchor and not any(anchor.casefold() in value.casefold() for value in anchors):
        failures.append(f"anchor_contains: {anchor!r} not found in {anchors!r}")
    instrument = str(expected.get("instrument_contains") or "")
    if instrument and not any(instrument.casefold() in value.casefold() for value in instruments):
        failures.append(f"instrument_contains: {instrument!r} not found in {instruments!r}")
    for fragment in expected.get("standalone_contains") or []:
        if str(fragment).casefold() not in observed["standalone_query"].casefold():
            failures.append(f"standalone_contains: {fragment!r} missing")
    if not terminal:
        failures.append("no terminal SSE event received")
    return observed, failures


async def _replay_turn(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    conversation_id: str,
    query: str,
    turn_index: int,
    case_id: str,
    expected: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    events: list[dict[str, Any]] = []
    payload = {
        "query": query,
        "conversation_id": conversation_id,
        "turn_id": f"natural-smoke-{case_id}-{turn_index}-{uuid.uuid4().hex[:8]}",
        "mode": "auto",
        "operation": "message",
        "intent_hint": "auto",
        "interaction_source": "composer",
    }
    transport_error = ""
    try:
        async with client.stream("POST", f"{base_url.rstrip('/')}/api/v1/chat", json=payload) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line.removeprefix("data:").strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
    except (httpx.HTTPError, OSError) as exc:
        transport_error = f"{type(exc).__name__}: {exc}"

    observed, failures = evaluate_turn_contract(events, expected)
    if transport_error:
        failures.append(f"provider_or_transport: {transport_error}")
    return {
        "case_id": case_id,
        "turn_index": turn_index,
        "query": query,
        "conversation_id": conversation_id,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "passed": not failures,
        "failure_reasons": failures,
        "observed": observed,
        "events_count": len(events),
    }


async def run_fixture(fixture_path: Path, base_url: str) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if fixture.get("mode") != "deterministic":
        raise ValueError("natural-language smoke only accepts deterministic fixtures")
    results: list[dict[str, Any]] = []
    timeout = httpx.Timeout(35.0, connect=5.0)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=20)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        for case in fixture.get("cases") or []:
            case_id = str(case.get("id") or "unknown")
            conversation_id = str(case.get("conversation_id") or f"smoke-{case_id}")
            for turn_index, turn in enumerate(case.get("turns") or [], start=1):
                results.append(
                    await _replay_turn(
                        client,
                        base_url=base_url,
                        conversation_id=conversation_id,
                        query=str(turn.get("query") or ""),
                        turn_index=turn_index,
                        case_id=case_id,
                        expected=dict(turn.get("expect") or {}),
                    )
                )
    failures = [item for item in results if not item["passed"]]
    return {
        "schema_version": "natural-language-smoke-report-v1",
        "fixture": str(fixture_path),
        "mode": "deterministic",
        "base_url": base_url,
        "turns": results,
        "summary": {
            "total": len(results),
            "passed": len(results) - len(failures),
            "failed": len(failures),
            "pass_rate": round((len(results) - len(failures)) / len(results), 4) if results else 0.0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay deterministic natural-language SSE contracts.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts" / "natural-language-smoke.json")
    args = parser.parse_args()
    report = asyncio.run(run_fixture(args.fixture.resolve(), args.base_url))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    if report["summary"]["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
