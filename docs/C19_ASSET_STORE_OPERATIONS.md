# C19 Asset Store Operations

This runbook covers the isolated Stage 4–6 asset dataset shared by chat
images/files and Moment images. It does not enable C19 assets in production,
install an Nginx template, or connect a future VPS.

Stage 6 adds the private service-token `GET /v1/ops/snapshot`, whose response is
limited to aggregate state/usage counts, object bytes, ticket/audit counts and
backlog ages. The coordinated Barong + Record + Asset bundle and restore
admission gate are documented in `docs/C19_FULL_SYSTEM_OPERATIONS.md`.

The current compatible Asset schema is `c19_asset_20260712_03`. Its
non-destructive retention fence adds `retention_operation_id`,
`retention_record_id`, `retention_conversation_id` and
`retention_prepared_at` as one all-null or all-present group, with a unique
operation ID and prepared-at index. These fields are coordination metadata, not
permission or organization gates.

Stage 5 tags every internal row and ticket with
`usage=chat_message|moment_image` and a provider-neutral `scope_id`. Existing
chat v1 wire remains exact; Moment images use the server-reserved Moment ID as
both scope and committed resource. Backup/restore manifests are generic and
must include active objects for both usages.

## Dataset and secrets

`C19_ASSET_DATASET_ID` is the stable identity of one logical asset dataset. Keep
it unchanged when the same metadata and objects move to another volume or VPS.
Passwords and service tokens rotate independently and do not change this ID.

Copy `.env.c19-asset.production.example` to the runtime-only
`.env.c19-asset.production`, replace every placeholder and set mode `0600`.
Never reuse the Record Service token, Barong session secret or PostgreSQL
password. Only Barong gets `C19_ASSET_STORE_URL` and
`C19_ASSET_STORE_TOKEN`; the browser and Next.js get neither.

The runtime env file and `backups/c19-asset/` are ignored by Git and Docker build
contexts. Do not print a rendered Compose configuration from a real env file,
because Docker Compose expands secrets into its output.

## Isolated deployment

The stack expects the already-created external Barong client network only when
the API is intentionally connected for integration. Rehearsals must override
all network names so they cannot reach production:

```bash
export C19_ASSET_ENV_FILE=/absolute/path/to/rehearsal.env
export C19_ASSET_DATASET_ID=barong-c19-assets-rehearsal
export C19_ASSET_PRIVATE_NETWORK_NAME=c19-asset-rehearsal-private
export C19_ASSET_CLAM_EGRESS_NETWORK_NAME=c19-asset-rehearsal-clam-egress
export C19_ASSET_GATEWAY_INGRESS_NETWORK_NAME=c19-asset-rehearsal-gateway-ingress
export BARONG_SHARED_NETWORK_NAME=c19-asset-rehearsal-client
export C19_ASSET_POSTGRES_VOLUME_NAME=c19_asset_rehearsal_postgres
export C19_ASSET_INCOMING_VOLUME_NAME=c19_asset_rehearsal_incoming
export C19_ASSET_QUARANTINE_VOLUME_NAME=c19_asset_rehearsal_quarantine
export C19_ASSET_ACTIVE_VOLUME_NAME=c19_asset_rehearsal_active
export C19_ASSET_CLAM_VOLUME_NAME=c19_asset_rehearsal_clam
export C19_ASSET_GATEWAY_HOST_PORT=18092
```

Create the isolated client network before starting the stack. Do not use the
production network name for a rehearsal. Validate Compose without starting it:

```bash
docker-compose -p c19-asset-rehearsal \
  -f docker-compose.c19-asset.yml config --services
```

The private runtime network remains `internal: true`. Docker does not create a
host-published port for a container attached only to an internal network, so the
gateway alone also joins a dedicated single-purpose ingress bridge. That bridge
disables IP masquerading and the only published listener is explicitly bound to
`127.0.0.1`; no other C19 role may join it. Give each rehearsal a unique
`C19_ASSET_GATEWAY_INGRESS_NETWORK_NAME` and verify that the loopback health
endpoint is reachable before configuring Nginx.

Only `c19-asset-clamd`
also joins the separately named ClamAV update-egress network so FreshClam can
refresh signatures before the 48-hour freshness gate closes. That network must
contain no other C19 service, and port 3310 must remain unpublished. Give every
rehearsal its own egress-network name; inspect rendered service membership
without printing a real secret-bearing `docker-compose config` document.

