from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from backend.api.routes.health import chat_admission_readiness, readiness_payload


class _Store:
    async def schema_status(self):
        return {"status": "ready", "code": "ok", "issues": []}


class _Redis:
    async def ping(self):
        raise ConnectionError("offline")


def _settings(mode: str, tmp_path: Path):
    manifest = tmp_path / "universal-manifest.json"
    manifest.write_text('{"corpus_version":"test"}', encoding="utf-8")
    return SimpleNamespace(
        corpus_id="vietnamese_law",
        corpus_version="test",
        corpus_runtime_mode=mode,
        universal_corpus_manifest_path=manifest,
        index_schema_version="legal-structure-v2",
        embedding_profile="openai-text-embedding-3-small-v1",
        embedding_dimensions=1536,
        legal_review_manifest_path=tmp_path / "legal-review.json",
        openai_api_key="configured",
        tavily_api_key="configured",
        enforce_legal_readiness_gate=(mode == "production"),
    )


def _install_health_adapters(monkeypatch: pytest.MonkeyPatch, settings, *, source_available: bool = True):
    import backend.history.store

    import vietnam_legal_agent.config
    import vietnam_legal_agent.infra.session_store
    import vietnam_legal_agent.retrieval.universal_retriever

    monkeypatch.setattr(vietnam_legal_agent.config, "get_settings", lambda: settings)
    monkeypatch.setattr(backend.history.store, "_store", _async_value(_Store()))
    monkeypatch.setattr(vietnam_legal_agent.infra.session_store, "get_redis", _async_value(_Redis()))
    monkeypatch.setattr(
        vietnam_legal_agent.retrieval.universal_retriever,
        "universal_retriever",
        SimpleNamespace(is_available=source_available, corpus_id="universal-vietnamese-legal", corpus_version="test"),
    )


@pytest.mark.asyncio
async def test_preview_readiness_uses_universal_corpus_only_and_reports_redis(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings("preview", tmp_path)
    _install_health_adapters(monkeypatch, settings)

    payload, ready = await readiness_payload()

    assert payload["dependencies"]["redis"] == "error"
    assert payload["dependencies"]["database"] == "ok"
    assert payload["retrieval_sources"]["universal_legal"]["status"] == "ready"
    assert payload["retrieval_sources"]["qdrant_legal"]["status"] == "disabled"
    assert payload["corpus"]["status"] == "preview_ready"
    assert payload["capabilities"]["legal_chat"]["status"] == "ready"
    assert ready is True


@pytest.mark.asyncio
async def test_missing_universal_corpus_blocks_legal_readiness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings("preview", tmp_path)
    _install_health_adapters(monkeypatch, settings, source_available=False)

    payload, ready = await readiness_payload()

    assert payload["retrieval_sources"]["universal_legal"]["status"] == "unavailable"
    assert payload["capabilities"]["legal_chat"] == {
        "status": "blocked",
        "reason": "universal_corpus_unavailable",
    }
    assert payload["status"] == "not_ready"
    assert ready is False


@pytest.mark.asyncio
async def test_production_review_must_match_the_complete_corpus_hash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings("production", tmp_path)
    corpus_hash = hashlib.sha256(settings.universal_corpus_manifest_path.read_bytes()).hexdigest()
    settings.legal_review_manifest_path.write_text(
        json.dumps({
            "schema_version": "legal-corpus-review-v1",
            "status": "ready",
            "corpus_sha256": corpus_hash,
            "reviewer_id": "reviewer-1",
            "reviewed_at": "2026-09-30T12:00:00Z",
        }),
        encoding="utf-8",
    )
    _install_health_adapters(monkeypatch, settings)

    payload, ready = await readiness_payload()

    assert payload["legal_readiness"]["status"] == "ready"
    assert payload["corpus"]["legally_ready"] is True
    assert payload["capabilities"]["legal_chat"]["status"] == "ready"
    assert ready is True


@pytest.mark.asyncio
async def test_missing_production_review_degrades_legal_capability(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = _settings("production", tmp_path)
    _install_health_adapters(monkeypatch, settings)

    payload, ready = await readiness_payload()

    assert payload["legal_readiness"]["status"] == "pending"
    assert payload["capabilities"]["legal_chat"] == {"status": "blocked", "reason": "legal_review_pending"}
    assert payload["status"] == "degraded"
    assert ready is True


@pytest.mark.asyncio
async def test_chat_admission_checks_database_and_provider_without_full_readiness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import backend.history.store

    import vietnam_legal_agent.config

    settings = _settings("preview", tmp_path)
    monkeypatch.setattr(vietnam_legal_agent.config, "get_settings", lambda: settings)
    monkeypatch.setattr(backend.history.store, "_store", _async_value(_Store()))

    payload, reason = await chat_admission_readiness()

    assert reason == ""
    assert payload["preview"] is True
    assert payload["capabilities"]["history"] == {"status": "ready", "reason": "ok"}
    assert payload["dependencies"] == {"database": "ok", "openai": "ok"}


def _async_value(value):
    async def resolve():
        return value

    return resolve
