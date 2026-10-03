from __future__ import annotations

from types import SimpleNamespace

import pytest
from backend import main

from vietnam_legal_agent.infra import llm_instances


@pytest.mark.asyncio
async def test_local_embedding_warmup_uses_background_embedding_instance(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_provider="local",
            embedding_profile="",
            openai_api_key="",
        ),
    )
    monkeypatch.setattr(
        llm_instances,
        "get_embeddings",
        lambda: SimpleNamespace(embed_query=lambda query: calls.append(query)),
    )

    async def run_in_background(function, *args, **kwargs):
        calls.append("background")
        return function(*args, **kwargs)

    monkeypatch.setattr(main.asyncio, "to_thread", run_in_background)

    await main._warmup_local_embeddings_task()

    assert calls == ["background", "Khởi tạo truy xuất pháp luật."]


@pytest.mark.asyncio
async def test_openai_embedding_provider_is_not_called_during_startup(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_provider="openai",
            embedding_profile="openai-text-embedding-3-small-v1",
            openai_api_key="configured",
        ),
    )

    def unexpected_embedding_call():
        raise AssertionError("startup must not make a paid OpenAI embedding request")

    monkeypatch.setattr(llm_instances, "get_embeddings", unexpected_embedding_call)

    await main._warmup_local_embeddings_task()


@pytest.mark.asyncio
async def test_universal_cross_encoder_warmup_runs_off_the_event_loop(monkeypatch):
    calls: list[str] = []

    def warmup():
        calls.append("model")

    async def run_in_background(function, *args, **kwargs):
        calls.append("background")
        return function(*args, **kwargs)

    import vietnam_legal_agent.tools.retrieval

    monkeypatch.setattr(
        vietnam_legal_agent.tools.retrieval,
        "warmup_universal_cross_encoder",
        warmup,
    )
    monkeypatch.setattr(main.asyncio, "to_thread", run_in_background)

    await main._warmup_universal_cross_encoder_task()

    assert calls == ["background", "model"]
