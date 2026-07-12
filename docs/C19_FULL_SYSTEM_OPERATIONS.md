# C19 Full-System Operations

Status: Stage 6 implementation and source/isolated acceptance completed,
`2026-07-12`. Production activation is not part of this runbook's recorded
acceptance.

This runbook coordinates the three authoritative C19 data domains without
merging them:

| Domain | Authority | Backup component |
| --- | --- | --- |
| Global profile, optional affiliations, social state, conversation/group membership and settings | Barong PostgreSQL | PostgreSQL custom archive |
| Chat/Moment bodies, audience ceilings, positions, interactions, tombstones, retention/outbox ledgers and content-free events (`c19_record_20260712_04`) | C19 Record PostgreSQL | PostgreSQL custom archive |
| Chat/Moment image/file lifecycle metadata, retention prepare fences and bytes (`c19_asset_20260712_03`) | C19 Asset PostgreSQL plus active object volume | PostgreSQL custom archive, exact object manifest and deterministic tar |

Each domain keeps a distinct dataset identity and schema revision. A coordinated
generation binds all artifacts together; it does not create a second writer or
change any application API.

## Universal access and privacy

C19 is available to every authenticated active Barong user. RBAC permissions,
roles, organizations, organization memberships and affiliations do not grant or
remove the feature. An affiliation is optional descriptive context and is
validated only when explicitly selected.

Conversation membership, group role, bilateral block state, Moment visibility,
session state and exact Asset scope remain mandatory content-privacy controls.
Operational tooling never bypasses those controls to expose content.

## Release gate

Run the complete non-production source gate from the repository root:

```bash
./scripts/c19_release_readiness.sh
```

It runs the Barong C19, Record, Asset, deployment-boundary and frontend suites,
the production frontend build, TypeScript/Foundation checks, Python compilation,
shell syntax and Git whitespace/private-artifact gates. It never activates a
production binding.

## Content-free operational snapshots

Both endpoints are private service-token APIs and return `Cache-Control:
no-store`:

```text
GET <record-origin>/v1/ops/snapshot
GET <asset-origin>/v1/ops/snapshot
Authorization: Bearer <service token>
```

They contain only aggregate lifecycle/usage counts, aggregate bytes, ticket and
audit counts, and oldest backlog ages. They contain no body, comment, filename,
token, object key, user ID, conversation ID, Moment ID or Asset ID. PostgreSQL,
Record API and Asset API remain private infrastructure; do not expose these
origins merely to scrape the snapshots.

## Distributed abuse controls

All C19 mutation routes share database-backed, hashed user/IP buckets. Bounded
SSE reconnects use an independent bucket. Defaults are:

```text
C19_RATE_LIMIT_WINDOW_SECONDS=60
C19_WRITE_USER_RATE_LIMIT_ATTEMPTS=180
C19_WRITE_IP_RATE_LIMIT_ATTEMPTS=1800
C19_STREAM_USER_RATE_LIMIT_ATTEMPTS=30
C19_STREAM_IP_RATE_LIMIT_ATTEMPTS=300
```

The buckets contain hashes, endpoint class, timestamps and counts only. Limits
apply equally to every user and are abuse controls, not permissions. Asset byte
size, pending-upload, ticket-use, parser, malware and decompression quotas remain
separate defense-in-depth limits.

## Record retention runner

Retention is never scheduled with an invented policy. First print a network-free
plan with the approved cutoff, reason and operator identity:

```bash
./scripts/c19_record_retention.py \
  --record-url http://c19-record-service:8090 \
  --asset-url http://c19-asset-api:8091 \
  --requested-by-user-id retention-operator \
  --reason "approved retention policy" \
  --delete-before 2026-01-01T00:00:00Z
```

