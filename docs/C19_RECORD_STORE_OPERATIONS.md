# C19 Record Store Operations

This runbook operates the shared Stage 3–6 C19 Record runtime: chat records,
receipts/events and Moments content/interactions. Image/file bytes remain in the
independent Asset Service and are not placed in this database. Voice and video
remain outside the implemented scope.

Stage 6 adds a private service-token `GET /v1/ops/snapshot`, an exact batch
unread-summary contract and the default-dry-run
`scripts/c19_record_retention.py`. Full-system coordination is documented in
`docs/C19_FULL_SYSTEM_OPERATIONS.md`; it does not replace this component's
atomic restore and rollback gates.

The current compatible Record schema is `c19_record_20260712_04`. It adds the
per-asset coordination fence, durable Asset-deletion outbox, stable retention
operation ledger and exact batch replay ledger. Barong's provider boundary uses
the same v4 batch request/response; the removed pre-v4 retention command is not
an advertised capability.

## Deployment boundary

| Component | Authority | Current-VPS placement | Migration unit |
| --- | --- | --- | --- |
| Barong PostgreSQL | C19 profiles, affiliations, social state, conversations, memberships, and settings | Existing Console stack | Existing Barong procedure |
| C19 Record Service | Private message/receipt/event HTTP contract | Independent container; no host port | Same service image/source plus target-owned configuration |
| C19 Record PostgreSQL | Message and Moment bodies, order, audience snapshots, idempotency/tombstones, receipts, interactions and event cursors | Independent PostgreSQL 17 container, database, and named volume | PostgreSQL custom-format archive plus metadata |
| C19 assets | Chat image/file and Moment-image bytes plus lifecycle metadata | Independent Asset stack; never this database | Stage 4/5 asset-VPS procedure |

The record database is attached only to the internal `c19-record-private`
network. The service joins that network and one external client network shared
with the Barong backend. Neither PostgreSQL nor service port 8090 is published
on the host.

`C19_RECORD_DATASET_ID` is the stable identity of one logical C19 record dataset. Keep
it unchanged when moving that dataset to another volume or VPS. A rehearsal may
restore the same dataset only on fully isolated private and client networks; it
must never become a second production writer. Compose also writes this identity
as a label on the named PostgreSQL volume; backup and restore refuse a volume
whose label does not match the protected env file.

## First deployment on the current VPS

1. Create the runtime file from `.env.c19-record.production.example`, set mode
   `0600`, and replace every `CHANGE-ME` value. Use three independent random
   values: the PostgreSQL password, service token, and cursor-signing secret.
   Use the same URL-safe PostgreSQL password in `POSTGRES_PASSWORD` and inside
   `C19_RECORD_DATABASE_URL`; the other two secrets remain independent. The
   service token must be at least 32 characters. Never commit or print this
   file.

   Keep `C19_RECORD_DATASET_ID=barong-c19-production` for this logical production
   dataset. Rotation of passwords or service credentials does not change the
   dataset ID.

2. Create or verify the external client network before Compose starts. The
   default production name is the existing Console network:

   ```bash
   docker network inspect barong-ops-console-prod >/dev/null 2>&1 || \
     docker network create barong-ops-console-prod
   ```

   A differently named target must set `BARONG_SHARED_NETWORK_NAME` consistently
   for both validation and execution. PostgreSQL never joins this network.

3. Validate the independent Compose model without printing resolved secrets,
   build the service, and start the stack. These examples use the Compose v2
   spelling; use `docker-compose` on a host that exposes only the v1 binary.
   The backup and restore scripts detect either form automatically.

   ```bash
   docker compose --env-file .env.c19-record.production -p c19-record -f docker-compose.c19-record.yml config -q
   docker compose --env-file .env.c19-record.production -p c19-record -f docker-compose.c19-record.yml build c19-record-service
   docker compose --env-file .env.c19-record.production -p c19-record -f docker-compose.c19-record.yml up -d
   docker compose --env-file .env.c19-record.production -p c19-record -f docker-compose.c19-record.yml ps
   ```

   The service applies its own Alembic migration before listening. Its health
   check is internal to the container. Do not publish 5432 or 8090 as part of
   this deployment.

