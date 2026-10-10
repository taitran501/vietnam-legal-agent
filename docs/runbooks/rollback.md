# Release Rollback

Rollback is designed to preserve the previous corpus and answer history while
returning the legal index alias and application code to a known-good release.

## Application Rollback

Redeploy the previous verified backend/frontend commit. Do not run a new schema
destructive migration during rollback. If the failed release added only
backward-compatible columns, keep the database at the current Alembic head;
otherwise follow the database backup procedure and obtain an explicit database
owner decision before restoring.

## Corpus Rollback

Redeploy the previous application release and restore its matching,
content-locked SQLite corpus artifact from the approved backup. Verify the
manifest hash, schema, row count, and source metadata before restarting the
backend. Preserve the current and previous artifacts until the rollback is
verified.

After the switch:

```powershell
Invoke-RestMethod http://127.0.0.1/api/v1/ready
```

Confirm that the response reports the expected corpus metadata, then run
ordinary legal lookups from more than one domain and verify their source links.

## Data Rollback

For a failed SQLite migration, stop the application and restore the pre-
migration backup only after confirming the exact database path. For PostgreSQL,
use the approved backup/PITR procedure; do not issue an ad-hoc `DROP` or
`TRUNCATE` from a release shell. Preserve the failed migration report, trace
ID, corpus hash, and readiness payload for diagnosis.
