"""
Application configuration using Pydantic BaseSettings.
All values are read from environment variables / .env file.
Missing required values raise a clear error at startup.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_base_dir() -> Path:
    """Locate the repository root that owns the ``data`` tree.

    The package may be imported from the source tree (local dev, pytest) or
    from site-packages (container build, where ``backend`` is copied into
    ``/app``).  Only the checked-out tree contains ``data/``, so prefer an
    explicit override, then scan upward from the working directory (the
    container runs with ``WORKDIR /app``), and finally fall back to the
    source-tree heuristic.
    """

    override = os.environ.get("EPR_AGENT_BASE_DIR")
    if override:
        return Path(override).resolve()
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "data").is_dir() and (candidate / "pyproject.toml").is_file():
            return candidate
    return Path(__file__).resolve().parent.parent.parent  # vietnam-legal-agent/


BASE_DIR = _resolve_base_dir()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── OpenAI ──────────────────────────────────────────────────────────────
    # Empty is a valid local/preview configuration.  Readiness remains the
    # authoritative gate and blocks legal capabilities when the key is absent.
    openai_api_key: str = Field(default="", description="OpenAI API key")

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
    law_collection: str = Field(default="vietnam_legal_collection_v1")

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_password: str = Field(
        default="",
        description="Redis AUTH password; included in REDIS_URL by Compose when set",
    )
    rate_limit_fail_open: bool = Field(
        default=False,
        description="Allow requests when Redis rate limiting is unavailable; keep false for production safety",
    )
    cache_ttl_seconds: int = Field(default=3600)       # exact-match cache TTL
    corpus_version: str = Field(
        default="epr-law-structure-v4-amendment-chain",
        description="Version included in bounded answer-cache keys after corpus changes",
    )
    corpus_id: str = Field(default="epr")
    index_schema_version: str = Field(default="legal-structure-v2")
    embedding_provider: str = Field(
        default="auto",
        description="Embedding provider: openai | local | auto",
    )
    local_embedding_model: str = Field(
        default="darklethelong/vnlegal-lal",
        description="HuggingFace / SentenceTransformers model ID for local legal embeddings",
    )
    embedding_profile: str = Field(default="openai-text-embedding-3-small-v1")
    embedding_model: str = Field(default="text-embedding-3-small")
    embedding_dimensions: int = Field(default=1536, ge=1)
    chunking_profile: str = Field(default="legal-structure-v2")
    auto_index_law: bool = Field(default=False)
    enable_trace_debug_api: bool = Field(default=False)
    enable_universal_retrieval: bool = Field(
        default=False,
        description="Allow the content-locked universal corpus as an explicit preview supplement; never implicit in production.",
    )
    agent_pipeline_version: str = Field(
        default="pipeline-v4",
        description="Server-selected workflow runtime: pipeline-v3 | pipeline-v4 | pipeline-agent. Clients never choose a pipeline version.",
    )
    v4_route_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    appendix_xxii_data_path: Path = Field(default=BASE_DIR / "artifacts" / "appendix_xxii.jsonl")
    amendment_map_path: Path = Field(default=BASE_DIR / "data" / "amendment_map.json")
    rule_pack_path: Path = Field(default=BASE_DIR / "data" / "epr_rule_pack.json")
    corpus_as_of_date: str | None = Field(
        default=None,
        description="Legally approved as-of date; build time is never substituted automatically",
    )
    corpus_runtime_mode: Literal["production", "preview"] = Field(
        default="production",
        description="Production requires legal approval; preview permits technically valid unapproved corpora with warnings.",
    )
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
    web_official_domains: str = Field(
        default="vanban.chinhphu.vn,vbpl.vn",
        description="Comma-separated official domains permitted as web evidence",
    )
    web_excerpt_max_chars: int = Field(default=1200, ge=200, le=4000)

    # ── Authentication ───────────────────────────────────────────────────────
    allowed_origins: str = Field(
        default="",
        description="Comma-separated browser origins allowed by CORS; leave empty for same-origin deployments",
    )
    api_keys: str = Field(
        default="",
        description="Comma-separated list of valid API keys (e.g. 'key1,key2')",
    )
    service_token_definitions: str = Field(
        default="",
        description="name:sha256(token):scope1|scope2:role1|role2 entries separated by commas",
    )
    oidc_issuer: str | None = Field(default=None)
    oidc_audience: str | None = Field(default=None)
    oidc_client_id: str | None = Field(default=None)
    oidc_required_group: str | None = Field(default=None)
    oidc_allowed_algorithms: str = Field(default="RS256")
    oidc_jwks_cache_seconds: int = Field(default=3600, ge=60, le=86400)
    trusted_proxy_ips: str = Field(
        default="",
        description="Comma-separated proxy IPs allowed to supply X-Forwarded-For",
    )
    auth_migration_backup_path: Path = Field(default=BASE_DIR / "data" / "owner_migration_backup.json")
    require_auth: bool = Field(
        default=True,
        description="Whether to require API key authentication",
    )
    legacy_hmac_key: str = Field(
        default="epr-owner-v2",
        description="HMAC salt for legacy API key derivation; override in production",
    )

    # ── Data paths ───────────────────────────────────────────────────────────
    faq_data_path: Path = Field(default=BASE_DIR / "data" / "faq.json")
    law_data_path: Path = Field(default=BASE_DIR / "data" / "law.json")
    corpus_manifest_path: Path = Field(default=BASE_DIR / "data" / "corpus_manifest.json")
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
    enable_relevance_gate: bool = Field(
        default=True,
        description="Run relevance gate before legal generation",
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
    min_legal_rerank_score: float = Field(
        default=0.40,
        ge=0.0,
        le=1.0,
        description="Minimum V3 heuristic rerank score for unanchored legal evidence",
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
        default=True,
        description="Run cross-encoder in shadow mode without impacting user ranking",
    )
    cross_encoder_rollout_percent: int = Field(
        default=0,
        description="Percent of requests where cross-encoder ranking is applied to users",
    )
    cross_encoder_model_name: str = Field(
        default="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
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
        # Validate supported embedding profiles
        _valid_profiles = {
            "openai-text-embedding-3-small-v1": (1536, "text-embedding-3-small"),
            "vnlegal-lal-v1": (1024, "darklethelong/vnlegal-lal"),
            "vietnamese-legal-embedding-v1": (768, "bqbbao6/vietnamese-legal-embedding"),
            "bge-m3-v1": (1024, "BAAI/bge-m3"),
        }
        if self.embedding_profile in _valid_profiles:
            expected_dim, _ = _valid_profiles[self.embedding_profile]
            if self.embedding_dimensions != expected_dim:
                self.embedding_dimensions = expected_dim
        elif self.embedding_provider in {"local", "sentence_transformers"}:
            pass  # Custom local model
        elif (
            self.embedding_profile != "openai-text-embedding-3-small-v1"
            and self.embedding_dimensions != 1536
            and self.embedding_provider == "openai"
        ):
            raise ValueError(
                f"Unsupported embedding profile: {self.embedding_profile}. "
                f"Supported: {list(_valid_profiles.keys())}"
            )
        if self.agent_pipeline_version not in {"pipeline-v3", "pipeline-v4", "pipeline-agent"}:
            raise ValueError("AGENT_PIPELINE_VERSION must be pipeline-v3, pipeline-v4, or pipeline-agent")
        if self.agent_pipeline_version == "pipeline-v4" and self.index_schema_version == "legal-structure-v2":
            self.index_schema_version = "legal-structure-v2-v4-appendix1"
        if self.oidc_issuer and not self.oidc_audience:
            raise ValueError("OIDC_AUDIENCE is required when OIDC_ISSUER is configured")
        if self.oidc_required_group and not self.oidc_issuer:
            raise ValueError("OIDC_REQUIRED_GROUP requires OIDC_ISSUER")
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


def _looks_like_configured_secret(value: str | None) -> bool:
    """Return whether a value is non-empty and not a documentation placeholder."""

    normalized = str(value or "").strip().lower()
    if not normalized:
        return False
    return not normalized.startswith(("your-", "replace-", "change-me", "example-"))


def validate_production_settings(settings: Settings) -> None:
    """Fail fast when a production process would start with unsafe defaults.

    Preview mode deliberately remains permissive so local deterministic journeys
    can run without paid providers.  Production mode must instead fail before
    opening dependency connections when its security or persistence contract is
    incomplete.
    """

    if settings.corpus_runtime_mode != "production":
        return

    errors: list[str] = []
    if not settings.require_auth:
        errors.append("REQUIRE_AUTH must be true")
    if settings.rate_limit_fail_open:
        errors.append("RATE_LIMIT_FAIL_OPEN must be false")
    if settings.enable_trace_debug_api:
        errors.append("ENABLE_TRACE_DEBUG_API must be false")
    if settings.enable_universal_retrieval:
        errors.append("ENABLE_UNIVERSAL_RETRIEVAL must be false until the universal corpus is legally approved")
    database_url = str(settings.database_url or "")
    if not database_url.startswith(("postgresql://", "postgres://", "postgresql+asyncpg://")):
        errors.append("DATABASE_URL must point to PostgreSQL")
    if not _looks_like_configured_secret(settings.openai_api_key):
        errors.append("OPENAI_API_KEY must be configured")
    if not settings.use_qdrant_cloud and not settings.qdrant_url:
        errors.append("QDRANT_URL must be configured when Qdrant Cloud is disabled")

    has_legacy_key = any(
        _looks_like_configured_secret(value)
        for value in settings.api_keys.split(",")
    )
    has_service_tokens = bool(settings.service_token_definitions.strip())
    has_oidc = bool(settings.oidc_issuer and settings.oidc_audience)
    if not (has_legacy_key or has_service_tokens or has_oidc):
        errors.append("configure API_KEYS, SERVICE_TOKEN_DEFINITIONS, or OIDC_ISSUER/OIDC_AUDIENCE")

    for raw_origin in settings.allowed_origins.split(","):
        origin = raw_origin.strip()
        if not origin:
            continue
        parsed = urlsplit(origin)
        if origin == "*":
            errors.append("ALLOWED_ORIGINS must not contain '*'")
            continue
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append("ALLOWED_ORIGINS must contain only valid HTTPS origins")
            continue
        if parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
            errors.append("ALLOWED_ORIGINS must not contain local development hosts")

    if errors:
        raise ValueError("Unsafe production configuration: " + "; ".join(errors))
