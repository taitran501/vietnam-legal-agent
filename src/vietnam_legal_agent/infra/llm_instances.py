"""
Shared LLM singletons.

All other modules import from here so we never create redundant instances.
Models:
  - llm_fast        : gpt-3.5-turbo  temperature=0  (chitchat, FAQ gen — plain text output only)
  - llm_router      : gpt-4o-mini    temperature=0  (routing with Structured Outputs)
                      NOTE: gpt-3.5-turbo does NOT support Structured Outputs (schema-strict).
                      It only supports JSON mode (no schema enforcement). Router MUST use
                      gpt-4o-mini or later — see openai.md "Supported models" section.
  - llm_smart       : gpt-4o-mini    temperature=0  (rewriting, legal generation, LLM-judge)
  - llm_stream      : gpt-3.5-turbo  temperature=0  streaming=True (answer delivery)
  - embeddings      : text-embedding-3-small
"""

import importlib
import logging
import threading
from functools import lru_cache
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from vietnam_legal_agent.config import get_settings

logger = logging.getLogger(__name__)


import asyncio
import time
from collections.abc import AsyncIterator, Iterator

import openai

_gemini_key_manager: Any = None
_gemini_manager_lock = threading.Lock()
_global_gemini_sync_lock = threading.Lock()


class GeminiKeyManager:
    """Thread-safe key pool manager with rate-pacing (RPM protection), LRU scheduling, and per-model cooldown."""

    def __init__(
        self,
        keys: list[str],
        *,
        min_interval_per_key: float = 1.5,
        cooldown_sec: float = 60.0,
    ) -> None:
        self.keys = [k.strip() for k in keys if k.strip()]
        self.min_interval_per_key = max(0.0, min_interval_per_key)
        self.cooldown_sec = max(5.0, cooldown_sec)
        self.last_used: dict[str, float] = {k: 0.0 for k in self.keys}
        self.cooldown_until: dict[tuple[str, str], float] = {}
        self.key_cooldown_until: dict[str, float] = {k: 0.0 for k in self.keys}
        self.call_stats: dict[str, int] = {k: 0 for k in self.keys}
        self.model_call_stats: dict[str, int] = {}
        self.rate_limited_stats: dict[str, int] = {k: 0 for k in self.keys}
        self.lock = threading.Lock()

    def get_stats(self) -> dict[str, Any]:
        """Return snapshot of key usage and rate-limiting statistics."""
        with self.lock:
            return {
                "call_stats": dict(self.call_stats),
                "model_call_stats": dict(self.model_call_stats),
                "rate_limited_stats": dict(self.rate_limited_stats),
                "active_cooldowns": {
                    f"...{k[-6:]}:{m}": max(0.0, exp - time.time())
                    for (k, m), exp in self.cooldown_until.items()
                    if exp > time.time()
                },
            }

    def get_available_keys(self, model: str | None = None) -> list[str]:
        """Return list of keys not currently in cooldown for the given model."""
        with self.lock:
            now = time.time()
            return [
                k for k in self.keys
                if now >= self.key_cooldown_until.get(k, 0.0)
                and (not model or now >= self.cooldown_until.get((k, model), 0.0))
            ]

    def acquire_key(self, model: str | None = None) -> str:
        """Acquire the best available key for the specified model using Least-Recently-Used with rate-pacing."""
        with self.lock:
            now = time.time()
            active_keys = [
                k for k in self.keys
                if now >= self.key_cooldown_until.get(k, 0.0)
                and (not model or now >= self.cooldown_until.get((k, model), 0.0))
            ]
            if not active_keys:
                if model:
                    earliest_key = min(
                        self.keys,
                        key=lambda k: max(
                            self.key_cooldown_until.get(k, 0.0),
                            self.cooldown_until.get((k, model), 0.0),
                        ),
                    )
                else:
                    earliest_key = min(self.keys, key=lambda k: self.key_cooldown_until.get(k, 0.0))
                exp_time = max(
                    self.key_cooldown_until.get(earliest_key, 0.0),
                    self.cooldown_until.get((earliest_key, model), 0.0) if model else 0.0,
                )
                wait_time = exp_time - now
                if 0 < wait_time <= 10.0:
                    time.sleep(wait_time)
                active_keys = [earliest_key]

            # Pick Least-Recently-Used (LRU) key to maximize time gap per key (avoids 5 RPM limit)
            chosen = min(active_keys, key=lambda k: self.last_used.get(k, 0.0))

            # Pacing: ensure minimum interval between calls on the same key
            elapsed = time.time() - self.last_used.get(chosen, 0.0)
            if elapsed < self.min_interval_per_key:
                time.sleep(self.min_interval_per_key - elapsed)

            self.last_used[chosen] = time.time()
            self.call_stats[chosen] = self.call_stats.get(chosen, 0) + 1
            if model:
                self.model_call_stats[model] = self.model_call_stats.get(model, 0) + 1
            return chosen

    def mark_rate_limited(self, key: str, model: str | None = None, cooldown: float | None = None) -> None:
        """Mark a (key, model) or entire key as temporarily cooling down after 429 or 503."""
        with self.lock:
            penalty = cooldown if cooldown is not None else self.cooldown_sec
            exp = time.time() + penalty
            self.rate_limited_stats[key] = self.rate_limited_stats.get(key, 0) + 1
            if model:
                self.cooldown_until[(key, model)] = exp
                logger.warning(
                    "Gemini API key ...%s rate-limited on model '%s'; cooled down for %.1fs",
                    key[-6:] if len(key) >= 6 else key,
                    model,
                    penalty,
                )
            else:
                self.key_cooldown_until[key] = exp
                logger.warning(
                    "Gemini API key ...%s rate-limited; cooled down for %.1fs",
                    key[-6:] if len(key) >= 6 else key,
                    penalty,
                )