4. Put only the Barong client settings in the protected `.env.production` file:

   ```dotenv
   C19_RECORD_STORE_URL=http://c19-record-service:8090
   C19_RECORD_STORE_TOKEN=<same value as C19_RECORD_SERVICE_TOKEN>
   C19_RECORD_STORE_TIMEOUT_SECONDS=5
   C19_RECORD_EVENT_POLL_SECONDS=1
   C19_EVENT_STREAM_LIFETIME_SECONDS=20
   ```

   The record-service token belongs only in the Barong backend and Record
   Service processes. Recreate only `console_backend` so it receives this
   binding; do not recreate or copy the main PostgreSQL volume.

5. Review and merge the exact C19 locations from
   `deploy/nginx/ops.barongyekhna.com.conf.template` into the actual HTTPS vhost:

   - `/api/backend/c19/events` must have proxy buffering/cache disabled and a
     bounded read timeout so SSE pages reach the browser immediately;
   - `/api/backend/c19/moments/events` applies the same rule to the separate
     content-free Moment event cursor;
   - the exact C19 message-send location must keep `client_max_body_size 16k`.

   The file is a template, not an instruction to overwrite the live vhost. Keep
   all unrelated production locations and real certificate paths. Run
   `nginx -t` against the rendered live configuration before reloading Nginx.

6. Verify with authorized users: durable chat send, identical idempotent retry,
   history after restart, delivery/read state, Moment publish/feed/interaction/
   deletion, current audience revocation, both SSE streams and HTTP cursor
   recovery. Every success must be retrievable from the authoritative service.

Never run Compose `down -v` against this stack. The `-v` option destroys the
authoritative record volume.

## Retention and Asset outbox dispatch

The v4 retention request is one exact, resumable batch: stable
`rtn_<64hex>` operation ID, batch ordinal, two approved hard totals, bounded
batch size, policy identity and cutoff. Its response echoes the operation and
ordinal plus batch/cumulative counts and `operation_complete`; Barong rejects
extra keys, mismatched identity or counts outside the approved bounds.

Deleting a record with an attachment durably creates an outbox row before the
record transaction commits. The operator runner's dispatch pass intentionally
claims all currently eligible outbox rows, including explicit-delete rows with
no retention operation, older retention operations and shared-reference rows
that became eligible later. `--maximum-asset-jobs` caps jobs that the current
stable policy may enqueue; the separate `--maximum-dispatch-jobs` caps this
process's cross-operation drain and is included in the printed confirmation
hash. Reaching it exits incomplete with code `2` before another Record batch.

Each eligible job follows durable prepare, Record re-authorization, Asset
commit and Record acknowledgement phases. Shared chat/Moment references remain
blocked, a lost response resumes from persisted state, and neither a lease nor
a protected disposition is treated as successful byte deletion.

## Backup

Create a private PostgreSQL custom-format archive and its metadata together:

```bash
./scripts/c19_record_backup.sh
```

For a non-default stack, pass the same deployment identity used by Compose:

```bash
C19_RECORD_ENV_FILE=.env.c19-record.production \
C19_RECORD_COMPOSE_PROJECT=c19-record \
C19_RECORD_VOLUME_NAME=c19_record_postgres_data \
C19_RECORD_BACKUP_DIR=backups/c19-record \
  ./scripts/c19_record_backup.sh
```

Backup fails closed unless the live source is exactly revision
`c19_record_20260712_04` and contains `record_asset_coordination`,
`record_asset_deletion_outbox`, `record_retention_operations` and
`record_retention_batches`. This prevents a nominally successful archive from
omitting the resumability and Record-to-Asset handoff state. The component
backup itself queries the live source catalog for every v4 column, validated
primary/foreign/unique constraint, hard-cap/counter and outbox state/lease/
completion check, and all six ready/valid operational indexes. Both foreign
keys must bind the correct child column to
`record_retention_operations.operation_id` with `ON DELETE RESTRICT`.

Coordinated backup repeats that catalog gate against its frozen source and also
inspects the archived schema for all required names. Before sealing, all v4 columns must exist,
constraints must be validated with the expected table/type, both foreign keys
must bind the correct child column to
`record_retention_operations.operation_id` with `ON DELETE RESTRICT`, and every
required index must be ready and valid.

The `.dump.metadata` companion records:

