"""Audit and migrate the pre-SQLAlchemy SQLite history database.

The command is dry-run-first.  ``--apply`` creates a SQLite online backup,
builds the current schema in a sibling file, validates the copied rows and
foreign keys, then atomically replaces the original database.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from epr_agent.infra.persistence import _EXPECTED_SCHEMA_COLUMNS, Base

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class MigrationReport:
    database: str
    schema: str
    dry_run: bool
    head_revision: str
    source_counts: dict[str, int] = field(default_factory=dict)
    target_counts: dict[str, int] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    backup: str | None = None
    changed: bool = False

    @property
    def safe_to_apply(self) -> bool:
        return self.schema in {
            "legacy",
            "hybrid",
            "previous_current",
            "current_unversioned",
            "current",
        } and not self.issues


def _head_revision() -> str:
    config = Config(str(ROOT / "alembic.ini"))
    return str(ScriptDirectory.from_config(config).get_current_head())


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not str(row[0]).startswith("sqlite_")
    }


def _columns(connection: sqlite3.Connection, table: str) -> dict[str, str]:
    return {str(row[1]): str(row[2]).upper() for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _schema_kind(connection: sqlite3.Connection) -> str:
    tables = _tables(connection)
    if not tables & set(_EXPECTED_SCHEMA_COLUMNS):
        return "empty"
    messages = _columns(connection, "messages") if "messages" in tables else {}
    summaries = _columns(connection, "conversation_summaries") if "conversation_summaries" in tables else {}
    conversations = _columns(connection, "conversations") if "conversations" in tables else {}
    legacy = (
        "metadata_json" in messages
        or "short_summary" in summaries
        or conversations.get("created_at") in {"REAL", "FLOAT", "NUMERIC"}
        or messages.get("created_at") in {"REAL", "FLOAT", "NUMERIC"}
    )
    current = all(table in tables and expected <= set(_columns(connection, table)) for table, expected in _EXPECTED_SCHEMA_COLUMNS.items())
    previous_expected = {
        table: (
            expected - {"turn_id", "status", "superseded_by_message_id", "updated_at"}
            if table == "messages"
            else expected
        )
        for table, expected in _EXPECTED_SCHEMA_COLUMNS.items()
        if table != "conversation_turns"
    }
    previous_current = all(
        table in tables and expected <= set(_columns(connection, table))
        for table, expected in previous_expected.items()
    )
    if legacy and current:
        return "hybrid"
    if legacy:
        return "legacy"
    if current:
        return "current" if "alembic_version" in tables else "current_unversioned"
    if previous_current:
        return "previous_current"
    return "unknown"


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _datetime_text(value: Any) -> str:
    if value is None or value == "":
        return datetime.now(UTC).isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), UTC).isoformat()
    text = str(value).strip()
    try:
        return datetime.fromtimestamp(float(text), UTC).isoformat()
    except ValueError:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()


def _json_text(value: Any, default: Any) -> str:
    if value is None or value == "":
        return json.dumps(default, ensure_ascii=False)
    parsed = json.loads(value) if isinstance(value, str) else value
    return json.dumps(parsed, ensure_ascii=False)


def _audit(connection: sqlite3.Connection, report: MigrationReport) -> None:
    tables = _tables(connection)
    for table in sorted(tables & set(_EXPECTED_SCHEMA_COLUMNS)):
        report.source_counts[table] = _count(connection, table)

    if report.schema in {"empty", "unknown"}:
        report.issues.append(f"unsupported_schema:{report.schema}")
        return

    if "messages" in tables:
        columns = _columns(connection, "messages")
        metadata_column = "metadata" if "metadata" in columns else "metadata_json" if "metadata_json" in columns else ""
        if not metadata_column:
            report.issues.append("messages:metadata_missing")
        else:
            for row in connection.execute(f'SELECT id, "{metadata_column}" FROM messages'):
                try:
                    _json_text(row[1], {})
                except (TypeError, ValueError, json.JSONDecodeError):
                    report.issues.append(f"messages:{row[0]}:invalid_metadata_json")

    orphan_checks = {
        "messages": "SELECT COUNT(*) FROM messages m LEFT JOIN conversations c ON c.id=m.conversation_id WHERE c.id IS NULL",
        "conversation_turns": "SELECT COUNT(*) FROM conversation_turns t LEFT JOIN conversations c ON c.id=t.conversation_id WHERE c.id IS NULL",
        "conversation_summaries": "SELECT COUNT(*) FROM conversation_summaries s LEFT JOIN conversations c ON c.id=s.conversation_id WHERE c.id IS NULL",
        "case_states": "SELECT COUNT(*) FROM case_states s LEFT JOIN conversations c ON c.id=s.conversation_id WHERE c.id IS NULL",
        "agent_runs": "SELECT COUNT(*) FROM agent_runs r LEFT JOIN conversations c ON c.id=r.conversation_id WHERE c.id IS NULL",
        "message_feedback": "SELECT COUNT(*) FROM message_feedback f LEFT JOIN messages m ON m.id=f.message_id WHERE m.id IS NULL",
    }
    for table, query in orphan_checks.items():
        if table in tables and "conversations" in tables:
            count = int(connection.execute(query).fetchone()[0])
            if count:
                report.issues.append(f"{table}:orphan_rows:{count}")
    if "conversations" in tables and "users" in tables:
        count = int(connection.execute(
            "SELECT COUNT(*) FROM conversations c LEFT JOIN users u ON u.id=c.user_id WHERE u.id IS NULL"
        ).fetchone()[0])
        if count:
            report.issues.append(f"conversations:orphan_owners:{count}")


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if table not in _tables(connection):
        return []
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]


def _pick(row: dict[str, Any], name: str, default: Any = None) -> Any:
    value = row.get(name, default)
    return default if value is None else value


def _mapped_rows(source: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    now = datetime.now(UTC).isoformat()
    mapped: dict[str, list[dict[str, Any]]] = {}
    mapped["users"] = [
        {"id": row["id"], "created_at": _datetime_text(_pick(row, "created_at", now))}
        for row in _rows(source, "users")
    ]
    mapped["conversations"] = [
        {
            "id": row["id"], "user_id": row["user_id"], "title": _pick(row, "title", "New Conversation"),
            "archived": int(bool(_pick(row, "archived", 0))), "pinned": int(bool(_pick(row, "pinned", 0))),
            "created_at": _datetime_text(_pick(row, "created_at", now)),
            "updated_at": _datetime_text(_pick(row, "updated_at", now)),
        }
        for row in _rows(source, "conversations")
    ]
    mapped["messages"] = []
    for row in _rows(source, "messages"):
        metadata = row.get("metadata", row.get("metadata_json"))
        mapped["messages"].append({
            "id": row["id"], "conversation_id": row["conversation_id"], "role": row["role"],
            "content": _pick(row, "content", ""), "metadata": _json_text(metadata, {}),
            "turn_id": row.get("turn_id"), "status": _pick(row, "status", "complete"),
            "superseded_by_message_id": row.get("superseded_by_message_id"),
            "created_at": _datetime_text(_pick(row, "created_at", now)),
            "updated_at": _datetime_text(_pick(row, "updated_at", _pick(row, "created_at", now))),
        })
    mapped["conversation_turns"] = [
        {
            "id": row["id"], "conversation_id": row["conversation_id"], "user_id": row["user_id"],
            "query": _pick(row, "query", ""), "mode": _pick(row, "mode", "auto"),
            "operation": _pick(row, "operation", "message"), "status": _pick(row, "status", "complete"),
            "replay_metadata": _json_text(_pick(row, "replay_metadata", {}), {}),
            "user_message_id": row.get("user_message_id"), "assistant_message_id": row["assistant_message_id"],
            "target_assistant_message_id": row.get("target_assistant_message_id"), "error_code": row.get("error_code"),
            "created_at": _datetime_text(_pick(row, "created_at", now)), "updated_at": _datetime_text(_pick(row, "updated_at", now)),
        }
        for row in _rows(source, "conversation_turns")
    ]
    mapped["conversation_summaries"] = [
        {
            "conversation_id": row["conversation_id"],
            "summary": _pick(row, "summary", _pick(row, "short_summary", "")),
            "updated_at": _datetime_text(_pick(row, "updated_at", _pick(row, "last_updated", now))),
        }
        for row in _rows(source, "conversation_summaries")
    ]
    mapped["case_states"] = [
        {
            "conversation_id": row["conversation_id"], "user_id": row["user_id"],
            "task_type": _pick(row, "task_type", "assess_epr_obligation"),
            "status": _pick(row, "status", "collecting"), "facts": _json_text(_pick(row, "facts", {}), {}),
            "missing_facts": _json_text(_pick(row, "missing_facts", []), []), "last_query": _pick(row, "last_query", ""),
            "schema_version": _pick(row, "schema_version", "legacy-v3"), "decision_status": row.get("decision_status"),
            "issue_states": _json_text(_pick(row, "issue_states", {}), {}), "as_of_date": _pick(row, "as_of_date", ""),
            "created_at": _datetime_text(_pick(row, "created_at", now)), "updated_at": _datetime_text(_pick(row, "updated_at", now)),
        }
        for row in _rows(source, "case_states")
    ]
    mapped["agent_runs"] = []
    for row in _rows(source, "agent_runs"):
        mapped["agent_runs"].append({
            "trace_id": row["trace_id"], "user_id": row["user_id"], "conversation_id": row["conversation_id"],
            "task_type": row.get("task_type"), "route": row.get("route"), "corpus_id": row.get("corpus_id"),
            "corpus_sha": row.get("corpus_sha"), "embedding_profile": row.get("embedding_profile"),
            "pipeline_version": row.get("pipeline_version"), "source": row.get("source"), "duration_ms": row.get("duration_ms"),
            "evidence_count": int(_pick(row, "evidence_count", 0)), "cache_status": row.get("cache_status"),
            "error_code": row.get("error_code"), "action_sequence": _json_text(_pick(row, "action_sequence", []), []),
            "tool_results": _json_text(_pick(row, "tool_results", []), []), "termination_reason": row.get("termination_reason"),
            "outcome": row.get("outcome"), "result_type": row.get("result_type"),
            "understanding_confidence": row.get("understanding_confidence"),
            "required_issue_count": int(_pick(row, "required_issue_count", 0)),
            "covered_issue_count": int(_pick(row, "covered_issue_count", 0)),
            "started_at": _datetime_text(_pick(row, "started_at", now)), "ended_at": _datetime_text(_pick(row, "ended_at", now)),
        })
    mapped["agent_run_events"] = [
        {
            "id": row["id"], "trace_id": row["trace_id"], "sequence": row["sequence"], "node": row["node"],
            "status": _pick(row, "status", "completed"), "reason_code": _pick(row, "reason_code", ""),
            "tool_name": row.get("tool_name"), "duration_ms": row.get("duration_ms"), "error_code": row.get("error_code"),
            "payload": _json_text(_pick(row, "payload", {}), {}), "created_at": _datetime_text(_pick(row, "created_at", now)),
        }
        for row in _rows(source, "agent_run_events")
    ]
    mapped["message_feedback"] = [
        {
            "id": row["id"], "user_id": row["user_id"], "conversation_id": row["conversation_id"],
            "message_id": row["message_id"], "rating": row["rating"], "comment": row.get("comment"),
            "created_at": _datetime_text(_pick(row, "created_at", now)), "updated_at": _datetime_text(_pick(row, "updated_at", now)),
        }
        for row in _rows(source, "message_feedback")
    ]
    return mapped


def _insert_rows(target: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    names = ", ".join(f'"{name}"' for name in columns)
    placeholders = ", ".join("?" for _ in columns)
    target.executemany(
        f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})',
        [[row[name] for name in columns] for row in rows],
    )


def _backup(source_path: Path, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source_path)) as source, closing(sqlite3.connect(backup_path)) as target:
        source.backup(target)


def migrate(database: Path, *, apply: bool = False, backup: Path | None = None) -> MigrationReport:
    database = database.resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    head = _head_revision()
    with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as source:
        schema = _schema_kind(source)
        report = MigrationReport(str(database), schema, not apply, head)
        _audit(source, report)
    if not apply or not report.safe_to_apply:
        return report

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = (backup or database.with_name(f"{database.name}.backup-{timestamp}" )).resolve()
    _backup(database, backup_path)
    report.backup = str(backup_path)

    if schema == "current":
        with closing(sqlite3.connect(database)) as connection:
            current_revision_row = connection.execute(
                "SELECT version_num FROM alembic_version LIMIT 1"
            ).fetchone()
            current_revision = str(current_revision_row[0]) if current_revision_row else ""
            if current_revision != head:
                connection.execute("DELETE FROM alembic_version")
                connection.execute("INSERT INTO alembic_version(version_num) VALUES (?)", (head,))
                connection.commit()
                report.changed = True
        return report
    if schema == "current_unversioned":
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
            connection.execute("DELETE FROM alembic_version")
            connection.execute("INSERT INTO alembic_version(version_num) VALUES (?)", (head,))
            connection.commit()
        report.changed = True
        return report

    fd, temp_name = tempfile.mkstemp(prefix=f".{database.stem}-migrating-", suffix=".sqlite3", dir=database.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        engine = create_engine(f"sqlite:///{temp_path.as_posix()}")
        Base.metadata.create_all(engine)
        engine.dispose(close=True)
        del engine
        # SQLAlchemy/SQLite can retain a pooled Windows file handle until the
        # connection wrapper is collected, which would make the atomic swap
        # fail even though every transaction has completed.
        gc.collect()
        with closing(sqlite3.connect(backup_path)) as source, closing(sqlite3.connect(temp_path)) as target:
            target.execute("PRAGMA foreign_keys=OFF")
            mapped = _mapped_rows(source)
            for table in (
                "users", "conversations", "messages", "conversation_turns", "conversation_summaries", "case_states",
                "agent_runs", "agent_run_events", "message_feedback",
            ):
                _insert_rows(target, table, mapped[table])
            target.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            target.execute("INSERT INTO alembic_version(version_num) VALUES (?)", (head,))
            target.commit()
            target.execute("PRAGMA foreign_keys=ON")
            foreign_key_errors = target.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise RuntimeError(f"target_foreign_key_errors:{len(foreign_key_errors)}")
            for table, count in report.source_counts.items():
                report.target_counts[table] = _count(target, table)
                if report.target_counts[table] != count:
                    raise RuntimeError(f"row_count_mismatch:{table}:{count}:{report.target_counts[table]}")
        gc.collect()
        for attempt in range(5):
            try:
                os.replace(temp_path, database)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                gc.collect()
                time.sleep(0.05 * (attempt + 1))
        for suffix in ("-wal", "-shm", "-journal"):
            database.with_name(database.name + suffix).unlink(missing_ok=True)
        report.changed = True
        return report
    finally:
        temp_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--apply", action="store_true", help="Apply after a successful audit (default is dry-run)")
    args = parser.parse_args(argv)
    try:
        report = migrate(args.database, apply=args.apply, backup=args.backup)
    except Exception as exc:  # noqa: BLE001 - CLI returns a stable non-zero failure
        print(json.dumps({
            "event": "migration_failure",
            "status": "error",
            "stage": "command",
            "error": type(exc).__name__,
            "message": str(exc),
        }, ensure_ascii=False))
        return 1
    payload = asdict(report)
    payload["safe_to_apply"] = report.safe_to_apply
    payload["status"] = "ok" if report.safe_to_apply else "blocked"
    if not report.safe_to_apply:
        payload["event"] = "migration_failure"
        payload["stage"] = "audit"
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.safe_to_apply else 2


if __name__ == "__main__":
    sys.exit(main())