def clear_gemini_key_manager() -> None:
    """Clear cached key manager for unit tests."""
    global _gemini_key_manager
    with _gemini_manager_lock:
        _gemini_key_manager = None


def _get_key_manager(settings: Any) -> GeminiKeyManager:
    global _gemini_key_manager
    if _gemini_key_manager is not None:
        return _gemini_key_manager
    with _gemini_manager_lock:
        if _gemini_key_manager is not None:
            return _gemini_key_manager
        raw_keys = (getattr(settings, "gemini_api_keys", None) or "").strip()
        if raw_keys:
            keys_list = [k.strip() for k in raw_keys.split(",") if k.strip()]
        else:
            single = (getattr(settings, "gemini_api_key", None) or "").strip()
            keys_list = [single] if single else []

        if not keys_list:
            raise RuntimeError("GEMINI_API_KEY is not set. Configure it in your .env or environment.")

        interval = float(getattr(settings, "gemini_min_request_interval_seconds", 1.5))
        cooldown = float(getattr(settings, "gemini_rate_limit_cooldown_seconds", 60.0))
        _gemini_key_manager = GeminiKeyManager(
            keys_list,
            min_interval_per_key=interval,
            cooldown_sec=cooldown,
        )
        return _gemini_key_manager


def _is_retryable_gemini_error(exc: Exception) -> bool:
    """Identify rate limit (429), quota exhaustion, or server overload (503/500)."""
    if isinstance(exc, (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError)):
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in (
        "rate limit", "429", "quota", "resource_exhausted", "503", "500", "502", "504",
        "high demand", "overloaded", "temporarily unavailable"
    ))


def _is_daily_quota_exhausted(exc: Exception) -> bool:
    """Identify daily quota exhaustion (ResourceExhausted or quota metric per day)."""
    msg = str(exc).lower()
    return any(marker in msg for marker in ("quota", "resource_exhausted", "per day", "daily", "free_tier"))


def _calc_cooldown_for_error(exc: Exception, default_cooldown: float = 60.0) -> float:
    """Assign longer cooldown (30 min) for daily quota exhaustion vs transient RPM/503 (60s)."""
    if _is_daily_quota_exhausted(exc):
        return 1800.0
    return default_cooldown