- `source_dataset_id`;
- the authoritative Alembic revision;
- `format=pg_dump_custom`;
- the archive SHA-256.

Treat the `.dump` and `.dump.metadata` files as one indivisible backup. Both are
private chat-and-Moment material, excluded from Git and ordinary Docker build contexts.
Copy them to approved encrypted off-host storage over an authenticated channel;
a same-disk archive is not disaster recovery.

## Restore and isolated rehearsal

Restore is dry-run by default. The non-mutating pass validates the
archive/metadata checksum, exact `c19_record_20260712_04` revision, dataset identity, target environment,
database URL identity, project, volume, and both network names without starting
a container or changing a database. During execution, the script starts only
target PostgreSQL and validates the archive's required tables before creating
the temporary restore database:

```bash
./scripts/c19_record_restore.sh \
  --archive backups/c19-record/c19_records_YYYYMMDDTHHMMSSZ.dump
```

The target `C19_RECORD_DATASET_ID` must exactly match the archive
`source_dataset_id`. The dry run prints a `required_confirmation` value with
this complete identity:

```text
<dataset-id>/<archive-sha256>/<project>/<target-db>/<volume>/<private-network>/<client-network>
```

Copy that exact value from the reviewed dry-run output; do not reconstruct or
shorten it. Then execute with the same target variables:

```bash
CONFIRM_C19_RECORD_RESTORE='<exact required_confirmation from dry run>' \
  ./scripts/c19_record_restore.sh \
  --archive backups/c19-record/c19_records_YYYYMMDDTHHMMSSZ.dump \
  --execute
```

Execution performs these steps:

1. locks the confirmed named volume; verifies its dataset label, actual mount,
   existing-container identity, and running DB/user/dataset identity; then
   starts only target PostgreSQL and checks readiness;
2. validates the archive list and restores into a new temporary database;
3. verifies the Alembic revision, chat idempotency/asset-reference columns,
   complete Moment schema, all v4 coordination/outbox/operation/batch tables
   and safety columns, every required validated constraint with its expected
   PostgreSQL table/type, both exact foreign-key endpoints/deletion behavior,
   and every required ready/valid operational index;
4. stops only a running Record Service, then creates a pre-restore logical
   backup when the target already contains the record schema;
5. atomically renames the old target database to
   `c19_rollback_<UTC timestamp>` and the validated database to the configured
   target name;
6. starts and health-checks the Record Service. A start/health failure triggers
   an automatic database rollback;
7. prints the retained rollback database name and restored revision.

The script never runs Compose `down` and never deletes the rollback database.
Before the atomic swap, a validation or restore failure force-drops only the
exact generated `c19_restore_*` temporary database. After a committed swap, an
ordinary command failure or handled termination attempts the same database
rollback; if the commit result cannot be proven or reversed, the service stays
stopped and the command requires manual recovery instead of guessing.

For a disposable rehearsal, create the external client network first and
isolate the env file, Compose project, volume, private network, and client
network together. Never attach a rehearsal service to
`barong-ops-console-prod`, because the shared service alias could receive
production traffic:

```bash
docker network inspect c19-record-rehearsal-client >/dev/null 2>&1 || \
  docker network create c19-record-rehearsal-client

C19_RECORD_ENV_FILE=.env.c19-record.rehearsal \
C19_RECORD_COMPOSE_PROJECT=c19-record-rehearsal \
C19_RECORD_VOLUME_NAME=c19_record_rehearsal_data \
C19_RECORD_PRIVATE_NETWORK_NAME=c19-record-rehearsal-private \
BARONG_SHARED_NETWORK_NAME=c19-record-rehearsal-client \
  ./scripts/c19_record_restore.sh --archive backup.dump
```

Review its output, then repeat the command with
`CONFIRM_C19_RECORD_RESTORE='<exact required_confirmation>'` and `--execute`.

## Post-restore verification and rollback-database lifecycle

Before accepting a restore or migration, verify:

- Record Service health and the expected Alembic revision;
- the last known conversation and user-event sequences;
- bounded old-history reads and unread/receipt positions;
- identical replay of a known idempotency key and rejection of a conflicting
  intent;
- a new send plus SSE and HTTP recovery;
- the same checks again after restarting only the Record Service.

Record the printed `rollback_database` name and an explicit rollback-window end
in the change record. Keep that database until all of the following are true:

