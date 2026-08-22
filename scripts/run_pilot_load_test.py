"""Exercise the 50-active-turn pilot SLO against a two-worker SSE host."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class TurnMeasurement:
    turn: int
    ttfe_seconds: float
    completion_seconds: float
    terminal_type: str
    error_code: str = ""


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


async def read_sse(
    client: httpx.AsyncClient,
    *,
    url: str,
    turn: int,
    first_event_callback: Callable[[], Awaitable[None]] | None = None,
) -> TurnMeasurement:
    started = time.perf_counter()
    first_event_at: float | None = None
    terminal: dict[str, Any] = {}
    async with client.stream("POST", url, json={"turn": turn}) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line.removeprefix("data: "))
            if first_event_at is None:
                first_event_at = time.perf_counter()
                if first_event_callback is not None:
                    await first_event_callback()
            if event.get("type") in {"response_complete", "error"}:
                terminal = event
                break
    completed = time.perf_counter()
    if first_event_at is None or not terminal:
        raise AssertionError(f"turn {turn} did not produce a complete SSE trajectory")
    return TurnMeasurement(
        turn=turn,
        ttfe_seconds=first_event_at - started,
        completion_seconds=completed - started,
        terminal_type=str(terminal["type"]),
        error_code=str(terminal.get("code") or ""),
    )


async def verify_disconnect_cleanup(client: httpx.AsyncClient, base_url: str) -> None:
    async with client.stream("POST", f"{base_url}/disconnect?hold_seconds=30") as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                break
    await asyncio.sleep(0.25)
    follow_up = await read_sse(
        client,
        url=f"{base_url}/disconnect?hold_seconds=0.01",
        turn=52,
    )
    if follow_up.terminal_type != "response_complete":
        raise AssertionError("disconnect did not release its admission lease")


async def run(base_url: str, report_path: Path) -> None:
    limits = httpx.Limits(max_connections=80, max_keepalive_connections=80)
    timeout = httpx.Timeout(35)
    first_event_count = 0
    first_event_lock = asyncio.Lock()
    all_admitted = asyncio.Event()

    async def mark_first_event() -> None:
        nonlocal first_event_count
        async with first_event_lock:
            first_event_count += 1
            if first_event_count == 50:
                all_admitted.set()

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        turns = [
            asyncio.create_task(
                read_sse(
                    client,
                    url=f"{base_url}/load",
                    turn=index,
                    first_event_callback=mark_first_event,
                )
            )
            for index in range(1, 51)
        ]
        await asyncio.wait_for(all_admitted.wait(), timeout=10)
        overflow = await read_sse(client, url=f"{base_url}/load", turn=51)
        measurements = await asyncio.gather(*turns)
        await verify_disconnect_cleanup(client, base_url)

    p95_ttfe = percentile([item.ttfe_seconds for item in measurements], 0.95)
    p95_completion = percentile([item.completion_seconds for item in measurements], 0.95)
    system_errors = [item for item in measurements if item.terminal_type != "response_complete"]
    report = {
        "active_turns": len(measurements),
        "p95_ttfe_seconds": p95_ttfe,
        "p95_completion_seconds": p95_completion,
        "system_errors": len(system_errors),
        "overflow": asdict(overflow),
        "disconnect_cleanup": "passed",
        "turns": [asdict(item) for item in measurements],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    failures: list[str] = []
    if p95_ttfe > 3:
        failures.append(f"p95 TTFE {p95_ttfe:.3f}s exceeds 3s")
    if p95_completion > 30:
        failures.append(f"p95 completion {p95_completion:.3f}s exceeds 30s")
    if system_errors:
        failures.append(f"{len(system_errors)} of 50 turns ended with errors")
    if overflow.error_code != "capacity_exceeded":
        failures.append(f"turn 51 was not controlled: {overflow.error_code or overflow.terminal_type}")
    if failures:
        raise SystemExit("; ".join(failures))
    print(json.dumps({key: value for key, value in report.items() if key != "turns"}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--report", type=Path, default=Path("artifacts/pilot-load-report.json"))
    args = parser.parse_args()
    asyncio.run(run(args.base_url.rstrip("/"), args.report))


if __name__ == "__main__":
    main()