class GeminiPooledChat(ChatOpenAI):
    """ChatOpenAI variant with rate pacing, LRU key pooling, model cascading, and automatic retry on 429/503."""

    key_manager: Any = None
    max_key_retries: int = 2
    fallback_model: str | None = None
    cascade_models: list[str] = []
    primary_model: str = ""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.key_manager:
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        last_exc: Exception | None = None
        models_to_try = self.cascade_models or ([self.model_name, self.fallback_model] if self.fallback_model else [self.model_name])
        for model in models_to_try:
            available = self.key_manager.get_available_keys(model)
            if not available:
                continue
            retries = min(self.max_key_retries, len(available))
            for _ in range(retries):
                key = self.key_manager.acquire_key(model=model)
                try:
                    with _global_gemini_sync_lock:
                        self.model_name = model
                        self.root_client.api_key = key
                        res = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
                        if model != self.primary_model:
                            logger.info(
                                "Gemini invocation succeeded on cascaded model '%s' (primary was '%s')",
                                model,
                                self.primary_model,
                            )
                        return res
                except Exception as exc:
                    if _is_retryable_gemini_error(exc):
                        penalty = _calc_cooldown_for_error(exc, self.key_manager.cooldown_sec)
                        self.key_manager.mark_rate_limited(key, model=model, cooldown=penalty)
                        last_exc = exc
                        continue
                    raise
                finally:
                    self.model_name = self.primary_model
        if last_exc:
            raise last_exc
        # Edge case: all keys cooling down; acquire with wait on first model
        fallback_m = models_to_try[0]
        key = self.key_manager.acquire_key(model=fallback_m)
        with _global_gemini_sync_lock:
            self.model_name = fallback_m
            self.root_client.api_key = key
            res = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            self.model_name = self.primary_model
            return res

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.key_manager:
            return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        last_exc: Exception | None = None
        models_to_try = self.cascade_models or ([self.model_name, self.fallback_model] if self.fallback_model else [self.model_name])
        for model in models_to_try:
            available = self.key_manager.get_available_keys(model)
            if not available:
                continue
            retries = min(self.max_key_retries, len(available))
            for _ in range(retries):
                key = self.key_manager.acquire_key(model=model)
                try:
                    self.model_name = model
                    self.root_async_client.api_key = key
                    res = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
                    if model != self.primary_model:
                        logger.info(
                            "Gemini async invocation succeeded on cascaded model '%s' (primary was '%s')",
                            model,
                            self.primary_model,
                        )
                    return res
                except Exception as exc:
                    if _is_retryable_gemini_error(exc):
                        penalty = _calc_cooldown_for_error(exc, self.key_manager.cooldown_sec)
                        self.key_manager.mark_rate_limited(key, model=model, cooldown=penalty)
                        last_exc = exc
                        continue
                    raise
                finally:
                    self.model_name = self.primary_model
        if last_exc:
            raise last_exc
        fallback_m = models_to_try[0]
        key = self.key_manager.acquire_key(model=fallback_m)
        self.model_name = fallback_m
        self.root_async_client.api_key = key
        res = await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)
        self.model_name = self.primary_model
        return res

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.key_manager:
            yield from super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs)
            return
        last_exc: Exception | None = None
        models_to_try = self.cascade_models or ([self.model_name, self.fallback_model] if self.fallback_model else [self.model_name])
        for model in models_to_try:
            available = self.key_manager.get_available_keys(model)
            if not available:
                continue
            retries = min(self.max_key_retries, len(available))
            for _ in range(retries):
                key = self.key_manager.acquire_key(model=model)
                try:
                    with _global_gemini_sync_lock:
                        self.model_name = model
                        self.root_client.api_key = key
                        yield from super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs)
                    return
                except Exception as exc:
                    if _is_retryable_gemini_error(exc):
                        penalty = _calc_cooldown_for_error(exc, self.key_manager.cooldown_sec)
                        self.key_manager.mark_rate_limited(key, model=model, cooldown=penalty)
                        last_exc = exc
                        continue
                    raise
                finally:
                    self.model_name = self.primary_model
        if last_exc:
            raise last_exc
        fallback_m = models_to_try[0]
        key = self.key_manager.acquire_key(model=fallback_m)
        with _global_gemini_sync_lock:
            self.model_name = fallback_m
            self.root_client.api_key = key
            yield from super()._stream(messages, stop=stop, run_manager=run_manager, **kwargs)
            self.model_name = self.primary_model

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.key_manager:
            async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                yield chunk
            return
        last_exc: Exception | None = None
        models_to_try = self.cascade_models or ([self.model_name, self.fallback_model] if self.fallback_model else [self.model_name])
        for model in models_to_try:
            available = self.key_manager.get_available_keys(model)
            if not available:
                continue
            retries = min(self.max_key_retries, len(available))
            for _ in range(retries):
                key = self.key_manager.acquire_key(model=model)
                try:
                    self.model_name = model
                    self.root_async_client.api_key = key
                    async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
                        yield chunk
                    return
                except Exception as exc:
                    if _is_retryable_gemini_error(exc):
                        penalty = _calc_cooldown_for_error(exc, self.key_manager.cooldown_sec)
                        self.key_manager.mark_rate_limited(key, model=model, cooldown=penalty)
                        last_exc = exc
                        continue
                    raise
                finally:
                    self.model_name = self.primary_model
        if last_exc:
            raise last_exc
        fallback_m = models_to_try[0]
        key = self.key_manager.acquire_key(model=fallback_m)
        self.model_name = fallback_m
        self.root_async_client.api_key = key
        async for chunk in super()._astream(messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk
        self.model_name = self.primary_model


def _resolve_provider(settings: Any) -> str:
    provider = getattr(settings, "llm_provider", "auto").strip().casefold()
    if provider in {"gemini", "google"}:
        return "gemini"
    if provider == "openai":
        return "openai"
    has_gemini = bool(getattr(settings, "gemini_api_key", None) or getattr(settings, "gemini_api_keys", None))
    if has_gemini and not getattr(settings, "openai_api_key", None):
        return "gemini"
    return "openai"


def _create_gemini_chat(
    model: str,
    *,
    cascade_models: list[str] | None = None,
    streaming: bool = False,
    temperature: float = 0.0,
    request_timeout: int = 30,
) -> ChatOpenAI:
    settings = get_settings()
    km = _get_key_manager(settings)
    cascade = list(cascade_models) if cascade_models else [model]
    if model not in cascade:
        cascade.insert(0, model)
    initial_key = km.acquire_key(model=cascade[0])
    base_url = getattr(settings, "gemini_base_url", "https://generativelanguage.googleapis.com/v1beta/openai/")
    max_retries = int(getattr(settings, "gemini_max_key_retries", 5))
    fallback = getattr(settings, "gemini_fallback_model", None)
    return GeminiPooledChat(  # type: ignore[call-arg]
        model=model,
        primary_model=model,
        cascade_models=cascade,
        temperature=temperature,
        streaming=streaming,
        request_timeout=request_timeout,
        api_key=initial_key,  # type: ignore[arg-type]
        base_url=base_url,
        key_manager=km,
        max_key_retries=max_retries,
        fallback_model=fallback,
    )


def _require_api_key(settings: Any) -> str:
    """Return the OpenAI API key or raise a clear error if not configured."""
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Configure it in your .env or environment."
        )
    return settings.openai_api_key


