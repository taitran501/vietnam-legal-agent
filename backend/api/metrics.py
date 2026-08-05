"""
Prometheus metrics for monitoring the EPR chatbot.

Provides:
- Request latency histograms
- Cache hit/miss rates
- Error rate tracking
- LLM call counts and latency
- Retrieval metrics (FAQ hit rate, legal retrieval success)
"""

from __future__ import annotations

import time
from typing import Optional

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from starlette.responses import Response
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
    ["cache_type"],  # exact, semantic
    registry=REGISTRY,
)

CACHE_MISSES = Counter(
    "cache_misses_total",
    "Cache misses",
    registry=REGISTRY,
)

CACHE_SIZE = Gauge(
    "cache_size_entries",
    "Number of entries in semantic cache",
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
        if endpoint == "/metrics":
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
