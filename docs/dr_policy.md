# Disaster Recovery Policy

Scope: Barong Ops Console production operations layer. This policy covers the
FastAPI/Next application containers, PostgreSQL data, C17 observability data,
and ops alert tables. It does not change C19, the C08-C15 execution engine,
the UI, or the permission system.

## Objectives

- RPO: 15 minutes for PostgreSQL data when scheduled backups run every 15
  minutes; 0 minutes for completed release metadata because rollback tags and
  backup metadata are generated before production changes.
- RTO, DB crash: 30 minutes for restore from the latest validated pg_dump
  archive.
- RTO, server crash: 45 minutes to rebuild host services from Docker Compose,
  restore volumes if needed, and pass smoke checks.
- RTO, region loss: 4 hours to provision a clean host in a replacement region,
  restore the latest off-region backup, and reroute traffic.

## Required Assets

- PostgreSQL backups produced by `scripts/pg_backup.sh`.
- Backup sidecar metadata with `app_version` and `alembic_revision`.
- Application rollback images tagged by `scripts/safe_compose_release.sh` as
  `rollback-YYYYmmddHHMMSS`.
- Recovery scripts:
  - `scripts/pg_restore_db.sh`
  - `scripts/db_rollback.sh`
  - `scripts/rollback_release.sh`
  - `scripts/check_release_consistency.py`
- C17 alerting records in `ops_alerts` and sink delivery records in
  `ops_alert_deliveries`.

## Failure Scenarios

### DB Crash

Detection:
- PostgreSQL health check fails.
- Backend `/health` reports database unavailable or times out.
- C17 alert engine emits DB-adjacent error spike, latency spike, or DLQ growth.

Recovery:
1. Stop application writes by removing only backend/frontend containers or
   blocking ingress at the edge.
2. Select the newest validated archive in `BARONG_BACKUP_DIR`.
3. Run `scripts/pg_restore_db.sh --latest --database-url TARGET --dry-run`.
4. Confirm the dry-run shows schema validation and migration revision checks.
5. Execute restore with `CONFIRM_DB_RESTORE=yes`.
6. Run `scripts/check_release_consistency.py` with the expected app version and
   schema revision.
7. Restart application service with `scripts/rollback_release.sh` only if the
   current application image is incompatible with the restored schema.
8. Run production smoke check and inspect `ops_alerts` for unresolved criticals.

### Server Crash

Detection:
- Host is unreachable.
- Docker daemon or service containers are down.
- External health checks fail.

Recovery:
1. Provision a replacement host with the same Compose files and environment
   variables.
2. Restore Docker volume data if the volume is intact; otherwise restore the
   latest PostgreSQL archive with `scripts/pg_restore_db.sh`.
3. Recreate services with the existing production Compose project name.
4. If the failed deployment caused the crash, restore the latest rollback image
   with `scripts/rollback_release.sh`.
5. Run `scripts/check_release_consistency.py`.
6. Run `scripts/production_smoke_check.sh`.
7. Keep the failed host isolated until logs and C17 records are exported.

### Region Loss

Detection:
- Region-wide network, compute, or storage outage.
- Production DNS/edge checks fail from multiple probes.

Recovery:
1. Declare region loss after two independent checks confirm the outage.
2. Provision a clean host in the replacement region.
3. Pull the last approved application image or restore the latest rollback tag
   from the image registry.
4. Restore the newest off-region PostgreSQL backup with
   `scripts/pg_restore_db.sh`.
5. Run Alembic and release consistency checks.
6. Start backend/frontend containers and run smoke checks.
7. Move DNS/edge traffic only after DB restore, app health, schema consistency,
   and C17 alert checks pass.
8. Keep the old region read-only until data divergence is assessed.

## Rollback Rules

- Application rollback restores a previous Docker image and recreates only the
  target service.
- DB rollback uses the latest validated backup first. Alembic downgrade is
  allowed only when the downgrade path was validated in an isolated database.
- Every rollback ends with app/schema consistency validation.
- A rollback that fails consistency checks must not receive production traffic.

## Validation

- DB failure recovery simulation: `scripts/simulate_pre20_o_dr.sh`.
- Backup restore simulation: `scripts/pg_restore_db.sh --validate-only` with a
  `pg_restore --list` file and sidecar metadata.
- Rollback simulation: `scripts/rollback_release.sh --dry-run` and
  `scripts/db_rollback.sh --dry-run`.
- Alert trigger simulation: backend tests covering C17 event streams,
  anomaly generation, alert creation, webhook/log/dashboard sink delivery, and
  persisted ops alert records.
