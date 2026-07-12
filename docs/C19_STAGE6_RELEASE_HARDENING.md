# C19 Stage 6 — Universal Access and Release Hardening

Status: implementation and source/isolated acceptance completed on `2026-07-12`.
Production activation was not performed and remains a separate explicitly
approved operation.

## 1. Final product contract

C19 is a basic capability of every authenticated, active Barong user. Access to
the C19 workspace and its directory, social, conversation, chat, asset and
Moments functions is not granted by an RBAC permission, role, organization,
organization membership or C19 affiliation.

One user still has one global communication profile and may have zero, one or
many organization affiliations. Affiliations are optional descriptive data and
may be used only for:

- displaying organization information on a global contact card;
- filtering the global directory;
- explicitly selecting the immutable maximum audience of an `org` Moment.

Omitting an affiliation never causes the server to guess one, even when the
user currently has exactly one. A user without an affiliation can still be
discovered, make friends, block another user, create direct and group
conversations, send messages and files, and publish `public`, `friends` or
`private` Moments.

## 2. Boundaries that remain security controls

Universal product access does not mean universal content access:

- the authenticated active user is always the actor;
- only current conversation members may read that conversation or its records
  and assets;
- group owner/admin/member rules govern group mutations;
- bilateral blocks stop new social/content interaction and current access where
  the product contract requires it;
- a Moment must satisfy both its immutable publication audience ceiling and
  current block/friend/explicit-organization visibility rules;
- short-lived asset tickets remain bound to exact owner, usage, scope, resource
  and version;
- disabled accounts and revoked sessions lose HTTP, SSE and asset access.

These are privacy, ownership and session-integrity controls. They are not module
permissions or organization admission gates.

## 3. Zero-affiliation persistence contract

`c19_profiles` remains one row per platform user. `c19_affiliations` remains a
projection of real organization memberships and creates no synthetic
organization.

Conversation members may store both `affiliation_id` and `org_id_at_join` as
null. They must be either both null or both non-null. A non-null pair must still
match an authoritative affiliation owned by that user. Existing conversation
members retain their historical snapshots during migration.

Directory and active-user resolution begin from active users/global profiles,
then left-load zero or more currently valid affiliations. Organization filters
remain exact filters and do not change the caller's authority.

## 4. Release-hardening contract

The completed final stage preserves the following operational properties:

- bounded request bodies, pages, event streams, upload sizes, decompression,
  image decoding and ticket lifetimes;
- distributed, content-free abuse controls that identify users/endpoints by
  hashes and return an explicit retry interval;
- durable idempotency for message, upload, publish, interaction and deletion
  retries;
- content-free health, audit and operational signals;
- bounded retention/deletion commands whose progress can resume safely;
- one-writer dataset identity and revision checks for both external stores;
- coordinated, checksummed Barong-control + Record + Asset backup evidence;
- restore validation before activation and explicit rollback material;
- no content, credential, signed ticket or physical object path in Git, logs,
  metrics, browser persistence or realtime notification payloads.

## 5. Frontend release contract

The C19 route is globally visible to authenticated users and bypasses the
ordinary capability/permission lock UI. A content-free unread badge is derived
from authorized unread APIs, refreshed in bounded batches and kept only in
memory.

Desktop and mobile layouts share the same server contracts. Empty organization
state is normal rather than an error. Loading, empty, failure, retry, reconnect,
focus/visibility changes, keyboard focus and reduced-motion behavior remain
explicit. The exact Next proxy allowlist and direct asset-byte boundary are not
broadened for convenience.

## 6. Acceptance evidence

Stage 6 is complete at the source and isolated-acceptance boundary. The recorded
evidence is:

- a user with no organization, affiliation or C19 permission can use every
  applicable base flow, while a disabled or unauthenticated user cannot;
- existing affiliated users and conversation rows migrate without identity or
  membership drift;
- private conversation, block, group-role, Moment visibility and asset-scope
  denial tests still pass;
- rate-limit, quota, content-free observability, retention and recovery tests
  pass under concurrency and retry;
- the focused Barong C19 suite passed `120` tests;
- the combined Record Service and Asset Service suites passed `180` tests;
- deployment, disaster-recovery, schema-admission and Nginx boundary suites
  passed all `20` tests;
- the frontend suite passed all `172` tests; TypeScript checking, Foundation
  verification and the production frontend build also passed;
- supplemental permission/migration/config-lock checks passed `19` tests, with `5`
  environment-dependent checks skipped;
- Python compilation, Bash syntax and Git whitespace/private-artifact checks
  passed;
- the native-access migration upgraded an isolated PostgreSQL database through
  `20260712_01_c19_native_access`; focused migration tests also covered
  backfill and downgrade behavior;
- fresh isolated PostgreSQL 17 databases upgraded Record to
  `c19_record_20260712_04` and Asset to `c19_asset_20260712_03` with zero
  metadata drift, then passed previous-revision downgrade/re-upgrade;
- real PostgreSQL acceptance proved exact retention replay and two-phase Asset
  deletion, blocking coordination/dataset row locks, and a concurrent quota
  race with exactly one reservation accepted and one rejected;
- earlier isolated Record and Asset PostgreSQL/HTTP restart and component
  backup/restore rehearsals remain valid, while Stage 6 adds tested coordinated
  full-system backup, restore-admission, retention and rollback tooling;
- production configuration is not activated by the acceptance rehearsal;
- all rehearsal containers, networks, volumes, environment files and archives
  are removed after evidence is captured;
- the complete reviewed Stage 1–6 C19 working-tree scope is committed only after
  every preceding gate passes.

Completion here records the implemented product and its non-production
acceptance evidence. It does not claim a live production rollout, a new-VPS
connection, or activation of protected production configuration.
