"""
Tests for LLM instance configuration.

Tests cover:
- All 4 LLM instances have 30s timeout configured
- Correct models are used for each instance
- Temperature settings are correct
- Streaming configuration
"""

from types import SimpleNamespace

import pytest

from vietnam_legal_agent.config import Settings, get_settings
from vietnam_legal_agent.infra.llm_instances import (
    GeminiPooledChat,
    LocalSentenceTransformerEmbeddings,
    clear_gemini_key_manager,
    get_embeddings,
    get_llm_fast,
    get_llm_router,
    get_llm_smart,
    get_llm_stream,
)


@pytest.fixture(autouse=True)
def deterministic_provider_configuration(monkeypatch: pytest.MonkeyPatch):
    """Construct provider clients without relying on a developer's local .env."""
    monkeypatch.setenv("OPENAI_API_KEY", "ci-unit-test-placeholder")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "auto")
    monkeypatch.setenv("EMBEDDING_PROFILE", "openai-text-embedding-3-small-v1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    get_embeddings.cache_clear()
    get_llm_fast.cache_clear()
    get_llm_router.cache_clear()
    get_llm_smart.cache_clear()
    get_llm_stream.cache_clear()
    clear_gemini_key_manager()


class TestLLMInstances:
    """Test LLM instance configuration."""

    def test_llm_fast_timeout(self):
        """llm_fast should have 30s timeout configured."""
        # Clear cache to get fresh instance
        get_llm_fast.cache_clear()
        llm = get_llm_fast()
        assert llm.request_timeout == 30

    def test_llm_fast_model(self):
        """llm_fast should use gpt-3.5-turbo."""
        get_llm_fast.cache_clear()
        llm = get_llm_fast()
        assert llm.model_name == "gpt-3.5-turbo"

    def test_llm_fast_temperature(self):
        """llm_fast should have temperature=0."""
        get_llm_fast.cache_clear()
        llm = get_llm_fast()
        assert llm.temperature == 0

    def test_llm_router_timeout(self):
        """llm_router should have 30s timeout configured."""
        get_llm_router.cache_clear()
        llm = get_llm_router()
        assert llm.request_timeout == 30

    def test_llm_router_model(self):
        """llm_router should use gpt-4o-mini."""
        get_llm_router.cache_clear()
        llm = get_llm_router()
        assert llm.model_name == "gpt-4o-mini"

    def test_llm_router_temperature(self):
        """llm_router should have temperature=0."""
        get_llm_router.cache_clear()
        llm = get_llm_router()
        assert llm.temperature == 0

    def test_llm_smart_timeout(self):
        """llm_smart should have 30s timeout configured."""
        get_llm_smart.cache_clear()
        llm = get_llm_smart()
        assert llm.request_timeout == 30

    def test_llm_smart_model(self):
        """llm_smart should use gpt-4o-mini."""
        get_llm_smart.cache_clear()
        llm = get_llm_smart()
        assert llm.model_name == "gpt-4o-mini"

    def test_llm_smart_temperature(self):
        """llm_smart should have temperature=0."""
        get_llm_smart.cache_clear()
        llm = get_llm_smart()
        assert llm.temperature == 0

    def test_llm_stream_timeout(self):
        """llm_stream should have 30s timeout configured."""
        get_llm_stream.cache_clear()
        llm = get_llm_stream()
        assert llm.request_timeout == 30

    def test_llm_stream_model(self):
        """llm_stream should use gpt-3.5-turbo."""
        get_llm_stream.cache_clear()
        llm = get_llm_stream()
        assert llm.model_name == "gpt-3.5-turbo"

    def test_llm_stream_temperature(self):
        """llm_stream should have temperature=0."""
        get_llm_stream.cache_clear()
        llm = get_llm_stream()
        assert llm.temperature == 0

    def test_llm_stream_streaming_enabled(self):
        """llm_stream should have streaming enabled."""
        get_llm_stream.cache_clear()
        llm = get_llm_stream()
        assert llm.streaming is True

    def test_embeddings_model(self):
        """embeddings should use configured provider model."""
        get_embeddings.cache_clear()
        embeddings = get_embeddings()
        model_name = getattr(embeddings, "model_name", getattr(embeddings, "model", ""))
        assert model_name in ["darklethelong/vnlegal-lal", "text-embedding-3-small", "bkai-foundation-models/vietnamese-bi-encoder"]

    def test_local_provider_rejects_openai_index_profile(self):
        with pytest.raises(ValueError, match="Query and indexed vectors must use the same model"):
            Settings(
                embedding_provider="local",
                embedding_profile="openai-text-embedding-3-small-v1",
                openai_api_key="ci-unit-test-placeholder",
            )

    def test_auto_provider_does_not_fallback_to_a_different_vector_space(self, monkeypatch):
        from vietnam_legal_agent.infra import llm_instances

        monkeypatch.setattr(
            llm_instances,
            "get_settings",
            lambda: SimpleNamespace(
                embedding_provider="auto",
                embedding_profile="openai-text-embedding-3-small-v1",
                openai_api_key="",
                embedding_model="text-embedding-3-small",
                embedding_dimensions=1536,
                local_embedding_model="darklethelong/vnlegal-lal",
            ),
        )
        get_embeddings.cache_clear()

        with pytest.raises(RuntimeError, match="OPENAI_API_KEY is required for embedding profile"):
            get_embeddings()

    def test_auto_provider_selects_local_only_for_a_local_index_profile(self, monkeypatch):
        from vietnam_legal_agent.infra import llm_instances

        monkeypatch.setattr(
            llm_instances,
            "get_settings",
            lambda: SimpleNamespace(
                embedding_provider="auto",
                embedding_profile="vnlegal-lal-v1",
                openai_api_key="configured-but-not-used",
                embedding_model="text-embedding-3-small",
                embedding_dimensions=1024,
                local_embedding_model="darklethelong/vnlegal-lal",
            ),
        )
        get_embeddings.cache_clear()

        assert isinstance(get_embeddings(), LocalSentenceTransformerEmbeddings)

    def test_all_llm_instances_have_timeout(self):
        """All 4 LLM instances should have request_timeout=30."""
        # Clear all caches
        get_llm_fast.cache_clear()
        get_llm_router.cache_clear()
        get_llm_smart.cache_clear()
        get_llm_stream.cache_clear()

        instances = [
            get_llm_fast(),
            get_llm_router(),
            get_llm_smart(),
            get_llm_stream(),
        ]

        for llm in instances:
            assert hasattr(llm, 'request_timeout'), f"{llm.model_name} missing request_timeout"
            assert llm.request_timeout == 30, f"{llm.model_name} has wrong timeout: {llm.request_timeout}"

    def test_gemini_provider_configuration(self, monkeypatch):
        """When LLM_PROVIDER=gemini, instances should configure Gemini models."""
        from vietnam_legal_agent.infra import llm_instances

        monkeypatch.setattr(
            llm_instances,
            "get_settings",
            lambda: SimpleNamespace(
                llm_provider="gemini",
                gemini_api_key="test-gemini-key",
                gemini_api_keys="",
                gemini_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                gemini_model_fast="gemini-3.5-flash-lite",
                gemini_model_smart="gemini-3.8-flash",
                gemini_smart_models_cascade="gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite",
                gemini_fast_models_cascade="gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.5-flash,gemini-3.6-flash",
                gemini_min_request_interval_seconds=0.0,
                gemini_rate_limit_cooldown_seconds=60.0,
                openai_api_key="",
            ),
        )
        get_llm_fast.cache_clear()
        get_llm_router.cache_clear()
        get_llm_smart.cache_clear()
        get_llm_stream.cache_clear()

        fast = get_llm_fast()
        assert fast.model_name == "gemini-3.5-flash-lite"
        assert str(fast.openai_api_base).rstrip("/") == "https://generativelanguage.googleapis.com/v1beta/openai"

        smart = get_llm_smart()
        assert smart.model_name == "gemini-3.8-flash"
        assert getattr(smart, "cascade_models", []) == [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
        ]

        router = get_llm_router()
        assert router is smart or router.model_name == "gemini-3.8-flash"

        stream = get_llm_stream()
        assert stream.model_name == "gemini-3.5-flash-lite"
        assert stream.streaming is True

    def test_gemini_key_manager_lru_and_cooldown(self):
        """GeminiKeyManager should pick LRU key and track cooldown per (key, model)."""
        from vietnam_legal_agent.infra.llm_instances import GeminiKeyManager

        km = GeminiKeyManager(["key1", "key2"], min_interval_per_key=0.0, cooldown_sec=10.0)
        k_first = km.acquire_key()
        k_second = km.acquire_key()
        assert {k_first, k_second} == {"key1", "key2"}

        # Put key1 on cooldown for gemini-3.8-flash only
        km.mark_rate_limited("key1", model="gemini-3.8-flash", cooldown=60.0)
        # key1 should not be acquired for gemini-3.8-flash
        assert km.acquire_key(model="gemini-3.8-flash") == "key2"
        # but key1 is still available for gemini-3.7-flash!
        assert "key1" in km.get_available_keys(model="gemini-3.7-flash")

    def test_gemini_model_cascading(self, monkeypatch):
        """GeminiPooledChat should cascade to next model when primary model hits rate limit."""

        from vietnam_legal_agent.infra.llm_instances import GeminiKeyManager

        km = GeminiKeyManager(["k1", "k2"], min_interval_per_key=0.0, cooldown_sec=60.0)
        chat = GeminiPooledChat(
            model="gemini-3.8-flash",
            primary_model="gemini-3.8-flash",
            cascade_models=["gemini-3.8-flash", "gemini-3.7-flash"],
            api_key="k1",
            key_manager=km,
            max_key_retries=2,
        )

        calls = []

        def fake_generate(self_inner, messages, stop=None, run_manager=None, **kwargs):
            calls.append((self_inner.model_name, self_inner.root_client.api_key))
            if self_inner.model_name == "gemini-3.8-flash":
                raise RuntimeError("429 ResourceExhausted: Quota exceeded for gemini-3.8-flash")
            return "success_response"

        monkeypatch.setattr("langchain_openai.ChatOpenAI._generate", fake_generate)

        res = chat._generate([{"role": "user", "content": "hi"}])
        assert res == "success_response"
        # Should have tried 3.8-flash on k1 and k2, then cascaded to 3.7-flash
        assert any(model == "gemini-3.7-flash" for model, _ in calls)
        assert chat.model_name == "gemini-3.8-flash"  # Reset back to primary

