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
from functools import lru_cache
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from epr_agent.config import get_settings


def _require_api_key(settings: Any) -> str:
    """Return the OpenAI API key or raise a clear error if not configured."""
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Configure it in your .env or environment."
        )
    return settings.openai_api_key


@lru_cache(maxsize=1)
def get_llm_fast() -> ChatOpenAI:
    """gpt-3.5-turbo — chitchat responses, FAQ answer generation (plain text output only)."""
    settings = get_settings()
    api_key = _require_api_key(settings)
    return ChatOpenAI(model="gpt-3.5-turbo", temperature=0, request_timeout=30, api_key=api_key)  # type: ignore[arg-type, call-arg]


@lru_cache(maxsize=1)
def get_llm_router() -> ChatOpenAI:
    """gpt-4o-mini — query routing with Structured Outputs (.with_structured_output())."""
    settings = get_settings()
    api_key = _require_api_key(settings)
    return ChatOpenAI(model="gpt-4o-mini", temperature=0, request_timeout=30, api_key=api_key)  # type: ignore[arg-type, call-arg]


@lru_cache(maxsize=1)
def get_llm_smart() -> ChatOpenAI:
    """gpt-4o-mini — query rewriting, legal generation, LLM-as-judge evaluation."""
    settings = get_settings()
    api_key = _require_api_key(settings)
    return ChatOpenAI(model="gpt-4o-mini", temperature=0, request_timeout=30, api_key=api_key)  # type: ignore[arg-type, call-arg]


@lru_cache(maxsize=1)
def get_llm_stream() -> ChatOpenAI:
    """gpt-3.5-turbo with streaming enabled — token-by-token answer delivery."""
    settings = get_settings()
    api_key = _require_api_key(settings)
    return ChatOpenAI(  # type: ignore[call-arg]
        model="gpt-3.5-turbo",
        temperature=0,
        streaming=True,
        request_timeout=30,
        api_key=api_key,  # type: ignore[arg-type]
    )


class LocalSentenceTransformerEmbeddings(Embeddings):
    """Local sentence embedding wrapper compatible with LangChain Embeddings interface."""

    def __init__(self, model_name: str = "darklethelong/vnlegal-lal", device: str | None = None) -> None:
        self.model_name = model_name
        self.device = device
        self._model: Any = None

    def _get_model(self):
        if self._model is None:
            try:
                torch: Any = importlib.import_module("torch")
                from sentence_transformers import SentenceTransformer
                dev = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
                self._model = SentenceTransformer(self.model_name, device=dev)
                if hasattr(self._model, "to"):
                    self._model.to(dtype=torch.float32)
                self._model.eval()
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to load local embedding model '{self.model_name}': {exc}. "
                    "Make sure 'sentence-transformers' and 'torch' are installed."
                ) from exc
        return self._model

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

    # Explicit local provider or auto without OpenAI key -> use local model
    if (
        settings.embedding_provider in {"local", "sentence_transformers"}
        or settings.embedding_profile in {"vnlegal-lal-v1", "vietnamese-legal-embedding-v1", "bge-m3-v1"}
        or (settings.embedding_provider == "auto" and not settings.openai_api_key)
    ):
        model_name = settings.local_embedding_model or "darklethelong/vnlegal-lal"
        return LocalSentenceTransformerEmbeddings(model_name=model_name)

    # Explicit openai provider requires a key
    if settings.embedding_provider == "openai" and not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required for OpenAI embeddings. "
            "Set embedding_provider='local' or configure OPENAI_API_KEY."
        )

    return OpenAIEmbeddings(model=settings.embedding_model, dimensions=settings.embedding_dimensions)
