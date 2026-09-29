from __future__ import annotations

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


class _MismatchedQdrant(_Qdrant):
    def scroll(self, _name: str, **_kwargs):
        points, offset = super().scroll(_name, **_kwargs)
        points[0].payload["Embedding_Profile"] = "stale-profile"
        return points, offset


def _settings(mode: str):
    return SimpleNamespace(
        corpus_id="epr",
        corpus_version="v-test",
        corpus_runtime_mode=mode,
        enable_universal_retrieval=False,
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
    import epr_agent.retrieval.universal_retriever

    settings = _settings(mode)
    settings.enable_universal_retrieval = True
    monkeypatch.setattr(epr_agent.config, "get_settings", lambda: settings)
    monkeypatch.setattr(backend.history.store, "_store", _async_value(_Store()))
    monkeypatch.setattr(epr_agent.infra.session_store, "get_redis", _async_value(_Redis()))
    monkeypatch.setattr(epr_agent.retrieval.retrieval, "_get_qdrant_client", lambda: _Qdrant())
    monkeypatch.setattr(
        epr_agent.retrieval.universal_retriever,
        "universal_retriever",
        SimpleNamespace(is_available=True),
    )
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
    assert payload["dependencies"]["database"] == "ok"
    assert payload["retrieval_sources"]["universal_legal"] == {
        "enabled": True,
        "status": "ready",
    }
    assert payload["retrieval_sources"]["qdrant_legal"]["index_matches"] is True
    assert payload["capabilities"]["history"]["status"] == "ready"
    assert payload["capabilities"]["legal_chat"]["status"] == expected
    assert ready is (expected == "ready")


@pytest.mark.asyncio
async def test_enabled_but_unavailable_universal_corpus_blocks_legal_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.history.store
    import scripts.canonical_corpus

    import epr_agent.config
    import epr_agent.infra.session_store
    import epr_agent.retrieval.retrieval
    import epr_agent.retrieval.universal_retriever

    settings = _settings("preview")
    settings.enable_universal_retrieval = True
    monkeypatch.setattr(epr_agent.config, "get_settings", lambda: settings)
    monkeypatch.setattr(backend.history.store, "_store", _async_value(_Store()))
    monkeypatch.setattr(epr_agent.infra.session_store, "get_redis", _async_value(_Redis()))
    monkeypatch.setattr(epr_agent.retrieval.retrieval, "_get_qdrant_client", lambda: _Qdrant())
    monkeypatch.setattr(
        epr_agent.retrieval.universal_retriever,
        "universal_retriever",
        SimpleNamespace(is_available=False),
    )
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

    assert payload["retrieval_sources"]["universal_legal"] == {
        "enabled": True,
        "status": "unavailable",
    }
    assert payload["capabilities"]["legal_chat"] == {
        "status": "blocked",
        "reason": "universal_corpus_unavailable",
    }
    assert payload["status"] == "not_ready"
    assert ready is False


@pytest.mark.asyncio
async def test_chat_admission_checks_database_and_provider_without_full_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.history.store

    import epr_agent.config

    settings = _settings("preview")
    monkeypatch.setattr(epr_agent.config, "get_settings", lambda: settings)
    monkeypatch.setattr(backend.history.store, "_store", _async_value(_Store()))

    payload, reason = await chat_admission_readiness()

    assert reason == ""
    assert payload["preview"] is True
    assert payload["capabilities"]["history"] == {"status": "ready", "reason": "ok"}
    assert payload["dependencies"] == {"database": "ok", "openai": "ok"}


@pytest.mark.asyncio
async def test_preview_blocks_chat_when_active_index_version_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.history.store
    import scripts.canonical_corpus

    import epr_agent.config
    import epr_agent.infra.session_store
    import epr_agent.retrieval.retrieval

    monkeypatch.setattr(epr_agent.config, "get_settings", lambda: _settings("preview"))
    monkeypatch.setattr(backend.history.store, "_store", _async_value(_Store()))
    monkeypatch.setattr(epr_agent.infra.session_store, "get_redis", _async_value(_Redis()))
    monkeypatch.setattr(epr_agent.retrieval.retrieval, "_get_qdrant_client", lambda: _MismatchedQdrant())
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

    assert payload["corpus"]["status"] == "version_mismatch"
    assert payload["capabilities"]["legal_chat"] == {
        "status": "blocked",
        "reason": "corpus_index_mismatch",
    }
    assert ready is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enforce", "expected_status", "expected_capability_status"),
    [(True, "degraded", "blocked"), (False, "ready", "ready")],
)
async def test_readiness_reports_pending_review_even_when_preview_does_not_enforce_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    enforce: bool,
    expected_status: str,
    expected_capability_status: str,
) -> None:
    import backend.history.store
    import scripts.canonical_corpus

    import epr_agent.config
    import epr_agent.infra.session_store
    import epr_agent.retrieval.retrieval
    from epr_agent.tools.legal_readiness import EPR_SCOPE_ANCHORS, EPR_SCOPE_APPENDICES

    settings = _settings("preview")
    settings.enforce_legal_readiness_gate = enforce
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
    assert payload["status"] == expected_status
    assert payload["legal_readiness"]["status"] == "pending"
    assert payload["legal_readiness"]["legally_ready"] is False
    assert payload["corpus"]["legally_ready"] is False
    assert payload["capabilities"]["legal_chat"]["status"] == expected_capability_status
    assert payload["capabilities"]["legal_chat"]["reason"] == (
        "legal_review_pending" if enforce else "preview_snapshot"
    )


def _async_value(value):
    async def resolve():
        return value

    return resolve
