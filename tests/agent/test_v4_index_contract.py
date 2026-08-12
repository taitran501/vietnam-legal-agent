"""Fast, deterministic contracts for versioned law-index publication."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest
from scripts import build_index, ensure_law_index


class _FakeQdrant:
    def __init__(self, payload: dict, *, points_count: int = 1, aliases: list[object] | None = None) -> None:
        self.payload = payload
        self.points_count = points_count
        self.aliases = aliases or []
        self.alias_operations: list[list[object]] = []

    def get_collection(self, _collection: str):
        return SimpleNamespace(points_count=self.points_count)

    def scroll(self, *_args, **_kwargs):
        return [SimpleNamespace(id="chunk-1", payload=self.payload)], None

    def get_aliases(self):
        return SimpleNamespace(aliases=self.aliases)

    def update_collection_aliases(self, *, change_aliases_operations):
        self.alias_operations.append(list(change_aliases_operations))


def _settings():
    return SimpleNamespace(
        embedding_profile="openai-text-embedding-3-small-v1",
        embedding_dimensions=1536,
        chunking_profile="legal-structure-v2",
    )


def _payload() -> dict[str, object]:
    return {
        "Corpus_SHA256": "a" * 64,
        "Index_Schema_Version": "legal-index-v4",
        "Embedding_Profile": "openai-text-embedding-3-small-v1",
        "Embedding_Dimensions": 1536,
        "Chunking_Strategy": "legal-structure-v2",
    }


def test_matching_collection_is_idempotent_only_when_schema_and_embedding_match() -> None:
    client = _FakeQdrant(_payload())
    settings = _settings()

    assert ensure_law_index._matching_collection(
        client, "law-epr", expected_count=1, digest="a" * 64, schema="legal-index-v4", settings=settings
    )

    client.payload["Embedding_Dimensions"] = 3072
    assert not ensure_law_index._matching_collection(
        client, "law-epr", expected_count=1, digest="a" * 64, schema="legal-index-v4", settings=settings
    )


def test_alias_switch_deletes_only_alias_and_keeps_previous_collection(monkeypatch) -> None:
    # qdrant-client is intentionally optional in the fast unit environment;
    # inject the tiny model surface used by the alias operation so this test
    # still verifies the atomic operation ordering without a live server.
    class _Model:
        def __init__(self, **values):
            self.__dict__.update(values)

    fake_models = types.ModuleType("qdrant_client.http.models")
    for name in ("CreateAlias", "CreateAliasOperation", "DeleteAlias", "DeleteAliasOperation"):
        setattr(fake_models, name, _Model)
    fake_http = types.ModuleType("qdrant_client.http")
    fake_http.models = fake_models
    fake_client = types.ModuleType("qdrant_client")
    fake_client.http = fake_http
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_client)
    monkeypatch.setitem(sys.modules, "qdrant_client.http", fake_http)
    monkeypatch.setitem(sys.modules, "qdrant_client.http.models", fake_models)

    client = _FakeQdrant(
        _payload(),
        aliases=[SimpleNamespace(alias_name="law_collection", collection_name="law_old")],
    )

    ensure_law_index._switch_alias(client, "law_collection", "law_new")

    assert len(client.alias_operations) == 1
    operations = client.alias_operations[0]
    assert len(operations) == 2
    assert operations[0].delete_alias.alias_name == "law_collection"
    assert operations[1].create_alias.alias_name == "law_collection"
    assert operations[1].create_alias.collection_name == "law_new"


def test_index_source_contract_fails_before_embedding_on_missing_heading() -> None:
    with pytest.raises(ValueError, match="missing legal heading"):
        build_index.validate_index_contract([{"Text": "Nội dung không có Điều."}])


def test_index_source_contract_accepts_traceable_legal_record() -> None:
    build_index.validate_index_contract([{"Điều": "Điều 77", "Chương": "Chương X", "Text": "Nội dung pháp luật."}])