The default minimum age is 30 days, each batch is at most 1,000 records and one
run is capped at 100,000. Execution additionally requires the printed
`CONFIRM_C19_RECORD_RETENTION` value and a mode-0600 service-token file. The
Record Service clears content and recipient events while retaining permanent
body-free idempotency tombstones and mutation audit. A lost response can be
retried with the same `rtn_<64hex>` operation ID and batch ordinal without
recreating content or exceeding the approved Record/Asset job caps. Asset
deletion uses the durable Record outbox and an exact prepare/commit fence; a
crash or lost response resumes from persisted phase state.

The dispatch phase deliberately scans all eligible outbox work, not only the
current operation: this includes explicit-delete rows with a null policy ID,
older operations and shared-reference rows that later became unblocked. The
current operation's `--maximum-asset-jobs` is a durable enqueue hard total;
`--maximum-dispatch-jobs` is the separate per-process cross-operation drain cap
and is bound into `required_confirmation`. Hitting the dispatch cap returns
incomplete status `2` before another Record batch, so an operator must review
and rerun the identical confirmed plan rather than silently exceeding it.

## Coordinated backup

Always inspect the plan first; dry-run performs no Docker, database, volume or
file operation:

```bash
./scripts/c19_full_backup.sh --dry-run \
  --generation-id GENERATION_ID \
  --barong-dataset-id BARONG_DATASET_ID \
  --record-dataset-id RECORD_DATASET_ID \
  --asset-dataset-id ASSET_DATASET_ID
```

Execution requires the exact printed `CONFIRM_C19_FULL_BACKUP`, the protected
HMAC key file and explicit Barong app version. The coordinator verifies the
three dataset identities and exact Compose projects, obtains an exclusive
full-system lock, and freezes every Barong database writer plus Record and Asset
writers. PostgreSQL containers remain private and running for consistent custom
dumps. The coordinator never uses `compose down`.

While the writers are stopped it captures all three domains, asserts the
single-writer boundary again, seals artifact path/size/SHA-256, schema revisions,
dataset identities, Asset member hashes and the quiesce interval into an
HMAC-authenticated manifest, then verifies the complete bundle. Only services
that belonged to the source writer set are resumed. A failed capture remains a
private quarantined partial generation and is never reported as accepted.

The coordinated gate requires Record `c19_record_20260712_04` and its four
coordination/retention tables, then verifies the archived v4 primary/foreign/
unique constraints, cap/counter/state/lease/completion checks and outbox/
operation indexes by schema token. Against the frozen source PostgreSQL it also
requires every v4 column, validated table/type constraint, exact
child-to-operation foreign-key binding with restricted deletion, and ready/
valid index before the bundle can be sealed. It also requires Asset
`c19_asset_20260712_03` and verifies the four retention-fence columns plus their
constraint/index names directly from the archived schema.

## Restore admission and order

Before any component restore, verify the immutable bundle against the intended
target identities:

```bash
./scripts/c19_full_restore_verify.sh \
  --manifest backups/c19-full/GEN/c19-full-GEN.json \
  --hmac-key-file /secure/c19-full-manifest.key \
  --barong-dataset-id BARONG_DATASET_ID \
  --record-dataset-id RECORD_DATASET_ID \
  --asset-dataset-id ASSET_DATASET_ID \
  --barong-revision BARONG_REVISION \
  --record-revision c19_record_20260712_04 \
  --asset-revision c19_asset_20260712_03
```

The admission gate validates the HMAC, every artifact checksum/size, PostgreSQL
custom-archive magic, exact Asset tar member bytes, revisions, datasets and the
all-writers-stopped attestation. It deliberately rejects `--execute`; automatic
full-system restore is too dangerous to present as one successful command.

After admission, restore only into isolated stopped targets in this order:

1. restore and migrate the Barong control database;
2. restore the Record dataset through its atomic-swap runbook;
3. restore the Asset database and exact object set through its consistency gate;
4. verify all three dataset/revision identities and private health snapshots;
5. exercise an affiliation-free user, affiliated user, chat, file and Moment
   authorization path;
6. enable exactly one writer set only after every check succeeds.

Retain the component rollback databases/archives for the documented rollback
window. Production execution, secret generation, maintenance-window approval
and traffic activation remain explicit operator actions outside source-code
acceptance.
