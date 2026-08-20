from __future__ import annotations

from epr_agent.infra import metrics


def test_release_user_journey_metrics_are_exported_with_bounded_labels() -> None:
    metrics.track_migration_failure("startup", "database_schema_mismatch")
    metrics.track_capability_readiness("legal_chat", "blocked", "corpus_promotion_blocked")
    metrics.track_turn_termination("stopped", "user_cancelled")
    metrics.track_sse_error("pipeline_error", True)
    metrics.track_session_load_failure("storage_unavailable")
    metrics.track_web_result_rejection("relevance_or_anchor_mismatch")
    metrics.track_feedback_failure("put", "storage_unavailable")
    metrics.track_replay_operation("regenerate", "failed")

    payload = metrics.metrics_endpoint().body.decode("utf-8")

    assert 'migration_failures_total{code="database_schema_mismatch",stage="startup"}' in payload
    assert 'capability_readiness_observations_total{capability="legal_chat",reason="corpus_promotion_blocked",status="blocked"}' in payload
    assert 'turn_terminations_total{reason="user_cancelled",status="stopped"}' in payload
    assert 'sse_errors_total{code="pipeline_error",retryable="true"}' in payload
    assert 'session_load_failures_total{reason="storage_unavailable"}' in payload
    assert 'web_result_rejections_total{reason="relevance_or_anchor_mismatch"}' in payload
    assert 'feedback_failures_total{operation="put",reason="storage_unavailable"}' in payload
    assert 'replay_operations_total{operation="regenerate",result="failed"}' in payload
