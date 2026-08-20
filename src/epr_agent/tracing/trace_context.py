"""OpenTelemetry-compatible Trace & Observability Context for Vietnam Legal Agent.

Tracks detailed execution waterfalls, latency per stage (ms), input/output token usage,
estimated LLM cost, Critic confidence scores, and cache effectiveness.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Price estimates per 1,000,000 tokens (USD)
_DEFAULT_PRICE_MAP = {
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
    "gpt-4o": {"in": 2.50, "out": 10.00},
    "gemini-1.5-flash": {"in": 0.075, "out": 0.30},
    "text-embedding-3-small": {"in": 0.02, "out": 0.0},
}


@dataclass
class Span:
    """An individual execution span within a conversation turn."""

    span_id: str
    name: str
    parent_span_id: str | None = None
    start_time_s: float = field(default_factory=time.perf_counter)
    end_time_s: float | None = None
    duration_ms: float = 0.0
    status: str = "running"  # running, ok, error
    error_message: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)

    def close(
        self,
        status: str = "ok",
        error_message: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "",
        extra_attrs: dict[str, Any] | None = None,
    ) -> None:
        self.end_time_s = time.perf_counter()
        self.duration_ms = round((self.end_time_s - self.start_time_s) * 1000, 2)
        self.status = status
        self.error_message = error_message
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        if model:
            self.model = model
            price = _DEFAULT_PRICE_MAP.get(model, {"in": 0.15, "out": 0.60})
            self.cost_usd = round(
                (input_tokens / 1_000_000.0) * price["in"] + (output_tokens / 1_000_000.0) * price["out"],
                6,
            )
        if extra_attrs:
            self.attributes.update(extra_attrs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error_message": self.error_message,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model": self.model,
            "cost_usd": self.cost_usd,
            "attributes": self.attributes,
        }


@dataclass
class TraceSession:
    """Trace session holding full execution tree for a conversation turn."""

    trace_id: str
    conversation_id: str
    user_id: str
    query: str
    start_time_iso: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    start_time_s: float = field(default_factory=time.perf_counter)
    end_time_s: float | None = None
    total_duration_ms: float = 0.0
    spans: dict[str, Span] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def start_span(self, name: str, parent_span_id: str | None = None, attributes: dict[str, Any] | None = None) -> Span:
        span_id = f"span_{uuid.uuid4().hex[:8]}"
        span = Span(
            span_id=span_id,
            name=name,
            parent_span_id=parent_span_id,
            attributes=attributes or {},
        )
        self.spans[span_id] = span
        return span

    def end_span(
        self,
        span_id: str,
        status: str = "ok",
        error_message: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "",
        extra_attrs: dict[str, Any] | None = None,
    ) -> None:
        if span_id in self.spans:
            self.spans[span_id].close(
                status=status,
                error_message=error_message,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=model,
                extra_attrs=extra_attrs,
            )

    def finish(self, metadata: dict[str, Any] | None = None) -> None:
        self.end_time_s = time.perf_counter()
        self.total_duration_ms = round((self.end_time_s - self.start_time_s) * 1000, 2)
        if metadata:
            self.metadata.update(metadata)

    def to_summary(self) -> dict[str, Any]:
        total_in_tokens = sum(s.input_tokens for s in self.spans.values())
        total_out_tokens = sum(s.output_tokens for s in self.spans.values())
        total_cost = sum(s.cost_usd for s in self.spans.values())

        retrieval_ms = sum(s.duration_ms for s in self.spans.values() if "retrieval" in s.name.lower() or "search" in s.name.lower())
        llm_ms = sum(s.duration_ms for s in self.spans.values() if "llm" in s.name.lower() or "reasoning" in s.name.lower() or "generate" in s.name.lower())

        return {
            "trace_id": self.trace_id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "query": self.query,
            "start_time": self.start_time_iso,
            "total_duration_ms": self.total_duration_ms,
            "total_tokens": total_in_tokens + total_out_tokens,
            "input_tokens": total_in_tokens,
            "output_tokens": total_out_tokens,
            "estimated_cost_usd": round(total_cost, 6),
            "breakdown": {
                "retrieval_ms": retrieval_ms,
                "llm_reasoning_ms": llm_ms,
            },
            "spans_count": len(self.spans),
            "metadata": self.metadata,
        }

    def to_waterfall(self) -> dict[str, Any]:
        summary = self.to_summary()
        summary["spans"] = [s.to_dict() for s in self.spans.values()]
        return summary


class TraceStore:
    """In-memory & SQLite persistent store for trace metrics and telemetry inspection."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._memory_traces: dict[str, TraceSession] = {}
        self.db_path = db_path or Path("data/chat_history.sqlite3")

    def create_trace(self, trace_id: str, conversation_id: str, user_id: str, query: str) -> TraceSession:
        trace = TraceSession(
            trace_id=trace_id,
            conversation_id=conversation_id,
            user_id=user_id,
            query=query,
        )
        self._memory_traces[trace_id] = trace
        return trace

    def get_trace(self, trace_id: str) -> TraceSession | None:
        return self._memory_traces.get(trace_id)

    def list_recent_traces(self, limit: int = 20) -> list[dict[str, Any]]:
        traces = list(self._memory_traces.values())[-limit:]
        return [t.to_summary() for t in reversed(traces)]

    def get_aggregate_metrics(self) -> dict[str, Any]:
        traces = list(self._memory_traces.values())
        if not traces:
            return {
                "total_turns": 0,
                "avg_duration_ms": 0.0,
                "p95_duration_ms": 0.0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "cache_hit_rate": 0.0,
            }

        durations = sorted([t.total_duration_ms for t in traces if t.total_duration_ms > 0])
        total_tokens = sum(s.input_tokens + s.output_tokens for t in traces for s in t.spans.values())
        total_cost = sum(s.cost_usd for t in traces for s in t.spans.values())
        cache_hits = sum(1 for t in traces if t.metadata.get("cache_hit"))

        p95_idx = int(len(durations) * 0.95)
        p95_val = durations[min(p95_idx, len(durations) - 1)] if durations else 0.0

        return {
            "total_turns": len(traces),
            "avg_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0.0,
            "p95_duration_ms": round(p95_val, 2),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "cache_hit_rate": round(cache_hits / len(traces), 3) if traces else 0.0,
        }


_global_trace_store = TraceStore()


def get_trace_store() -> TraceStore:
    return _global_trace_store
