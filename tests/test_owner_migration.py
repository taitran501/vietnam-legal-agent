"""Dry-run, transactional owner migration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from backend.api.principal import oidc_user_id
from scripts import migrate_owners

from epr_agent.infra.persistence import PersistenceStore, sqlite_database_url


@pytest.mark.asyncio
async def test_owner_migration_dry_run_and_apply_are_idempotent(tmp_path: Path) -> None:
    database_url = sqlite_database_url(str(tmp_path / "owners.sqlite3"))
    backup = tmp_path / "owners.backup.sqlite3"
    store = PersistenceStore(database_url)
    await store.initialize()
    await store.ensure_conversation("legacy:owner-a", "conversation-a", "A")
    await store.ensure_conversation("legacy:owner-b", "conversation-b", "B")
    await store.close()

    mapping = {"legacy:owner-a": {"issuer": "https://sso.example", "subject": "user-a"}}
    report = await migrate_owners.audit(database_url, mapping)
    assert report["status"] == "ready"
    assert report["mapped"] == [{"from": "legacy:owner-a", "to": oidc_user_id("https://sso.example", "user-a")}]
    assert report["quarantined"] == ["legacy:owner-b"]

    applied = await migrate_owners.apply(database_url, mapping, backup)
    assert applied["status"] == "applied"
    assert backup.exists()

    migrated_store = PersistenceStore(database_url)
    await migrated_store.initialize()
    try:
        assert len(await migrated_store.list_conversations(oidc_user_id("https://sso.example", "user-a"))) == 1
        assert await migrated_store.list_conversations("legacy:owner-a") == []
        assert await migrated_store.list_conversations("legacy:owner-b") == []
    finally:
        await migrated_store.close()

    second_audit = await migrate_owners.audit(database_url, mapping)
    assert second_audit["mapped"] == []
    assert second_audit["quarantined"] == []


def test_mapping_file_shape_is_external_and_hash_free(tmp_path: Path) -> None:
    mapping_path = tmp_path / "owners.json"
    mapping_path.write_text(
        json.dumps({"legacy:owner-a": {"issuer": "https://sso.example", "subject": "user-a"}}),
        encoding="utf-8",
    )
    loaded = migrate_owners._mapping(mapping_path)
    assert loaded["legacy:owner-a"]["subject"] == "user-a"