ClamAV has Compose-v1 host limits `mem_limit: 4g` and `pids_limit: 128`, plus
bounded JSON log rotation. The memory value follows the official container
guidance ([ClamAV Docker documentation](https://docs.clamav.net/manual/Installing/Docker.html));
it is a ceiling, not reserved capacity. Before a same-host rehearsal, inspect
host/container memory and disk pressure and do not start ClamAV unless the
existing production workload can retain its operating reserve.

Build and migrate before starting writers. Health means only that the process
and its required dependency are reachable; it does not mean production is
enabled. Scanner failure or stale/unavailable signatures keep uploads out of
`active`.

## Volume roles

- metadata PostgreSQL volume: authoritative asset state, tickets, bindings,
  idempotency and audits;
- incoming volume: incomplete uploads, excluded from backup;
- quarantine volume: rejected/suspicious bytes, excluded from ordinary backup;
- active volume: authoritative accepted originals and derived safe thumbnails;
- ClamAV signatures: operational cache, rebuilt through official updates.

Every dataset volume is labelled with the dataset ID and a fixed role. A script
must verify both the configured name and actual container mount before reading
or writing it. The gateway has active RO and incoming RW; only the worker has
active RW. The API has no object mount and the gateway has no DB credential.

## Nginx activation review

`deploy/nginx/ops.barongyekhna.com.conf.template` is a template, not an installed
configuration. Before activation:

1. verify the gateway is bound only to loopback or the approved private tunnel;
2. verify the internal auth subrequest reaches Barong directly and forwards the
   current session cookie plus original path/method but no request body; Barong
   must branch the v2 tagged inspection into live conversation or Moment
   authorization;
3. verify `AUTH_SESSION_COOKIE_PATH=/api/backend` remains a prefix of both
   `/api/backend/c19-assets/u/...` and `/api/backend/c19-assets/d/...`;
4. verify the two ticket regex locations are the only public byte routes and
   proxy bytes directly to the gateway, never Next or Barong; malformed new
   paths and legacy `/api/c19-assets/...` paths must return 404 at Nginx;
5. verify upload buffering and ticket-bearing access logs are disabled;
6. verify the 64 MiB Nginx ceiling, gateway streaming counter and intent limit;
7. verify GET, HEAD and a single Range plus 416 behavior;
8. run `nginx -t`, then reload during an approved window.

Do not raise the site's global 10 MiB limit. Do not proxy bytes through Next.js
or Barong. A future VPS cut-over changes only the gateway upstream and private
Asset API URL after source writers have stopped.

## Backup set

One accepted backup is an indivisible set:

- PostgreSQL custom-format dump;
- deterministic active-object tar archive;
- sorted manifest containing relative path, byte size and SHA-256 for every
  active object;
- metadata containing dataset ID, Alembic revision, blob format revision,
  counts, byte totals and SHA-256 for all three files.

Before any backup member is published, the shared consistency gate queries all
non-null `active_object_key` and `thumbnail_object_key` references and compares
their expected size/SHA-256 with every regular file in the active volume. The
sets must be exactly equal: missing bytes, extra/orphan bytes, duplicate keys,
invalid paths and digest/size drift all fail the backup.

The component backup also fails closed unless the source revision is exactly
`c19_asset_20260712_03`, all four retention-prepare columns exist, the
all-null/all-present check and operation-ID unique constraint are validated
with the expected PostgreSQL types, and the prepared-at index is ready and
valid. These catalog checks run before `pg_dump`; a matching revision string
alone is never accepted as schema evidence.

The backup operation first stops the gateway and API, verifies both are down,
then polls a read-only database drain gate while the worker settles every
`uploaded`, `scanning` and `delete_pending` row plus terminal rows that still
hold an incoming/active object. It fails after the bounded drain timeout rather
than taking an ambiguous snapshot. Unconfirmed `pending_upload` rows may remain;
their partial incoming bytes are deliberately not portable and the client must
retry them after cut-over. Once drained, SIGTERM lets the worker finish its
current `run_once` DB/filesystem transition before exiting, and the script
verifies that it is down before creating DB and object snapshots at one
high-water mark. Compose also grants the worker a 180-second stop grace period
for ordinary restarts. The normal mode restarts only the previously running services.
`--leave-stopped` is the final-cutover mode: writers remain stopped after
success, failure or a signal.
Quarantine, incoming bytes and ClamAV signatures are not portable content.
Encrypt the completed set and copy it off the current disk.

Restore clears nonportable quarantine object keys and revokes every surviving
pre-move transfer-ticket hash before activation. Pending upload destination keys
remain so an authenticated client can request a fresh ticket and re-upload the
bytes; no old raw locator is accepted on the target.

The default drain timeout is 600 seconds. An approved operation may set
`C19_ASSET_BACKUP_DRAIN_TIMEOUT_SECONDS` from 30 through 3600; increasing it
does not bypass the zero-blocker requirement.

For a cut-over, first run
`./scripts/c19_asset_backup.sh --dry-run --leave-stopped`, review its distinct
confirmation identity, then repeat with
`--execute --leave-stopped` and the printed confirmation value. Do not reuse a
normal resumable-backup confirmation for this operation.

Never accept only a DB dump or only an object archive. Never edit metadata or
rename one file without regenerating all checksums.

## Restore acceptance

Restore defaults to a non-mutating validation plan. Execution is allowed only
into an isolated project with fresh labelled PostgreSQL, incoming, quarantine
and active volumes. The target dataset ID must match source metadata, while all
target secrets must be target-owned.

Acceptance order:

1. verify all metadata fields and file checksums before starting containers;
2. verify the source archive cannot escape the active root and contains no
   symlink, device, absolute path or duplicate path;
3. restore PostgreSQL into a temporary database and objects into an empty target
   active volume;
4. require exact revision `c19_asset_20260712_03`, then verify the four
   retention-fence columns, consistency constraint, unique operation constraint
   and prepared-at index before any database activation;
5. run the same consistency gate against the temporary restored database and
   active volume, then compare its exact manifest with the source manifest;
6. rename the pristine/temporary databases in one transaction, start only the
   API so current-image migrations and health run, then stop it again; a start,
   health, signal or post-swap failure transactionally restores the pristine DB
   name and leaves the failed database isolated; rerun DB/object consistency
   after migration before accepting the target;
7. retain the source stopped and target isolated for observation;
8. only after explicit approval connect the target API/client network and switch
   the Nginx gateway upstream. Source and target must never accept writes at the
   same time.

If any check fails, stop the target writers and retain the failed isolated
dataset for diagnosis. Do not partially copy files into the source dataset.

## Retention and incident response

- Pending uploads expire independently and release reserved quota.
- The worker TTL deletes only `active + unbound` assets that were never prepared
  for a message. It does not use that TTL for record/commit reconciliation.
  `prepared` may mean Record append succeeded while Asset commit response was
  lost, so it must not be blindly deleted; the authorized exact-record/access
  path repairs the binding with an idempotent commit.
- A deleted record immediately fails exact visibility, so no new download ticket
  can be issued. The same Record transaction persists a body-free deletion
  outbox row; byte deletion is asynchronous and is not claimed complete merely
  because the record disappeared.
- The confirmed retention runner intentionally drains all currently eligible
  outbox work: current/older retention operations, explicit deletes whose
  retention operation is null, and shared-reference jobs that became unblocked.
  `maximum_asset_jobs` is the current stable policy's enqueue cap;
  `maximum_dispatch_jobs` is a separate per-run cross-operation dispatch cap
  bound into the printed confirmation hash.
- A job prepares the exact Asset binding, rechecks all Record/Moment references
  under the coordination fence, durably authorizes the job, commits Asset
  deletion and only then acknowledges its outcome to Record. Crashes and lost
  responses resume at prepare or commit; a surviving shared reference yields
  blocked/protected behavior rather than deleting its bytes.
- Quarantine immediately invalidates all old tickets. Quarantine bytes are not
  exposed to ordinary administrators or included in normal backups.
- Scanner outage, parsing ambiguity or DB/object inconsistency stops new
  activation; it never falls back to a public/local file path. Host monitoring
  must separately alert and close ingress before the configured disk low-water
  threshold is reached.

Record audit IDs and asset audit IDs may be correlated operationally, but logs
must not contain ticket values, object keys, raw filenames, file SHA-256 or file
content.

## Future VPS move

1. Put the C19 asset entry points into maintenance: block new byte routes and
   make Barong's Asset Store client fail closed. Verify no client can create a
   new upload or download intent.
2. Run the final source backup with `--leave-stopped`. Do not reconnect the
   source writers if the backup or transfer fails; correct the problem while the
   entry points remain closed and repeat from the same quiescent source.
3. Deploy the same image/Compose revision on the target with a private TLS or
   VPN path, target-owned secrets and sufficient encrypted storage.
4. Restore the unchanged dataset ID into fresh target volumes and complete the
   isolated acceptance above.
5. Keep source writers stopped; change Barong `C19_ASSET_STORE_URL` and the exact
   Nginx transfer upstream.
6. Before reopening writes, exercise read-only health, existing thumbnail,
   download, Range and revocation checks. This is the simple rollback window:
   stop the target and reconnect the still-frozen source if acceptance fails.
7. Reopen writes and exercise upload, scan, chat-message and Moment bindings,
   thumbnail, download,
   Range, revocation and delete with test accounts.
8. Once the target has accepted any write, the old source is no longer a valid
   direct rollback target. A rollback now means: close entry points, stop target
   writers, take a new target `--leave-stopped` backup, restore and verify it on
   fresh source-side volumes, then switch back. Never run both writers and never
   discard target-era assets that Record Service records may already reference.

Because records contain stable provider-neutral asset IDs and snapshots, no
Barong database rewrite, message rewrite or frontend URL migration is required.
