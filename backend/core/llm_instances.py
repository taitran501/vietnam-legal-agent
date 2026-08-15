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

from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings


@lru_cache(maxsize=1)
def get_llm_fast() -> ChatOpenAI:
    """gpt-3.5-turbo — chitchat responses, FAQ answer generation (plain text output only).
    Do NOT use with .with_structured_output() — use get_llm_router() for that."""
    return ChatOpenAI(model="gpt-3.5-turbo", temperature=0, request_timeout=30)  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_llm_router() -> ChatOpenAI:
    """gpt-4o-mini — query routing with Structured Outputs (.with_structured_output()).
    gpt-3.5-turbo only supports JSON mode (no strict schema), so routing must use this."""
    return ChatOpenAI(model="gpt-4o-mini", temperature=0, request_timeout=30)  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_llm_smart() -> ChatOpenAI:
    """gpt-4o-mini — query rewriting, legal generation, LLM-as-judge evaluation."""
    return ChatOpenAI(model="gpt-4o-mini", temperature=0, request_timeout=30)  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_llm_stream() -> ChatOpenAI:
    """gpt-3.5-turbo with streaming enabled — token-by-token answer delivery."""
    return ChatOpenAI(  # type: ignore[call-arg]
        model="gpt-3.5-turbo",
        temperature=0,
        streaming=True,
        request_timeout=30,
    )


@lru_cache(maxsize=1)
def get_embeddings() -> OpenAIEmbeddings:
    """Configured embedding profile used by every legal vector collection."""

    from backend.config import get_settings

    settings = get_settings()
    if settings.embedding_model != "text-embedding-3-small" or settings.embedding_dimensions != 1536:
        raise ValueError("unsupported_embedding_profile: expected text-embedding-3-small/1536")
    return OpenAIEmbeddings(model=settings.embedding_model, dimensions=settings.embedding_dimensions)
