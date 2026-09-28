from __future__ import annotations

import json
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
        enforce_legal_readiness_gate=False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("mode", "expected"), [("preview", "ready"), ("production", "ready")])
async def test_readiness_uses_technical_corpus_gate_and_reports_redis(
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
        "amendment_errors": [],
        "rule_pack_errors": [],
        "ready_for_promotion": True,
        "technical_ready": True,
        "source_snapshot_status": "technical",
        "amendment_map_sha256": "amendment-sha",
        "rule_pack_sha256": "rule-sha",
    })

    payload, ready = await readiness_payload()

    assert payload["dependencies"]["redis"] == "error"
    assert payload["capabilities"]["history"]["status"] == "ready"
    assert payload["capabilities"]["legal_chat"]["status"] == expected
    assert ready is (expected == "ready")


@pytest.mark.asyncio
async def test_readiness_reports_degraded_when_legal_review_is_pending(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import backend.history.store
    import scripts.canonical_corpus

    import epr_agent.config
    import epr_agent.infra.session_store
    import epr_agent.retrieval.retrieval
    from epr_agent.tools.legal_readiness import EPR_SCOPE_ANCHORS, EPR_SCOPE_APPENDICES

    settings = _settings("preview")
    settings.enforce_legal_readiness_gate = True
    settings.legal_readiness_manifest_path = tmp_path / "legal-readiness.json"
    subjects = {
        "corpus_sha256": "sha-test",
        "amendment_map_sha256": "amendment-sha",
        "rule_pack_sha256": "rule-sha",
    }
    entries = [
        {
            "anchor": anchor,
            "status": "pending_legal_review",
            "legally_ready": False,
            "reviewer_id": None,
            "reviewed_at": None,
            "review_record_id": None,
            "reviewed_intervals": [],
            "source_hashes": [],
            "review_notes": "pending",
        }
        for anchor in [*EPR_SCOPE_ANCHORS, *EPR_SCOPE_APPENDICES]
    ]
    settings.legal_readiness_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "legal-readiness-v1",
                "corpus_id": "epr",
                "corpus_version": "test",
                "subject_hashes": subjects,
                "scope": {"anchors": EPR_SCOPE_ANCHORS, "appendices": EPR_SCOPE_APPENDICES},
                "aggregate_status": "blocked",
                "entries": entries,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(epr_agent.config, "get_settings", lambda: settings)
    monkeypatch.setattr(backend.history.store, "_store", _async_value(_Store()))
    monkeypatch.setattr(epr_agent.infra.session_store, "get_redis", _async_value(_Redis()))
    monkeypatch.setattr(epr_agent.retrieval.retrieval, "_get_qdrant_client", lambda: _Qdrant())
    monkeypatch.setattr(scripts.canonical_corpus, "corpus_sha256", lambda **_kwargs: "sha-test")
    monkeypatch.setattr(scripts.canonical_corpus, "corpus_readiness_audit", lambda **_kwargs: {
        "source_errors": [],
        "amendment_errors": [],
        "rule_pack_errors": [],
        "ready_for_promotion": True,
        "technical_ready": True,
        "source_snapshot_status": "technical",
        "amendment_map_sha256": "amendment-sha",
        "rule_pack_sha256": "rule-sha",
    })

    payload, ready = await readiness_payload()

    assert ready is True
    assert payload["status"] == "degraded"
    assert payload["legal_readiness"]["status"] == "pending"
    assert payload["capabilities"]["legal_chat"] == {
        "status": "blocked",
        "reason": "legal_review_pending",
    }


def _async_value(value):
    async def resolve():
        return value

    return resolve
