from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from backend.api.routes.health import readiness_payload


class _Store:
    async def schema_status(self):
        return {"status": "ready", "code": "ok", "issues": []}


class _Redis:
    async def ping(self):
        raise ConnectionError("offline")


class _Qdrant:
    def get_collection(self, _name: str):
        return SimpleNamespace(points_count=1)

    def scroll(self, _name: str, **_kwargs):
        return ([SimpleNamespace(payload={
            "Corpus_ID": "epr",
            "Corpus_Version": "v-test",
            "Corpus_SHA256": "sha-test",
            "Index_Schema_Version": "schema-test",
            "Embedding_Profile": "embedding-test",
            "Embedding_Dimensions": 8,
        })], None)


def _settings(mode: str):
    return SimpleNamespace(
        corpus_id="epr",
        corpus_version="v-test",
        corpus_runtime_mode=mode,
        index_schema_version="schema-test",
        embedding_profile="embedding-test",
        embedding_dimensions=8,
        law_collection="law-test",
        corpus_manifest_path=Path("manifest.json"),
        rule_pack_path=Path("rules.json"),
        amendment_map_path=Path("amendments.json"),
        appendix_xxii_data_path=Path("missing.jsonl"),
        law_data_path=Path("law.json"),
        openai_api_key="configured",
        tavily_api_key="configured",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "expected"), [("preview", "ready"), ("production", "blocked")])
async def test_readiness_separates_preview_legal_gate_and_redis(
    monkeypatch: pytest.MonkeyPatch, mode: str, expected: str
) -> None:
    import backend.history.store
    import scripts.canonical_corpus

    import epr_agent.config
    import epr_agent.infra.session_store
    import epr_agent.retrieval.retrieval

    monkeypatch.setattr(epr_agent.config, "get_settings", lambda: _settings(mode))
    monkeypatch.setattr(backend.history.store, "_store", _async_value(_Store()))
    monkeypatch.setattr(epr_agent.infra.session_store, "get_redis", _async_value(_Redis()))
    monkeypatch.setattr(epr_agent.retrieval.retrieval, "_get_qdrant_client", lambda: _Qdrant())
    monkeypatch.setattr(scripts.canonical_corpus, "corpus_sha256", lambda **_kwargs: "sha-test")
    monkeypatch.setattr(scripts.canonical_corpus, "corpus_readiness_audit", lambda **_kwargs: {
        "source_errors": [],
        "amendment_errors": ["amendment_map_legal_review_pending", "entry_0:resolution_pending"],
        "rule_pack_errors": ["rule_pack_legal_review_pending"],
        "ready_for_promotion": False,
        "manifest_legal_review_status": "pending",
        "amendment_map_sha256": "amendment-sha",
        "rule_pack_sha256": "rule-sha",
    })

    payload, ready = await readiness_payload()

    assert payload["dependencies"]["redis"] == "error"
    assert payload["capabilities"]["history"]["status"] == "ready"
    assert payload["capabilities"]["legal_chat"]["status"] == expected
    assert ready is (expected == "ready")


def _async_value(value):
    async def resolve():
        return value

    return resolve
