# Database Migration and Ownership Recovery

All migrations are dry-run-first. Take a recoverable backup, inspect the
report, and only then apply the change.

## Legacy SQLite History

Audit the database without changing it:

```powershell
python -m scripts.migrate_legacy_sqlite --database .\data\history.db
```

The audit detects epoch/`REAL` timestamps, `metadata_json`, `short_summary`,
previous current schemas, malformed JSON, orphan rows, foreign-key failures,
row-count changes, and owner collisions. Apply only after the report has no
issues:

```powershell
New-Item -ItemType Directory -Force .\backups | Out-Null
python -m scripts.migrate_legacy_sqlite `
  --database .\data\history.db `
  --backup .\backups\history-pre-migration.sqlite `
  --apply
```

The command uses SQLite's online backup API, builds and validates the current
schema in a sibling file, stamps the Alembic head, and swaps transactionally.
Running the command again is idempotent. Keep the backup until the application
has passed history, feedback, case, and reload checks.

## PostgreSQL Startup

Production startup must run the Alembic head before serving requests. A schema
mismatch is a readiness failure (`database_schema_mismatch`), not a reason to
call `create_all()` against an existing database. Run the migration explicitly
from the deployment job:

```powershell
alembic upgrade head
```

`create_all()` remains suitable only for a brand-new test database.

## Legacy Owner Hashes

Prepare an external mapping file; do not commit it:

```json
{
  "legacy:<owner-hash>": {
    "issuer": "https://sso.example",
    "subject": "stable-oidc-sub"
  }
}
```

Audit first:

```powershell
python -m scripts.migrate_owners --mapping .\owner-mapping.json --database-url $env:DATABASE_URL
```

The report lists mapped owners, collisions, and owners that will be quarantined
and therefore invisible to OIDC users. Resolve every collision before apply:

```powershell
python -m scripts.migrate_owners `
  --mapping .\owner-mapping.json `
  --database-url $env:DATABASE_URL `
  --backup .\backups\owners-pre-migration.bak `
  --apply
```

The operation moves conversations, cases, runs, and feedback in one
transaction. It does not persist access tokens, and it never guesses an
identity for an unmapped legacy owner.

## Recovery

If validation fails, stop the deployment, retain the backup, restore it using
the database-specific recovery procedure, and rerun the dry-run audit. Record
the migration report and database revision with the release artifact.
