from __future__ import annotations

import pytest

from vietnam_legal_agent.config import Settings, validate_production_settings


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "corpus_runtime_mode": "production",
        "openai_api_key": "sk-test-key",
        "database_url": "postgresql://vietnam_legal_agent:secret@postgres:5432/vietnam_legal_agent",
        "use_qdrant_cloud": False,
        "qdrant_url": "http://qdrant:6333",
        "require_auth": True,
        "enforce_legal_readiness_gate": True,
        "enable_universal_retrieval": True,
        "api_keys": "a-real-test-key",
        "allowed_origins": "https://app.example.com",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_waits_for_domain_neutral_corpus_review() -> None:
    with pytest.raises(ValueError, match="matching legal-review approval"):
        validate_production_settings(_production_settings())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("require_auth", False, "REQUIRE_AUTH"),
        ("rate_limit_fail_open", True, "RATE_LIMIT_FAIL_OPEN"),
        ("enable_trace_debug_api", True, "ENABLE_TRACE_DEBUG_API"),
        ("enable_universal_retrieval", False, "ENABLE_UNIVERSAL_RETRIEVAL"),
        ("enable_official_delta_retrieval", True, "ENABLE_OFFICIAL_DELTA_RETRIEVAL"),
        ("enforce_legal_safety_circuit_breaker", False, "ENFORCE_LEGAL_SAFETY_CIRCUIT_BREAKER"),
        ("enforce_legal_readiness_gate", False, "ENFORCE_LEGAL_READINESS_GATE"),
        ("database_url", None, "DATABASE_URL"),
        ("database_url", "sqlite:///tmp/local.db", "DATABASE_URL"),
        ("openai_api_key", "", "OPENAI_API_KEY"),
        ("api_keys", "", "configure API_KEYS"),
        ("allowed_origins", "http://localhost:3000", "HTTPS origins"),
    ],
)
def test_unsafe_production_setting_fails_fast(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_production_settings(_production_settings(**{field: value}))


def test_preview_mode_allows_local_development_defaults() -> None:
    settings = Settings(
        _env_file=None,
        corpus_runtime_mode="preview",
        require_auth=False,
        openai_api_key="",
        database_url=None,
        qdrant_url=None,
        allowed_origins="http://localhost:3000",
    )

    validate_production_settings(settings)


def test_general_legal_corpus_is_the_default_runtime_source() -> None:
    settings = Settings(_env_file=None)

    assert settings.enable_universal_retrieval is True
    assert settings.corpus_id == "vietnamese_law"
    assert settings.enable_qdrant_retrieval is False


def test_broad_corpus_requires_legal_review_before_production() -> None:
    with pytest.raises(ValueError, match="matching legal-review approval"):
        validate_production_settings(_production_settings(enable_universal_retrieval=True))
