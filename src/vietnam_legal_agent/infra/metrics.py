"""
Prometheus metrics for monitoring the Vietnam Legal Agent backend.

Provides:
- Request latency histograms
- Cache hit/miss rates
- Error rate tracking
- LLM call counts and latency
- Retrieval metrics (FAQ hit rate, legal retrieval success)
"""

from __future__ import annotations

import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# ---------------------------------------------------------------------------
# Metrics Registry
# ---------------------------------------------------------------------------

REGISTRY = CollectorRegistry()

# Request metrics
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
    registry=REGISTRY,
)

HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
    registry=REGISTRY,
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Number of HTTP requests currently being processed",
    ["method", "endpoint"],
    registry=REGISTRY,
)

# Cache metrics
CACHE_HITS = Counter(
    "cache_hits_total",
    "Cache hits",
    ["cache_type"],  # e.g. redis_exact
    registry=REGISTRY,
)

CACHE_MISSES = Counter(
    "cache_misses_total",
    "Cache misses",
    registry=REGISTRY,
)

CACHE_SIZE = Gauge(
    "cache_size_entries",
    "Number of entries in the answer cache",
    registry=REGISTRY,
)

# LLM metrics
LLM_CALLS_TOTAL = Counter(
    "llm_calls_total",
    "Total LLM API calls",
    ["model", "purpose"],  # gpt-4o-mini, routing | gpt-3.5-turbo, generation
    registry=REGISTRY,
)

LLM_CALL_DURATION = Histogram(
    "llm_call_duration_seconds",
    "LLM API call duration in seconds",
    ["model", "purpose"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
    registry=REGISTRY,
)

LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "Total tokens used in LLM calls",
    ["model", "type"],  # prompt, completion
    registry=REGISTRY,
)

# Retrieval metrics
RETRIEVAL_ATTEMPTS = Counter(
    "retrieval_attempts_total",
    "Total retrieval attempts",
    ["retriever", "result"],  # faq, legal | hit, miss
    registry=REGISTRY,
)

