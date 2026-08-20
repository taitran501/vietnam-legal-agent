"""
Tests for LLM instance configuration.

Tests cover:
- All 4 LLM instances have 30s timeout configured
- Correct models are used for each instance
- Temperature settings are correct
- Streaming configuration
"""


from backend.core.llm_instances import (
    get_embeddings,
    get_llm_fast,
    get_llm_router,
    get_llm_smart,
    get_llm_stream,
)


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
