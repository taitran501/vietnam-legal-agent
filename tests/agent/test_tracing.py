import pytest
from epr_agent.tracing.trace_context import Span, TraceSession, TraceStore, get_trace_store


def test_span_lifecycle():
    span = Span(span_id="span_123", name="test_span")
    assert span.status == "running"
    assert span.duration_ms == 0.0

    span.close(
        status="ok",
        input_tokens=500,
        output_tokens=150,
        model="gpt-4o-mini",
    )
    assert span.status == "ok"
    assert span.duration_ms >= 0.0
    assert span.input_tokens == 500
    assert span.output_tokens == 150
    assert span.cost_usd > 0.0


def test_trace_session_waterfall():
    session = TraceSession(
        trace_id="tr_001",
        conversation_id="conv_001",
        user_id="user_test",
        query="Thời gian thử việc tối đa?",
    )

    s1 = session.start_span("retrieval")
    session.end_span(s1.span_id, status="ok", input_tokens=100)

    s2 = session.start_span("llm_reasoning", parent_span_id=s1.span_id)
    session.end_span(s2.span_id, status="ok", input_tokens=300, output_tokens=100, model="gpt-4o-mini")

    session.finish(metadata={"cache_hit": False})

    summary = session.to_summary()
    assert summary["trace_id"] == "tr_001"
    assert summary["total_tokens"] == 500
    assert summary["spans_count"] == 2

    waterfall = session.to_waterfall()
    assert len(waterfall["spans"]) == 2
    assert waterfall["spans"][0]["name"] == "retrieval"


def test_trace_store_aggregates():
    store = TraceStore()
    t1 = store.create_trace("t1", "c1", "u1", "query 1")
    t1.finish(metadata={"cache_hit": True})

    t2 = store.create_trace("t2", "c1", "u1", "query 2")
    t2.finish(metadata={"cache_hit": False})

    metrics = store.get_aggregate_metrics()
    assert metrics["total_turns"] == 2
    assert metrics["cache_hit_rate"] == 0.5
