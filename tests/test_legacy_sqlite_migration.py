from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from scripts.migrate_legacy_sqlite import migrate

from epr_agent.infra.persistence import DatabaseSchemaMismatch, PersistenceStore, sqlite_database_url


def _legacy_database(path: Path, *, metadata: str = '{"source":"legacy"}', orphan: bool = False) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE users (id TEXT PRIMARY KEY, created_at REAL NOT NULL);
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
                archived INTEGER NOT NULL, pinned INTEGER NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL, model TEXT,
                metadata_json TEXT NOT NULL, created_at REAL NOT NULL
            );
            CREATE TABLE conversation_summaries (
                conversation_id TEXT PRIMARY KEY, short_summary TEXT NOT NULL, last_updated REAL NOT NULL
            );
            """
        )
        connection.execute("INSERT INTO users VALUES (?, ?)", ("legacy:owner", 1_700_000_000.0))
        connection.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, 0, 1, ?, ?)",
            ("conv-1", "legacy:owner", "Điều 77", 1_700_000_000.0, 1_700_000_001.0),
        )
        connection.execute(
            "INSERT INTO messages(conversation_id, role, content, model, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("missing" if orphan else "conv-1", "assistant", "Nội dung cũ", "legacy", metadata, 1_700_000_002.0),
        )
        connection.execute(
            "INSERT INTO conversation_summaries VALUES (?, ?, ?)",
            ("conv-1", "Tóm tắt cũ", 1_700_000_003.0),
        )


def test_legacy_sqlite_migration_is_dry_run_first_and_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "history.sqlite3"
    backup = tmp_path / "history.backup.sqlite3"
    _legacy_database(database)

    dry_run = migrate(database)
    assert dry_run.schema == "legacy"
    assert dry_run.dry_run is True
    assert dry_run.safe_to_apply is True
    assert dry_run.changed is False
    assert backup.exists() is False

    applied = migrate(database, apply=True, backup=backup)
    assert applied.changed is True
    assert applied.source_counts["messages"] == applied.target_counts["messages"] == 1
    assert backup.is_file()

    with sqlite3.connect(database) as connection:
        message_columns = {row[1] for row in connection.execute("PRAGMA table_info(messages)")}
        assert "metadata" in message_columns
        assert "metadata_json" not in message_columns
        metadata, timestamp = connection.execute("SELECT metadata, created_at FROM messages").fetchone()
        assert json.loads(metadata) == {"source": "legacy"}
        assert isinstance(timestamp, str) and "+00:00" in timestamp
        assert connection.execute("SELECT summary FROM conversation_summaries").fetchone()[0] == "Tóm tắt cũ"
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == applied.head_revision

    second = migrate(database, apply=True)
    assert second.schema == "current"
    assert second.changed is False


@pytest.mark.parametrize(
    ("metadata", "orphan", "expected"),
    [("{bad-json", False, "invalid_metadata_json"), ('{"ok":true}', True, "orphan_rows")],
)
def test_legacy_sqlite_migration_blocks_invalid_input(
    tmp_path: Path, metadata: str, orphan: bool, expected: str
) -> None:
    database = tmp_path / "invalid.sqlite3"
    _legacy_database(database, metadata=metadata, orphan=orphan)

    report = migrate(database, apply=True)

    assert report.safe_to_apply is False
    assert report.changed is False
    assert any(expected in issue for issue in report.issues)
    with sqlite3.connect(database) as connection:
        assert "metadata_json" in {row[1] for row in connection.execute("PRAGMA table_info(messages)")}


@pytest.mark.asyncio
async def test_persistence_fails_fast_for_legacy_schema(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    _legacy_database(database)
    store = PersistenceStore(sqlite_database_url(str(database)))
    try:
        with pytest.raises(DatabaseSchemaMismatch) as error:
            await store.initialize()
        assert "messages:legacy_metadata_json" in error.value.issues
        status = await store.schema_status()
        assert status["code"] == "database_schema_mismatch"
    finally:
        await store.close()