@lru_cache(maxsize=1)
def get_llm_fast() -> ChatOpenAI:
    """Fast model (gpt-3.5-turbo or Gemini Flash Lite with fast cascade)."""
    settings = get_settings()
    if _resolve_provider(settings) == "gemini":
        model = getattr(settings, "gemini_model_fast", "gemini-3.5-flash-lite")
        raw_cascade = getattr(settings, "gemini_fast_models_cascade", "")
        cascade = [m.strip() for m in raw_cascade.split(",") if m.strip()] or [model]
        return _create_gemini_chat(model=model, cascade_models=cascade, temperature=0, request_timeout=30)
    api_key = _require_api_key(settings)
    return ChatOpenAI(model="gpt-3.5-turbo", temperature=0, request_timeout=30, api_key=api_key)  # type: ignore[arg-type, call-arg]


@lru_cache(maxsize=1)
def get_llm_smart() -> ChatOpenAI:
    """Smartest reasoning & critic model (gpt-4o-mini or Gemini 3.8/3.7/3.6/3.5 cascade)."""
    settings = get_settings()
    if _resolve_provider(settings) == "gemini":
        model = getattr(settings, "gemini_model_smart", "gemini-3.8-flash")
        raw_cascade = getattr(settings, "gemini_smart_models_cascade", "")
        cascade = [m.strip() for m in raw_cascade.split(",") if m.strip()] or [model]
        return _create_gemini_chat(model=model, cascade_models=cascade, temperature=0, request_timeout=30)
    api_key = _require_api_key(settings)
    return ChatOpenAI(model="gpt-4o-mini", temperature=0, request_timeout=30, api_key=api_key)  # type: ignore[arg-type, call-arg]


@lru_cache(maxsize=1)
def get_llm_router() -> ChatOpenAI:
    """Unified routing model using the smart model cascade directly."""
    return get_llm_smart()


@lru_cache(maxsize=1)
def get_llm_stream() -> ChatOpenAI:
    """Streaming answer model with fast cascade."""
    settings = get_settings()
    if _resolve_provider(settings) == "gemini":
        model = getattr(settings, "gemini_model_fast", "gemini-3.5-flash-lite")
        raw_cascade = getattr(settings, "gemini_fast_models_cascade", "")
        cascade = [m.strip() for m in raw_cascade.split(",") if m.strip()] or [model]
        return _create_gemini_chat(model=model, cascade_models=cascade, streaming=True, temperature=0, request_timeout=30)
    api_key = _require_api_key(settings)
    return ChatOpenAI(  # type: ignore[call-arg]
        model="gpt-3.5-turbo",
        temperature=0,
        streaming=True,
        request_timeout=30,
        api_key=api_key,  # type: ignore[arg-type]
    )


