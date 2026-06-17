# Migration Policy

This policy governs Alembic migrations for the Barong Ops Console backend.

## Required Migration Shape

Every migration file under `backend/alembic/versions/` must define both:

- `upgrade()`
- `downgrade()`

Migrations must be deterministic, reviewable, and scoped to database state. CI/CD,
frontend UI, deployment files, and execution routing are outside migration scope.

## Upgrade Strategy

1. Confirm the database is not production-like unless the rollout is approved.
2. Run `scripts/check_migration_safety.py` against the target database.
3. Require exactly one Alembic script head and exactly one database revision.
4. Block production/staging if the current revision does not match the script head
   expected before a managed rollout.
5. Run `alembic upgrade head` inside a transaction-capable migration process.
6. Run schema consistency, foreign key integrity, and org_id constraint checks.
7. Only start production/staging application processes after the safety check
   reports a clean head match.

## Downgrade Strategy

1. Downgrade only one revision at a time unless an approved incident plan says
   otherwise.
2. Run `alembic downgrade head-1` first in an isolated database with matching data
   shape.
3. Confirm the downgraded schema is internally consistent.
4. If the downgrade drops stateful tables, export or snapshot the affected rows
   before running the downgrade in shared environments.
5. Re-run `scripts/check_migration_safety.py`; production/staging must remain
   blocked while the database revision intentionally differs from application head.

## Restore Strategy

1. Prefer point-in-time database restore when data loss, failed DDL, or partial
   migration side effects are suspected.
2. Restore into an isolated database first and run `alembic current`,
   schema consistency checks, foreign key checks, and application smoke checks.
3. Promote the restored database only after the revision and schema match the
   application version selected for rollback.
4. If a logical restore is used, preserve `alembic_version` with the restored
   schema revision.

## Rollback Decision Tree

1. Did `alembic upgrade head` fail before committing?
   - Stop application rollout.
   - Keep the previous application version.
   - Fix the migration or run `alembic downgrade head-1` only if Alembic advanced.
2. Did the migration commit but schema checks fail?
   - Block production/staging startup.
   - Run `alembic downgrade head-1` if the downgrade has been validated.
   - Otherwise restore from backup.
3. Did application startup fail because of head mismatch?
   - Do not bypass the startup guard.
   - Align the database to application head or deploy the matching application
     version.
4. Was bad data written after upgrade?
   - Stop writes.
   - Prefer point-in-time restore.
   - Use downgrade only when schema rollback is sufficient and data repair is
     already complete.

## Migration Safety Check

The safety check is implemented in `backend/app/db/migration_safety.py` and exposed
by `scripts/check_migration_safety.py`.

It verifies:

- current Alembic script head
- current database revision from `alembic_version`
- dirty state, including missing version table, missing current revision, multiple
  database revisions, or multiple script heads
- production/staging blocking when the current database revision does not match
  the application migration head

FastAPI startup runs the same check in `production`, `prod`, and `staging`.
