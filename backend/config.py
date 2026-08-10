"""
Application configuration using Pydantic BaseSettings.
All values are read from environment variables / .env file.
Missing required values raise a clear error at startup.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # epr_chatbot/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── OpenAI ──────────────────────────────────────────────────────────────
    openai_api_key: str = Field(..., description="OpenAI API key")

    # ── Qdrant ──────────────────────────────────────────────────────────────
    use_qdrant_cloud: bool = Field(default=False)
    qdrant_cloud_url: str | None = Field(default=None)
    qdrant_api_key: str | None = Field(default=None)
    qdrant_url: str | None = Field(
        default=None,
        description="Optional self-hosted Qdrant endpoint, e.g. http://qdrant:6333",
    )
    # Local path used when not using cloud
    qdrant_local_path: str = Field(default="./qdrant_db")

    # Collection names
    law_collection: str = Field(default="law_collection")
    cache_collection: str = Field(default="cache_collection")

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")
    cache_ttl_seconds: int = Field(default=3600)       # exact-match cache TTL
    semantic_cache_threshold: float = Field(default=0.95)  # cosine similarity
    corpus_version: str = Field(
        default="epr-law-structure-v2",
        description="Version included in bounded answer-cache keys after corpus changes",
    )
    corpus_id: str = Field(default="epr")
    index_schema_version: str = Field(default="legal-structure-v1")
    auto_index_law: bool = Field(default=False)
    enable_trace_debug_api: bool = Field(default=False)
    database_url: str | None = Field(
        default=None,
        description="PostgreSQL production source of truth; SQLite is used locally when unset",
    )

    # ── Persistent Chat History ─────────────────────────────────────────────
    history_enabled: bool = Field(
        default=True,
        description="Deprecated compatibility flag; conversations always use durable persistence",
    )
    history_db_path: Path = Field(
        default=BASE_DIR / "data" / "chat_history.sqlite3",
        description="SQLite path for durable conversation and message history",
    )
    history_context_messages: int = Field(
        default=6,
        description="How many recent messages to load for model context",
    )
    history_dual_write_session: bool = Field(
        default=False,
        description="Deprecated compatibility flag. Durable conversations are never dual-written.",
    )

    # ── LangSmith (optional) ─────────────────────────────────────────────────
    langchain_tracing_v2: bool = Field(default=False)
    langchain_endpoint: str = Field(default="https://api.smith.langchain.com")
    langchain_api_key: str | None = Field(default=None)

    # ── Tavily (optional web search) ─────────────────────────────────────────
    tavily_api_key: str | None = Field(default=None)

    # ── Authentication ───────────────────────────────────────────────────────
    api_keys: str = Field(
        default="",
        description="Comma-separated list of valid API keys (e.g. 'key1,key2')",
    )
    require_auth: bool = Field(
        default=True,
        description="Whether to require API key authentication",
    )

    # ── Data paths ───────────────────────────────────────────────────────────
    faq_data_path: Path = Field(default=BASE_DIR / "data" / "faq.json")
    law_data_path: Path = Field(default=BASE_DIR / "data" / "law.json")
    # Full title for every chunk in law_collection (shown to the LLM for exact citations)
    law_citation_label: str = Field(
        default=(
            "Nghị định số 08/2022/NĐ-CP quy định chi tiết thi hành "
            "một số điều của Luật Bảo vệ môi trường"
        ),
        description="Official citation string appended in RAG context for bibliography",
    )

    # ── Pipeline tuning ──────────────────────────────────────────────────────
    max_retrieval_docs: int = Field(default=3, description="Evidence chunks passed to generation")
    max_chat_history_exchanges: int = Field(default=3)

    # ── Pipeline feature flags (Option A: small, reversible improvements) ──
    enable_query_rewrite: bool = Field(
        default=True,
        description="Enable contextual query rewriting for follow-up questions",
    )
    enable_llm_router_fallback: bool = Field(
        default=False,
        description="Allow router to call LLM when deterministic fast-route is inconclusive",
    )
    enable_relevance_gate: bool = Field(
        default=True,
        description="Run relevance gate before legal generation",
    )
    enable_web_fallback: bool = Field(
        default=True,
        description="Allow EPR-scoped web fallback when legal retrieval misses",
    )
    web_fallback_timeout_seconds: float = Field(
        default=6.0,
        description="Hard timeout for web fallback call in seconds",
    )
    enable_followup_suggestions: bool = Field(
        default=False,
        description="Generate LLM follow-up suggestions after each answer (adds latency)",
    )
    enable_legal_evidence_guardrail: bool = Field(
        default=True,
        description="Block legal generation when retrieved evidence quality is too low",
    )
    min_legal_evidence_docs: int = Field(
        default=1,
        description="Minimum number of retrieved legal docs required to generate an answer",
    )
    min_legal_evidence_chars: int = Field(
        default=160,
        description="Minimum combined characters from top legal docs required by evidence guardrail",
    )
    legal_context_max_docs: int = Field(
        default=3,
        description="Maximum legal documents packed into generation context",
    )
    legal_context_max_tokens_per_doc: int = Field(
        default=500,
        description="Approximate max tokens per legal document in generation context",
    )

    # ── Re-ranking ───────────────────────────────────────────────────────────
    enable_reranking: bool = Field(
        default=False,  # DISABLED: LLM re-ranker is incorrectly scoring docs
        description="Enable LLM-based re-ranking for retrieval results",
    )
    rerank_top_k: int = Field(
        default=3,
        description="Number of documents to return after re-ranking",
    )
    enable_cross_encoder_rerank: bool = Field(
        default=True,
        description="Enable cross-encoder reranker execution (shadow/apply modes)",
    )
    rerank_top_n: int = Field(
        default=20,
        description="Number of retrieval candidates sent into reranker",
    )
    rerank_timeout_ms: int = Field(
        default=1200,
        description="Hard timeout for cross-encoder reranking in milliseconds",
    )
    rerank_fallback_on_timeout: bool = Field(
        default=True,
        description="Fallback to heuristic rerank when cross-encoder times out/errors",
    )
    cross_encoder_shadow_mode: bool = Field(
        default=False,
        description="Run cross-encoder in shadow mode without impacting user ranking",
    )
    cross_encoder_rollout_percent: int = Field(
        default=0,
        description="Percent of requests where cross-encoder ranking is applied to users",
    )
    cross_encoder_model_name: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Cross-encoder model for reranking",
    )

    # ── Qdrant HNSW Index Configuration ─────────────────────────────────────
    # Optimized for 1M+ vectors: higher M = better recall, higher ef_construct = better index quality
    hnsw_m: int = Field(default=64, description="HNSW M parameter (connections per layer)")
    hnsw_ef_construct: int = Field(default=256, description="HNSW ef_construct (graph quality during indexing)")
    search_ef: int = Field(default=128, description="HNSW ef search parameter (runtime accuracy vs speed tradeoff)")

    @model_validator(mode="after")
    def _validate_qdrant_cloud(self) -> Settings:
        if self.use_qdrant_cloud and (not self.qdrant_cloud_url or not self.qdrant_api_key):
            raise ValueError(
                "USE_QDRANT_CLOUD=true requires both QDRANT_CLOUD_URL and QDRANT_API_KEY"
            )
        return self

    @model_validator(mode="after")
    def _set_langchain_env(self) -> Settings:
        """Push LangSmith vars into os.environ so LangChain SDK picks them up."""
        import os

        os.environ["OPENAI_API_KEY"] = self.openai_api_key
        os.environ["LANGCHAIN_TRACING_V2"] = str(self.langchain_tracing_v2).lower()
        os.environ["LANGCHAIN_ENDPOINT"] = self.langchain_endpoint
        if self.langchain_api_key:
            os.environ["LANGCHAIN_API_KEY"] = self.langchain_api_key
        if self.tavily_api_key:
            os.environ["TAVILY_API_KEY"] = self.tavily_api_key
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings singleton."""
    return Settings()