- application-level verification has passed after restart;
- Barong has remained bound to the restored dataset for the agreed observation
  window;
- the pre-restore/final archive and metadata are verified in encrypted off-host
  storage;
- the rollback-window owner has approved cleanup.

If application verification fails during the window, stop the Record Service,
terminate connections to only the active and printed rollback databases, and
perform one reviewed PostgreSQL transaction modeled on the restore script:

```sql
BEGIN;
ALTER DATABASE c19_chat_records RENAME TO c19_failed_<UTC_timestamp>;
ALTER DATABASE c19_rollback_<printed_timestamp> RENAME TO c19_chat_records;
COMMIT;
```

Restart and reverify the Record Service before reopening writes. Replace every
placeholder with the exact validated database name; never select a rollback
database by wildcard.

After the rollback window, list the retained database names, verify the active
dataset one final time, and drop only the exact approved rollback database:

```sql
SELECT datname FROM pg_database
WHERE datname LIKE 'c19\_rollback\_%' ESCAPE '\';
DROP DATABASE c19_rollback_<approved_timestamp>;
```

Retain the encrypted logical backups according to the backup policy even after
the temporary rollback database is removed.

## Move the record dataset to another VPS

1. Declare a C19 record maintenance window and fail-close new sends by removing
   the Barong record-store binding and recreating only the backend. This prevents
   writes after the final archive begins.
2. Run a final backup. Transfer both archive and metadata over an encrypted,
   authenticated channel and independently verify the SHA-256 on the target.
   After the final backup succeeds, stop the source VPS
   `c19-record-service` and verify it is not running. Keep its PostgreSQL
   container and named volume intact; do not run `down -v`. The source service
   may be started again only as part of an explicit rollback.
3. On the target VPS, create a protected target env file with the same
   `C19_RECORD_DATASET_ID`, target-owned PostgreSQL/service/cursor secrets, a new
   named volume, and isolated private/client networks. Create the external
   client network before invoking Compose or restore.
4. Build the same Record Service image/source. Run restore dry-run, compare the
   dataset ID and archive SHA in `required_confirmation`, then execute the
   restore against the fresh target.
5. Perform the complete post-restore and post-restart verification above before
   routing Barong to the target. Confirm once more that the source Record
   Service remains stopped so only one writer can own the dataset.
6. Expose only the Record Service to Barong through private networking or HTTPS
   with service/IP identity controls. PostgreSQL remains private. Change
   `C19_RECORD_STORE_URL` and, if rotated, the matching token; recreate only the
   Barong backend.
7. Reverify tail sequence, old history, a new send, idempotent replay,
   delivery/read/unread state, SSE reconnect, and HTTP recovery through Barong.
8. Keep the source service stopped and retain its PostgreSQL volume, plus the
   target `c19_rollback_*` database, through the recorded rollback window.
   Remove either only after migration acceptance, off-host backup verification,
   and retention approval. If rollback is approved, first fail-close Barong on
   the target, stop the target service, then explicitly restart and rebind the
   source; never leave both services writable.

The API and Barong schema do not change during this move. The portable unit is
the independently versioned Record Service plus a logical PostgreSQL archive,
not a raw Docker-volume copy; this avoids coupling migration to filesystem
layout or exact container internals.

## PostgreSQL 17 rehearsal evidence

The Stage 3 procedure was exercised on `2026-07-11` using isolated source and
fresh-target PostgreSQL 17 stacks. The source exposed 25 visible records with
latest sequence 26. Backup metadata bound the logical dataset, Alembic revision,
custom archive format, and SHA-256. Restore validated the archive into a
temporary database, performed the atomic swap, reached service health, retained
the rollback database, and reproduced the same record/event/idempotency state
after restarting the Record Service. Repeating the restore against that
populated target created a pre-restore archive whose recorded SHA-256 matched
the archive bytes before the swap. A separate fault-injection stack made the
Record Service exit only after the database swap; the restore command failed
closed, atomically restored the original target database, and retained the
restored dataset under `c19_failed_*` for diagnosis. These paths were rerun with
the final scripts on dataset-labelled volumes, with the env, existing container,
actual mount, and volume label all agreeing. A deliberate Alembic revision
mismatch stopped before swap and left no `c19_restore_*` database behind.