RETRIEVAL_LATENCY = Histogram(
    "retrieval_latency_seconds",
    "Retrieval latency in seconds",
    ["retriever"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=REGISTRY,
)

RERANK_LATENCY_MS = Histogram(
    "rerank_latency_ms",
    "Reranker latency in milliseconds",
    ["mode", "engine"],  # apply|shadow, heuristic|cross_encoder
    buckets=[5, 10, 25, 50, 75, 100, 150, 200, 300, 500, 1000],
    registry=REGISTRY,
)

RERANK_TIMEOUT_COUNT = Counter(
    "rerank_timeout_count",
    "Total reranker timeout events",
    ["engine"],
    registry=REGISTRY,
)

RERANK_FALLBACK_COUNT = Counter(
    "rerank_fallback_count",
    "Total reranker fallback events",
    ["reason", "from_engine", "to_engine"],
    registry=REGISTRY,
)

# Pipeline metrics
PIPELINE_STAGE_HITS = Counter(
    "pipeline_stage_hits_total",
    "Pipeline stage hits (where the answer came from)",
    ["stage"],  # cache, faq, legal, chitchat, web_search
    registry=REGISTRY,
)

PIPELINE_STAGE_LATENCY = Histogram(
    "pipeline_stage_latency_seconds",
    "Pipeline stage latency in seconds",
    ["stage"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=REGISTRY,
)

ERRORS_TOTAL = Counter(
    "errors_total",
    "Total errors",
    ["type", "component"],  # redis, qdrant, openai, timeout
    registry=REGISTRY,
)

# Rate limiting
RATE_LIMITED_REQUESTS = Counter(
    "rate_limited_requests_total",
    "Number of rate-limited requests",
    registry=REGISTRY,
)

# User-journey and release-operation metrics.  Labels are intentionally
# low-cardinality reason codes, never conversation IDs, URLs, tokens, or raw
# exception messages.
MIGRATION_FAILURES = Counter(
    "migration_failures_total",
    "Database migration failures",
    ["stage", "code"],
    registry=REGISTRY,
)

CAPABILITY_READINESS = Counter(
    "capability_readiness_observations_total",
    "Capability readiness observations",
    ["capability", "status", "reason"],
    registry=REGISTRY,
)

TURN_TERMINATIONS = Counter(
    "turn_terminations_total",
    "Durable turn terminal states",
    ["status", "reason"],
    registry=REGISTRY,
)

SSE_ERRORS = Counter(
    "sse_errors_total",
    "Structured SSE errors emitted to clients",
    ["code", "retryable"],
    registry=REGISTRY,
)

SESSION_LOAD_FAILURES = Counter(
    "session_load_failures_total",
    "Conversation load failures",
    ["reason"],
    registry=REGISTRY,
)

WEB_RESULT_REJECTIONS = Counter(
    "web_result_rejections_total",
    "Official-web candidates rejected before evidence use",
    ["reason"],
    registry=REGISTRY,
)

FEEDBACK_FAILURES = Counter(
    "feedback_failures_total",
    "Durable feedback failures",
    ["operation", "reason"],
    registry=REGISTRY,
)

REPLAY_OPERATIONS = Counter(
    "replay_operations_total",
    "Retry and regeneration operations",
    ["operation", "result"],
    registry=REGISTRY,
)

ADMISSION_DECISIONS = Counter(
    "admission_decisions_total",
    "Capacity admission and lease-maintenance decisions",
    ["scope", "outcome"],
    registry=REGISTRY,
)

WORKLOAD_DURATION = Histogram(
    "pilot_workload_duration_seconds",
    "End-to-end duration of bounded pilot workloads",
    ["workload", "outcome"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 15, 30, 60, 120, 300),
    registry=REGISTRY,
)

TURN_TIME_TO_FIRST_EVENT = Histogram(
    "agent_turn_time_to_first_event_seconds",
    "Time from accepted chat request to the first runtime SSE event",
    ["pipeline"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 30),
    registry=REGISTRY,
)


# ---------------------------------------------------------------------------
# Helper functions for metrics
# ---------------------------------------------------------------------------

def track_cache_hit(cache_type: str = "exact") -> None:
    """Track a cache hit."""
    CACHE_HITS.labels(cache_type=cache_type).inc()


def track_cache_miss() -> None:
    """Track a cache miss."""
    CACHE_MISSES.inc()


def track_llm_call(model: str, purpose: str) -> None:
    """Track an LLM call."""
    LLM_CALLS_TOTAL.labels(model=model, purpose=purpose).inc()


def track_retrieval(retriever: str, result: str) -> None:
    """Track a retrieval attempt."""
    RETRIEVAL_ATTEMPTS.labels(retriever=retriever, result=result).inc()


def track_pipeline_stage(stage: str) -> None:
    """Track which pipeline stage provided the answer."""
    PIPELINE_STAGE_HITS.labels(stage=stage).inc()


def track_stage_latency(stage: str, seconds: float) -> None:
    """Track latency for a specific pipeline stage."""
    if seconds < 0:
        return
    PIPELINE_STAGE_LATENCY.labels(stage=stage).observe(seconds)


def track_error(error_type: str, component: str) -> None:
    """Track an error."""
    ERRORS_TOTAL.labels(type=error_type, component=component).inc()


def track_rerank_latency_ms(mode: str, engine: str, latency_ms: float) -> None:
    """Track reranker latency in milliseconds."""
    if latency_ms < 0:
        return
    RERANK_LATENCY_MS.labels(mode=mode, engine=engine).observe(latency_ms)


def track_rerank_timeout(engine: str) -> None:
    """Track reranker timeout count."""
    RERANK_TIMEOUT_COUNT.labels(engine=engine).inc()


def track_rerank_fallback(reason: str, from_engine: str, to_engine: str) -> None:
    """Track reranker fallback usage."""
    RERANK_FALLBACK_COUNT.labels(
        reason=reason,
        from_engine=from_engine,
        to_engine=to_engine,
    ).inc()


def _label(value: object, default: str = "unknown") -> str:
    text = str(value or default).strip().lower().replace("-", "_")
    return text[:80] if text and all(char.isalnum() or char in "_:._" for char in text) else default


def track_migration_failure(stage: str, code: str) -> None:
    MIGRATION_FAILURES.labels(stage=_label(stage), code=_label(code)).inc()


def track_capability_readiness(capability: str, status: str, reason: str) -> None:
    CAPABILITY_READINESS.labels(
        capability=_label(capability), status=_label(status), reason=_label(reason)
    ).inc()


def track_turn_termination(status: str, reason: str = "none") -> None:
    TURN_TERMINATIONS.labels(status=_label(status), reason=_label(reason, "none")).inc()


def track_sse_error(code: str, retryable: bool) -> None:
    SSE_ERRORS.labels(code=_label(code), retryable=str(bool(retryable)).lower()).inc()


def track_session_load_failure(reason: str) -> None:
    SESSION_LOAD_FAILURES.labels(reason=_label(reason)).inc()


def track_web_result_rejection(reason: str) -> None:
    WEB_RESULT_REJECTIONS.labels(reason=_label(reason)).inc()


def track_feedback_failure(operation: str, reason: str) -> None:
    FEEDBACK_FAILURES.labels(operation=_label(operation), reason=_label(reason)).inc()


def track_replay_operation(operation: str, result: str) -> None:
    REPLAY_OPERATIONS.labels(operation=_label(operation), result=_label(result)).inc()


def track_admission_decision(scope: str, outcome: str) -> None:
    ADMISSION_DECISIONS.labels(scope=_label(scope), outcome=_label(outcome)).inc()


def track_workload_duration(workload: str, outcome: str, seconds: float) -> None:
    if seconds < 0:
        return
    WORKLOAD_DURATION.labels(
        workload=_label(workload), outcome=_label(outcome)
    ).observe(seconds)


def track_turn_time_to_first_event(pipeline: str, seconds: float) -> None:
    if seconds < 0:
        return
    TURN_TIME_TO_FIRST_EVENT.labels(pipeline=_label(pipeline)).observe(seconds)


# ---------------------------------------------------------------------------
# Prometheus metrics endpoint
# ---------------------------------------------------------------------------

from fastapi.responses import Response as FastAPIResponse


def metrics_endpoint():
    """Return Prometheus metrics."""
    return FastAPIResponse(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )


# ---------------------------------------------------------------------------
# Metrics middleware
# ---------------------------------------------------------------------------

class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to track HTTP request metrics."""

    async def dispatch(self, request: Request, call_next):
        method = request.method
        endpoint = request.url.path
        
        # Skip metrics endpoint itself
        if endpoint == "/internal/metrics":
            return await call_next(request)
        
        start_time = time.time()
        HTTP_REQUESTS_IN_PROGRESS.labels(method=method, endpoint=endpoint).inc()
        
        try:
            response = await call_next(request)
            
            duration = time.time() - start_time
            HTTP_REQUEST_DURATION.labels(method=method, endpoint=endpoint).observe(duration)
            HTTP_REQUESTS_TOTAL.labels(
                method=method, endpoint=endpoint, status_code=str(response.status_code)
            ).inc()
            
            return response
        finally:
            HTTP_REQUESTS_IN_PROGRESS.labels(method=method, endpoint=endpoint).dec()
