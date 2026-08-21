# Release Rollback

Rollback is designed to preserve the previous corpus and answer history while
returning the legal index alias and application code to a known-good release.

## Application Rollback

Redeploy the previous verified backend/frontend commit. Do not run a new schema
destructive migration during rollback. If the failed release added only
backward-compatible columns, keep the database at the current Alembic head;
otherwise follow the database backup procedure and obtain an explicit database
owner decision before restoring.

## Qdrant Alias Rollback

Use the `rollback_collection` captured by `ensure_law_index` and perform one
atomic alias update from `law_collection` to that retained immutable collection
through the approved Qdrant operations job. Verify the target's corpus hash,
index schema, embedding profile, point count, and citation metadata before the
switch. Never delete the current or previous collection as part of the alias
rollback.

After the switch:

```powershell
Invoke-RestMethod http://127.0.0.1/api/v1/ready
```

Confirm that the response reports the expected corpus and collection metadata,
then run a legal lookup and source deep-link smoke test.

## Data Rollback

For a failed SQLite migration, stop the application and restore the pre-
migration backup only after confirming the exact database path. For PostgreSQL,
use the approved backup/PITR procedure; do not issue an ad-hoc `DROP` or
`TRUNCATE` from a release shell. Preserve the failed migration report, trace
ID, corpus hash, and readiness payload for diagnosis.
