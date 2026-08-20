from __future__ import annotations

import pytest
from backend.config import Settings, validate_production_settings


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "corpus_runtime_mode": "production",
        "openai_api_key": "sk-test-key",
        "database_url": "postgresql://epr:secret@postgres:5432/epr",
        "use_qdrant_cloud": False,
        "qdrant_url": "http://qdrant:6333",
        "require_auth": True,
        "api_keys": "a-real-test-key",
        "allowed_origins": "https://app.example.com",
    }
    values.update(overrides)
    return Settings(**values)


def test_valid_production_settings_pass() -> None:
    validate_production_settings(_production_settings())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("require_auth", False, "REQUIRE_AUTH"),
        ("rate_limit_fail_open", True, "RATE_LIMIT_FAIL_OPEN"),
        ("enable_trace_debug_api", True, "ENABLE_TRACE_DEBUG_API"),
        ("enable_universal_retrieval", True, "ENABLE_UNIVERSAL_RETRIEVAL"),
        ("database_url", None, "DATABASE_URL"),
        ("database_url", "sqlite:///tmp/local.db", "DATABASE_URL"),
        ("openai_api_key", "", "OPENAI_API_KEY"),
        ("qdrant_url", None, "QDRANT_URL"),
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