_st_lock = threading.Lock()
_shared_st_models: dict[str, Any] = {}


class LocalSentenceTransformerEmbeddings(Embeddings):
    """Local sentence embedding wrapper compatible with LangChain Embeddings interface."""

    def __init__(self, model_name: str = "darklethelong/vnlegal-lal", device: str | None = None) -> None:
        self.model_name = model_name
        req_dev = (device or "auto").strip().casefold()
        if req_dev == "auto":
            try:
                torch: Any = importlib.import_module("torch")
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                self.device = "cpu"
        else:
            self.device = req_dev

        if self.device == "cpu":
            try:
                import os
                torch = importlib.import_module("torch")
                # Throttling CPU threads avoids pegging all 16 cores and freezing OS desktop
                max_threads = max(1, min(4, (os.cpu_count() or 4) // 2))
                torch.set_num_threads(max_threads)
            except Exception:
                pass

    def _get_model(self):
        with _st_lock:
            key = f"{self.model_name}:{self.device}"
            if key not in _shared_st_models:
                try:
                    torch: Any = importlib.import_module("torch")
                    from sentence_transformers import SentenceTransformer
                    try:
                        model = SentenceTransformer(self.model_name, device=self.device, local_files_only=True)
                    except Exception:
                        try:
                            model = SentenceTransformer(self.model_name, device=self.device)
                        except Exception as dev_err:
                            if self.device != "cpu":
                                logger.warning("Device '%s' failed (%s), falling back to 'cpu'", self.device, dev_err)
                                model = SentenceTransformer(self.model_name, device="cpu")
                            else:
                                raise
                    if hasattr(model, "to"):
                        model.to(dtype=torch.float32)
                    model.eval()
                    _shared_st_models[key] = model
                except Exception as exc:
                    raise RuntimeError(
                        f"Failed to load local embedding model '{self.model_name}': {exc}. "
                        "Make sure 'sentence-transformers' and 'torch' are installed."
                    ) from exc
            return _shared_st_models[key]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        embs = model.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True, precision="float32")
        return [e.tolist() for e in embs]

    def embed_query(self, text: str) -> list[float]:
        model = self._get_model()
        emb = model.encode(text, show_progress_bar=False, normalize_embeddings=True, precision="float32")
        return emb.tolist()


@lru_cache(maxsize=1)
def get_embeddings() -> Embeddings:
    """Configured embedding profile (OpenAI or Local VNLegal-LAL) used by legal vector collections."""
    settings = get_settings()
    local_profiles = {
        "vnlegal-lal-v1",
        "vietnamese-legal-embedding-v1",
        "bge-m3-v1",
    }
    local_providers = {"local", "sentence_transformers"}
    provider = settings.embedding_provider.strip().casefold()

    # The vector profile describes the model used to build the index. Never
    # switch to a different embedding space just because a key is missing.
    if provider in local_providers or settings.embedding_profile in local_profiles:
        if settings.embedding_profile == "openai-text-embedding-3-small-v1":
            raise RuntimeError(
                "Embedding provider/profile mismatch: the law collection uses "
                "openai-text-embedding-3-small-v1, but a local model was selected."
            )
        if provider == "openai":
            raise RuntimeError(
                f"Embedding provider/profile mismatch: {settings.embedding_profile} requires a local model."
            )
        model_name = settings.local_embedding_model or "darklethelong/vnlegal-lal"
        device = getattr(settings, "embedding_device", "auto")
        return LocalSentenceTransformerEmbeddings(model_name=model_name, device=device)

    if provider not in {"openai", "auto"}:
        raise RuntimeError(f"Unsupported EMBEDDING_PROVIDER: {settings.embedding_provider}")
    if settings.embedding_profile != "openai-text-embedding-3-small-v1":
        raise RuntimeError(f"Unsupported embedding profile: {settings.embedding_profile}")
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required for embedding profile "
            "openai-text-embedding-3-small-v1. Configure the key or index the corpus with a matching local profile."
        )

    return OpenAIEmbeddings(model=settings.embedding_model, dimensions=settings.embedding_dimensions)
