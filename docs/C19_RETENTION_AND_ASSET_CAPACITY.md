# C19 coordinated retention and asset capacity

Status: Stage 6 implemented; production execution remains an explicit operator action.

## Safety invariants

- Chat/Moment bodies and filenames never enter retention logs or the Record outbox.
- A Record retention policy has a stable `rtn_<sha256>` operation ID. The
  policy hash covers actor, reason, cutoff, conversation scope, the approved
  Record total, and the approved newly-enqueued asset-job total. `requested_at`
  and transport retries are not identity.
- Every Record batch has a durable ordinal and exact stored response, including
  `operation_complete`. A lost response replays the same result and never
  selects another batch.
- `approved_maximum_records` and `approved_maximum_asset_jobs` are hard,
  durable totals enforced by Record, not counters trusted to the CLI.
- Every removed asset reference creates a content-free outbox row. A permanent
  per-asset coordination row is locked by chat append, Moment publish, Record
  deletion, claim, and authorization. All writers re-check the outbox after
  acquiring that fence.
- An outbox job is ineligible while any surviving chat or Moment reference uses
  the asset ID. Historical jobs remain durable so a shared-reference anomaly
  can be resolved when the final live reference disappears.

## Two-phase deletion

The coordinator performs these durable transitions:

1. Record leases an eligible `pending` job.
2. Asset `prepare` verifies the exact immutable tuple `(asset_id, chat usage,
   conversation_id, committed record_id)` and stores the per-asset outbox job
   UUID. Prepare does **not** change the asset lifecycle status and the byte
   worker cannot consume it.
3. Record locks the permanent asset fence and checks both reference tables
   again. A new/surviving reference returns `blocked`; otherwise the job becomes
   `authorized`.
4. Asset `commit` accepts only the exact prior preparation and changes the
   lifecycle to `delete_pending`. This is the byte worker's durable queue.
5. Record acknowledges the job as `completed`. An authoritative scope mismatch
   at prepare is acknowledged as `protected`, never deleted.

Crash recovery is phase-aware. An expired `authorized` lease is reclaimed with
`phase=commit`, so a crash or lost response after Record authorization never
strands the job and never repeats the destructive authorization decision.
Asset prepare/commit and Record authorize/complete are idempotent.

## Operator scope and confirmation

`scripts/c19_record_retention.py` is network-free by default. Its printed plan
and confirmation digest explicitly include:

- protocol `record-asset-retention-v2-two-phase`;
- Record and Asset origins;
- Record conversation scope and cutoff;
- durable Record and new-asset-job maxima;
- per-process `maximum_dispatch_jobs`; and
- asset dispatch scope `all-eligible-record-outbox`.

The dispatch scope is intentionally broader than the conversation filter: each
run may drain eligible explicit-delete jobs, jobs from older retention
operations, and jobs that were previously blocked by a shared reference. This
prevents `retention_operation_id = NULL` explicit deletions from leaking bytes.
Dispatch is bounded per process; reaching that bound stops before another
Record batch and exits incomplete so the same confirmed command can resume.

Execution requires separate 0600 Record and Asset token files and refuses equal
tokens. The runner opens tokens once with `O_NOFOLLOW`, validates a bounded
single whitespace-free/control-free line, disables environment proxies, and
refuses redirects. Plain HTTP is allowed only for loopback/RFC1918/IPv6 ULA,
single-label service DNS, or the private suffixes `.localhost`, `.internal`,
`.local`, `.svc`, and `.svc.cluster.local`. Public HTTPS requires the explicit
`--allow-public-https` flag, which changes the confirmation digest.
Link-local, unspecified, multicast, and reserved IP destinations are rejected.

## Durable capacity quotas

Every new upload intent locks `asset_dataset_identity` with `FOR UPDATE` before
locking/re-checking the idempotency row and calculating quota. Production
PostgreSQL therefore serializes new reservations across API workers.

Portable defaults (all configurable):

- per owner: 2,000 non-deleted assets and 2 GiB reserved bytes;
- global dataset: 100,000 non-deleted assets and 50 GiB reserved bytes;
- generated thumbnail maximum/reservation: 2 MiB per image.

Reserved bytes are `actual_size_bytes` when known, otherwise declared bytes,
plus the actual thumbnail size. An image without a thumbnail reserves the full
configured thumbnail maximum. The worker enforces the same thumbnail byte hard
limit before activation, so background generation cannot cross the quota.
Pending, active, rejected, quarantined, expired, and `delete_pending` rows all
retain capacity; only the permanent body-free `deleted` tombstone releases it.
Reopening an expired intent uses the same dataset lock and re-checks the
per-owner pending-upload cap.

Configuration keys:

- `C19_ASSET_OWNER_RESERVED_FILE_LIMIT`
- `C19_ASSET_OWNER_RESERVED_BYTE_LIMIT`
- `C19_ASSET_GLOBAL_RESERVED_FILE_LIMIT`
- `C19_ASSET_GLOBAL_RESERVED_BYTE_LIMIT`
- `C19_ASSET_THUMBNAIL_MAX_BYTES`

## Content-free observability

Record `/v1/ops/snapshot` separates pending, authorized, blocked, leased,
completed, and protected asset-deletion counts and reports the oldest pending
and authorized ages. Active leases cover both pending prepare and authorized
commit phases. Asset `/v1/ops/snapshot` reports preparations that have not reached
`delete_pending` plus their oldest age; committed `delete_pending` work remains
visible through the existing lifecycle count/age instead of being double-counted.
It also reports reserved file/byte totals using the exact quota expression, and
active object bytes include both originals and thumbnails.

No endpoint returns chat content, filename, asset ID, record ID, object key, or
token in operational telemetry.
