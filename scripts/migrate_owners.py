"""Dry-run-first migration from legacy owner hashes to OIDC identities.

The mapping file is external and intentionally not committed. Example:

    {"legacy:<hash>": {"issuer": "https://sso.example", "subject": "abc"}}

Run without ``--apply`` to audit collisions and the quarantine set.  The
apply path takes a backup first, then moves all owner-linked rows in one
transaction.  Quarantined owners retain their data but are not addressable by
an OIDC principal.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from backend.api.principal import oidc_user_id
from backend.history.store import _database_url
from sqlalchemy import select, update

from epr_agent.config import get_settings
from epr_agent.infra.persistence import (
    AgentRunRecord,
    CaseStateRecord,
    ConversationRecord,
    FeedbackRecord,
    PersistenceStore,
    UserRecord,
)


def _mapping(path: Path) -> dict[str, dict[str, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("mapping file must be an object")
    result: dict[str, dict[str, str]] = {}
    for legacy_id, value in raw.items():
        if not isinstance(value, dict) or not value.get("issuer") or not value.get("subject"):
            raise ValueError(f"mapping for {legacy_id} must contain issuer and subject")
        result[str(legacy_id)] = {"issuer": str(value["issuer"]), "subject": str(value["subject"])}
    return result


async def audit(database_url: str, mapping: dict[str, dict[str, str]]) -> dict[str, Any]:
    store = PersistenceStore(database_url)
    await store.initialize()
    async with store.sessions() as session:
        users = list((await session.execute(select(UserRecord).order_by(UserRecord.id))).scalars().all())
    targets: dict[str, str] = {}
    mapped: list[dict[str, str]] = []
    quarantined: list[str] = []
    collisions: list[str] = []
    for user in users:
        legacy_id = str(user.id)
        lookup_id = legacy_id.removeprefix("quarantine:")
        item = mapping.get(legacy_id) or mapping.get(lookup_id)
        if item:
            target = oidc_user_id(item["issuer"], item["subject"])
            if target in targets.values() and targets.get(legacy_id) != target:
                collisions.append(f"multiple legacy owners map to {target}")
            targets[legacy_id] = target
            mapped.append({"from": legacy_id, "to": target})
        elif legacy_id.startswith(("oidc:", "service:", "dev-local", "quarantine:")):
            continue
        else:
            quarantined.append(legacy_id)
    existing_ids = {str(user.id) for user in users}
    for legacy_id, target in targets.items():
        if target in existing_ids and target != legacy_id:
            collisions.append(f"target already exists: {target}")
    await store.close()
    return {
        "status": "blocked" if collisions else "ready",
        "mapped": mapped,
        "quarantined": quarantined,
        "collisions": sorted(set(collisions)),
        "user_count": len(users),
    }


async def apply(database_url: str, mapping: dict[str, dict[str, str]], backup_path: Path) -> dict[str, Any]:
    report = await audit(database_url, mapping)
    if report["collisions"]:
        raise RuntimeError("owner migration has collisions; resolve them before --apply")
    if database_url.startswith("sqlite"):
        parsed_path = urlparse(database_url).path
        if parsed_path.startswith("/") and len(parsed_path) > 2 and parsed_path[2] == ":":
            parsed_path = parsed_path[1:]
        database_file = Path(parsed_path)
        if database_file.exists():
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            if not backup_path.exists():
                shutil.copy2(database_file, backup_path)
        elif not backup_path.exists():
            raise RuntimeError("SQLite database does not exist and no backup is available")
    elif not backup_path.exists():
        raise RuntimeError("prepare a database backup before applying a non-SQLite owner migration")
    store = PersistenceStore(database_url)
    await store.initialize()
    changes: dict[str, str] = {}
    for item in report["mapped"]:
        changes[item["from"]] = item["to"]
    changes.update({owner: f"quarantine:{owner}" for owner in report["quarantined"]})
    async with store.sessions() as session, session.begin():
        for old_id, new_id in changes.items():
            if old_id == new_id:
                continue
            if await session.get(UserRecord, new_id) is None:
                session.add(UserRecord(id=new_id))
                await session.flush()
            await session.execute(update(ConversationRecord).where(ConversationRecord.user_id == old_id).values(user_id=new_id))
            await session.execute(update(CaseStateRecord).where(CaseStateRecord.user_id == old_id).values(user_id=new_id))
            await session.execute(update(AgentRunRecord).where(AgentRunRecord.user_id == old_id).values(user_id=new_id))
            await session.execute(update(FeedbackRecord).where(FeedbackRecord.user_id == old_id).values(user_id=new_id))
            user = await session.get(UserRecord, old_id)
            if user is not None:
                await session.delete(user)
    await store.close()
    return {**report, "status": "applied", "backup_path": str(backup_path), "applied_at": datetime.now(UTC).isoformat()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", type=Path, required=True, help="External legacy-owner mapping JSON")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--backup", type=Path, default=None)
    parser.add_argument("--apply", action="store_true", help="Apply after audit; default is dry run")
    args = parser.parse_args()
    settings = get_settings()
    database_url = args.database_url or _database_url()
    mapping = _mapping(args.mapping)
    if args.apply:
        backup = args.backup or settings.auth_migration_backup_path
        report = asyncio.run(apply(database_url, mapping, backup))
    else:
        report = asyncio.run(audit(database_url, mapping))
        report["mode"] = "dry-run"
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
