# PRE20 FIX TASK BOARD

Generated: 2026-06-17

Scope: convert PRE20-A through PRE20-M findings into an engineering fix backlog for C01-C18, C17, UI, and infrastructure only. This is a planning artifact. No code, migration, CI/CD change, deployment, runtime command, or test execution is included.

C19_IM_SYSTEM: EXCLUDED_FROM_FIX_SCOPE
Reason: intentionally deferred future module
Status: no tasks generated

### 1. Master Fix Task Table

| Task ID | Area | Problem | Fix Action | Priority | Depends on |
|---|---|---|---|---|---|
| P0-001 | C18 / DB | Core tenant data is not org-scoped; jobs, artifacts, reviews, approvals, operation logs, memory, errors, context packets, and related business records can be listed globally. | Add `org_id` or explicit global-resource classification to every persistent business table, then backfill ownership and enforce non-null ownership for tenant data. | P0 | None |
| P0-002 | C18 / Repositories | C18G can only scope models that already have `org_id`; legacy repositories still run global list/detail queries. | Refactor repositories and routes to require org context and apply org filters for all tenant-owned records. | P0 | P0-001 |
| P0-003 | C18 / Migration | C18 organization and membership models/services exist but managed migrations are incomplete. | Create and promote Alembic migrations for organizations, org memberships, durable module bindings, shared modules, and required ownership indexes. | P0 | P0-001 |
| P0-004 | C05 / C18 | Multiple permission systems coexist and create bypass drift. | Define one authoritative permission path using org, module, action, visibility, and explicit global-resource classification; migrate route guards to it. | P0 | P0-001, P0-002 |
| P0-005 | C18F | Owner bypass skips org membership, module binding, and data isolation checks. | Replace global owner bypass with explicit platform-owner and org-owner policies; require scoped authorization for tenant data access. | P0 | P0-004 |
| P0-006 | C18 middleware | C18F/C18G pass through when org/module context cannot be resolved. | Make tenant context mandatory on tenant routes, or mark routes as audited global resources with local invariants and tests. | P0 | P0-004 |
| P0-007 | C18D / C18I | Module binding and shared-module state is process memory and diverges across workers. | Move module bindings and shared-module records to durable DB tables with transactional updates and consistency checks. | P0 | P0-003 |
| P0-008 | C13D | Emergency kill switch is process-local memory and not cluster-wide. | Persist kill switch state in a durable store and enforce it through all execution gates with atomic reads/writes. | P0 | P0-019 |
| P0-009 | C08-C15 | Execution system is structurally mock-only; adapters, providers, gate, sandbox, and workflow layer cannot perform staging/live execution. | Introduce provider-routed execution architecture with `mock`, `staging`, and `live` modes, hard mode matching, no silent fallback, and upstream C18/C13/C14/C15 evidence. | P0 | P0-004, P0-007 |
| P0-010 | C08 | Adapter action contracts are locked to `mock`/`no_op`. | Add mode-aware adapter action policy and route all non-mock action requests into the execution provider router. | P0 | P0-009 |
| P0-011 | C09 | Provider registry is static, no-execute, and cannot express staging/live readiness. | Split provider metadata from runtime provider resolution; add `staging_ready` and `live_ready` states with env/org/module policy checks. | P0 | P0-009 |
| P0-012 | C10 | Sandbox runtime is hard-coded to disabled/mock-only execution. | Keep mock runtime as MockProvider, then design a separate staging-ready sandbox runtime with isolated credentials, callbacks, storage, and audit. | P0 | P0-009, P0-011 |
| P0-013 | C13E | Execution flow gate blocks live/external/callback provider paths and lacks an approved positive path for approval-required work. | Make gate decisions mode-aware and add explicit approved pass-through semantics tied to C12 approval records. | P0 | P0-009, P0-012 |
| P0-014 | C15 | Workflow registry and module-workflow binding are decision-only; dispatch is absent. | Separate workflow registry/whitelist from runtime dispatch; dispatch must call the provider router after C15A/C15F approval. | P0 | P0-009, P0-013 |
| P0-015 | C15 | Callback store and DLQ are in-memory and racy. | Persist callback context, callback results, retry state, DLQ records, and replay attempts with idempotency keys and transactional state transitions. | P0 | P0-014 |
| P0-016 | C15 / C16 | Signed system ingress is mounted behind human/session control-plane semantics. | Split external signed ingress from human control-plane auth while preserving replay protection, C18/C13/C15 gates, and audit requirements. | P0 | P0-015 |
| P0-017 | C17 | Event collector, storage, audit query, replay, and anomaly state are memory-backed and can drop or lose data. | Build durable event/log/trace/replay/anomaly storage with a real sink and explicit retention/partition strategy. | P0 | P0-001 |
| P0-018 | C17 | Queue overflow silently drops audit events; daemon drain can lose buffered data on shutdown. | Replace best-effort in-memory queue with durable ingestion, backpressure/error reporting, and loss accounting surfaced to operators. | P0 | P0-017 |
| P0-019 | Infra / DB | Migration promotion is manual and stale after C08; C12/C16/C17/C18 changes have no generalized release gate. | Add migration release gate: backup, lock, dry-run, `alembic current/head` verification, upgrade, smoke, and rollback/restore decision point. | P0 | P0-021 |
| P0-020 | Infra / CI/CD | No CI/CD pipeline binds tests, builds, migrations, staging, production approval, and rollback metadata. | Add backend, frontend, integration, system, migration, image-build, artifact, staging, and production approval jobs. | P0 | P0-028 |
| P0-021 | Ops / Backup | No Postgres backup, restore, PITR, restore drill, retention, or RPO/RTO policy exists. | Implement Postgres backup and restore system, including scheduled backups, off-host retention, restore rehearsal, and migration restore points. | P0 | None |
| P0-022 | Ops / Rollback | Rollback image tags exist but no executable rollback system exists. | Implement rollback command/runbook for backend/frontend images plus DB restore/migration compatibility validation and post-rollback smoke. | P0 | P0-019, P0-021 |
| P0-023 | Ops / DR | Disaster recovery strategy is absent. | Define DR plan with RPO/RTO, server rebuild, secret recovery, Postgres restore, image restoration, DNS/proxy recovery, and exercise cadence. | P0 | P0-021, P0-022 |
| P0-024 | Ops / Smoke | Health checks do not validate DB queryability, migrated schema, authenticated flow, permissions, or tenant isolation. | Add deep staging/prod smoke checks for DB connectivity, schema head, auth/session, permission resolution, org-scoped access, proxy, and security headers. | P0 | P0-019 |
| P0-025 | Ops / Alerting | C17 does not emit to a production alert sink. | Implement alert routing from durable C17 events into real notification/incident sinks with severity, ack, suppression, and escalation. | P0 | P0-017 |
| P0-026 | Concurrency | Callback, DLQ, approvals, job events, reviews, replay nonces, rate limits, and login counters have race/lost-update risks. | Add row locks, optimistic versioning, atomic SQL increments, unique active constraints, transactional idempotency, and deterministic conflict handling. | P0 | P0-015, P0-019 |
| P0-027 | Concurrency / Auth | Session validation writes `last_seen_at` repeatedly across middleware/deps and can create write amplification. | Consolidate session validation and throttle or batch `last_seen_at` updates. | P0 | P0-026 |
| P0-028 | Testing | Host pytest, DB tests, frontend tests, and full C01-C18 coverage are not repeatable. | Standardize local and Docker test entrypoints, markers, isolated DB setup, and full backend/frontend/system lanes before CI adoption. | P0 | None |
| P1-001 | C07 / Architecture | Module manifests, switch registry, route metadata, and navigation are hardcoded. | Move module metadata, route namespace, switch policy, permissions, and release flags into a registry/config source that can drive backend and frontend. | P1 | P0-004 |
| P1-002 | UI / Frontend | Sidebar is static and only filtered after the fact. | Generate sidebar from capability registry, active org visibility, permission state, adapter/provider readiness, and API binding state. | P1 | P0-007, P1-001 |
| P1-003 | UI / Proxy | Frontend proxy allowlist is static and has demo/test exceptions while real operator APIs are missing. | Align proxy rules with capability registry and product pages; remove normal-path demo exceptions and add only audited real routes. | P1 | P1-002 |
| P1-004 | UI / Capability | Empty, locked, hidden, and partial states are generic and do not explain unlock conditions. | Add `ProductCapabilityItem` and `CapabilityEmptyState` models with reason, permissions, org state, module state, API binding, and execution readiness. | P1 | P1-002 |
| P1-005 | C18 / UI | Frontend does not use active org context or C18E visible modules as its source of truth. | Add active-org state and route/sidebar resolution from durable C18 visible-module APIs. | P1 | P0-007, P1-002 |
| P1-006 | C05 / C18 | Role and owner semantics are hardcoded and not tenant-configurable. | Introduce scoped role policy, delegated org-admin records, platform-owner separation, and module-owned permission manifests. | P1 | P0-004, P0-005 |
| P1-007 | C18F | Module action rules are hardcoded by module family with broad fallback. | Replace hardcoded series rules with module-owned action manifests and fail-closed unknown-module behavior. | P1 | P1-001, P1-006 |
| P1-008 | C09 / C14 | Provider, secret, and external dependency registries are static. | Add env-aware connector registry with secret references, dependency allowlists, provider readiness, and policy validation. | P1 | P0-011 |
| P1-009 | C15 | Workflow registry and result normalization mappings are hardcoded around current shapes. | Move workflow registry, module workflow binding, and result normalization mappings to data/config governed by module ownership. | P1 | P0-014 |
| P1-010 | Execution / Staging | No isolated staging connector namespace exists. | Define staging credentials, callback namespace, storage namespace, endpoint allowlists, and explicit staging result markers. | P1 | P0-011, P0-012 |
| P1-011 | C17 / UI | Operation logs are DB-backed but lack a product page/proxy binding. | Add operation-log page and proxy binding as the first C17 operator surface. | P1 | P0-017, P1-003 |
| P1-012 | C17 / UI | Dashboard is an empty state rather than an operations surface. | Rebuild dashboard from C17 operation data, C12 approvals, module readiness, provider readiness, health, and permission snapshot. | P1 | P1-004, P1-011 |
| P1-013 | C12 / UI | Approval persistence exists without an operator console. | Add approvals page and proxy binding for list/detail/approve/reject, with no execution implication until C13/C15 gates are ready. | P1 | P0-013, P1-003 |
| P1-014 | DB / Performance | High-volume tables lack indexes for tenant, status, time, actor, job, execution, request, and trace lookups. | Add DB indexing strategy and cursor pagination for jobs, events, approvals, reviews, operation logs, memory records, security buckets, memberships, and execution records. | P1 | P0-001, P0-019 |
| P1-015 | API / Performance | Registry and permission APIs over-fetch and frontend uses `no-store` everywhere. | Add server pagination/cache headers where safe, client request dedupe, stable registry caching, and permission snapshot reuse. | P1 | P1-014 |
| P1-016 | Infra / Runtime | Compose topology has no migration runner, worker, queue, scheduler, sandbox executor, or alerting service. | Define runtime topology for migration jobs, callback/retry workers, durable queue, alerting, and optional execution workers. | P1 | P0-015, P0-020 |
| P1-017 | Infra / Artifact | Builds are local Compose images without immutable artifact promotion. | Add artifact registry, image digest promotion, release manifest, commit-to-image attestation, and retention policy. | P1 | P0-020 |
| P1-018 | Testing | Runtime and test dependencies are mixed; backend image copies tests and installs pytest. | Split runtime requirements from dev/test requirements and move tests into dedicated test image stages. | P1 | P0-028 |
| P1-019 | Testing | DB tests mix Alembic, `create_all`, shared cleanup, and implicit default DB URLs. | Use Alembic as integration schema source, add production/staging URL guards, and split unit-safe from integration-only fixtures. | P1 | P0-028 |
| P1-020 | Testing / Frontend | Frontend Node tests are not wired into package scripts or Docker test flow. | Add `npm test` and Docker/CI execution for frontend Node tests before verify/typecheck/build. | P1 | P0-028 |
| P1-021 | C13 / C15 | Replay nonce and callback state can commit in separate failure windows. | Make replay nonce reservation and callback state update part of one durable idempotency transaction. | P1 | P0-015, P0-026 |
| P1-022 | C16 / Env | Production-like environment classification is duplicated across config, cookies, security headers, and proxy assumptions. | Centralize environment class policy and route/cookie/proxy config ownership. | P1 | P0-020 |
| P1-023 | C07 / C15 | Integration test bridge module ID drifts between namespaced and non-namespaced forms. | Canonicalize module ID usage across registry, repositories, workflows, audit, UI, and permission binding. | P1 | P1-001 |
| P1-024 | C17 | Durable observability needs retention and query boundaries to avoid unbounded growth. | Define retention, partitioning, archive, index, and query-limits policy for logs, traces, replay inputs, and anomaly signals. | P1 | P0-017, P1-014 |
| P2-001 | UI | `foundation-demo` is product-visible despite being demo-only. | Remove from production sidebar, production proxy normal paths, dashboard cards, and product copy; keep only behind internal non-production diagnostics if needed. | P2 | P1-002, P1-003 |
| P2-002 | UI | `n8n-test` is product-visible despite being a mock/test bridge. | Remove from production sidebar and normal operator flows; keep only as internal diagnostics with explicit environment labeling if retained. | P2 | P1-002, P1-003 |
| P2-003 | UI | `/products` and `/settings` are empty pages without backend bindings. | Hide from production navigation until real APIs, proxy bindings, and capability records exist. | P2 | P1-002 |
| P2-004 | UI | Dashboard, Products, Settings, and foundation-era lists use generic empty states that imply unavailable features are merely empty. | Replace with capability-aware empty states that distinguish empty data, no permission, hidden module, missing API, mock-only, adapter pending, and backend unavailable. | P2 | P1-004 |
| P2-005 | UI / C17 | Standalone memory page and wording imply a real memory product although records are audit-like and model calls are absent. | Reclassify as audit records under C17 observability and remove AI-memory product framing. | P2 | P1-012 |
| P2-006 | UI | Visible F-series, foundation, demo, and stage labels remain in product copy. | Remove misleading stage labels and rewrite empty/loading/status copy around real data sources and capability states. | P2 | P2-001, P2-002 |
| P2-007 | UI / Execution | Adapter/provider shells are globally visible and can look like product actions even when no-execute. | Move adapter/provider shells to diagnostic/read-only pages or show compact readiness state only where operationally useful. | P2 | P1-012 |
| P2-008 | UI | Jobs, artifacts, reviews, modules, agents, and workflows can imply execution/storage when they are metadata/record views. | Rename or label pages as records/metadata/read-only until execution, storage, or decision actions are product-ready. | P2 | P1-004 |
| P2-009 | UI / Review | Review decision actions are missing or not product-bound. | Keep reviews read-only until decision routes, proxy binding, approval semantics, and permission checks are unified. | P2 | P1-013 |
| P2-010 | UI / Observability | Errors, memory records, and operation logs are fragmented. | Merge into C17 operations/audit information architecture with filters and source labels. | P2 | P1-011, P1-012 |
| P2-011 | UI / Admin | Settings is a placeholder route. | Merge any real settings controls into users/permissions/admin pages until a real settings module is installed. | P2 | P2-003 |
| P2-012 | UI / Copy | Direct-route blocked states do not provide concrete unlock conditions. | Show missing permission, required role, active org state, module state, provider mode, and backend binding reason. | P2 | P1-004 |

### 2. Execution System Fix Plan

- C08 adapter execution unlock
  - Convert adapter actions from `mock`/`no_op` only to mode-aware contracts.
  - Require every non-mock action to submit a normalized payload to the execution provider router.
  - Preserve read-only adapter registry behavior until C18, C13, C14, C15, audit, and idempotency evidence is present.

- C09 provider execution routing redesign
  - Split provider metadata registry from runtime provider resolver.
  - Add `mock`, `staging`, and `live` provider modes with hard mode matching.
  - Add org policy, module policy, deployment cap, provider readiness, explicit intent, and no silent fallback.
  - Add result contract fields: provider mode, provider key, execution id, request id, status, external effect, production effect, and normalization version.

- C10 sandbox evolution (mock → staging-ready architecture)
  - Keep current deterministic mock sandbox as MockProvider behavior.
  - Create a separate staging-ready sandbox path with non-production endpoints, staging secrets, callback namespace, artifact namespace, timeout/retry policy, and durable audit.
  - Do not reuse mock-only finalization as proof of live execution.

- C13 execution flow gate correction
  - Replace static no-runtime blocking with mode-aware allow/deny decisions.
  - Add explicit approved pass-through for C12 approval-required executions.
  - Enforce durable kill switch, module switch, dependency/secret policy, provider readiness, and idempotency reservation before dispatch.

- C15 workflow execution separation
  - Keep workflow registry and module-workflow whitelist as gates only.
  - Add a distinct dispatch step that calls the provider router.
  - Persist callback context, results, retries, DLQ, replay state, and result normalization before any non-mock dispatch is enabled.
  - Split external signed ingress from human control-plane session paths.

### 3. Multi-Tenant Fix Plan (C18 only)

- org_id propagation to ALL business tables
  - Add `org_id` to tenant-owned records across foundation, approval, observability, execution records, and business metadata.
  - Explicitly classify true platform/global resources so they cannot silently bypass C18.
  - Backfill and validate ownership before enforcing non-null tenant ownership.

- DB migration completion for C18
  - Add Alembic migrations for organizations, org memberships, module bindings, shared modules, ownership indexes, and C18 route dependencies.
  - Include migration promotion checks in staging and production release gates.

- permission unification (remove multiple systems)
  - Replace route-by-route drift between legacy RBAC, C05 assignments, and C18F checks with one org/module/action/visibility permission decision.
  - Remove global owner shortcuts from tenant data access.
  - Make unknown tenant scope fail closed.

- remove memory-based module binding
  - Replace process dictionaries and private-state mutation with durable module binding repositories.
  - Make shared module updates transactional with module visibility updates.
  - Add idempotent writes and conflict handling for concurrent binding changes.

- enforce durable org isolation
  - Require active org context for tenant routes.
  - Apply repository-level org filters and DB constraints, not only middleware.
  - Add cross-org denial verification requirements to CI after the test environment is standardized.

### 4. UI Productization Fix Plan

- sidebar dynamic generation from capability registry
  - Generate navigation from module registry, active org visibility, current permission snapshot, adapter/provider readiness, and API binding state.
  - Hide `planned`, `mock`, `demo`, `test`, `schema_only`, and `no_execute` entries from production navigation unless explicitly diagnostic.

- remove fake UI (foundation-demo, n8n-test)
  - Remove both entries from product sidebar, dashboard, and normal proxy paths.
  - Retain only as internal non-production diagnostics if needed, with no product navigation entry.

- dashboard rebuild (C17-driven)
  - Replace the empty dashboard with operations health, operation logs, approvals, provider readiness, module readiness, permission snapshot, and active org state.
  - Every dashboard tile must show source, freshness, and unavailable reason.

- empty state redesign (capability-aware)
  - Distinguish empty data from missing API, no permission, hidden module, no active org, module disabled, adapter pending, execution unavailable, and backend failure.
  - Include unlock condition, required permission, required role, required org state, and backend binding.

- remove misleading demo/foundation UI labels
  - Remove stage labels, demo wording, and foundation-era copy from production pages.
  - Rename record-only pages so they do not imply execution, storage, model memory, or workflow dispatch.

### 5. Performance & Concurrency Fix Plan

- eliminate shared memory state (C18/C17/C15)
  - Replace C18 module/shared bindings, C17 event/storage/query/anomaly state, C15 callback/DLQ state, and C13 kill switch globals with durable stores.
  - Treat all remaining memory stores as non-authoritative cache only.

- fix queue durability issues
  - Replace lossy in-process queues with durable ingestion and backpressure.
  - Surface dropped-event or delayed-event metrics through C17 and alerting.

- add DB indexing strategy
  - Add indexes for tenant, status, created time, actor, action, request id, trace id, execution id, job id, module id, approval state, and membership state.
  - Replace high-offset and full-table scans with cursor pagination and bounded filters.

- fix race conditions (callbacks, approvals, DLQ, logs)
  - Add atomic state transitions, idempotency keys, row locks or optimistic versions, partial unique constraints, and deterministic conflict responses.
  - Keep replay nonce reservation and business/callback state updates in one transactional boundary.

- introduce proper locking & transaction safety
  - Use DB transactions for authoritative state.
  - Avoid cross-service private-state mutation.
  - Add conflict-aware write APIs for module binding, approvals, job events, review decisions, callback status, rate limits, and session updates.

### 6. Testing & CI/CD Fix Plan

- fix pytest environment (venv + dev requirements split)
  - Add standard Python 3.12 virtualenv bootstrap and `backend/requirements-dev.txt`.
  - Add pytest config, markers, and canonical local commands.

- split dev/prod dependency system
  - Remove test tooling from runtime images where safe.
  - Move backend tests into dedicated test image stages.
  - Keep runtime requirements limited to application runtime and approved migration tooling.

- add CI pipeline (backend/frontend/system)
  - Add backend unit, backend integration with Postgres, frontend tests, frontend build, system Docker smoke, migration verification, image build, artifact publishing, staging acceptance, and production approval jobs.

- integrate frontend test execution
  - Add `npm test` for Node test files.
  - Run frontend tests before verify/typecheck/build in Docker and CI.

- standardize docker test environments
  - Add test Compose profile/project with isolated Postgres, ephemeral volumes, no staging/production env files, and explicit safety checks.
  - Add migration runner step before integration tests.

- unify test isolation strategy (DB + mock layer)
  - Use Alembic as the integration schema source.
  - Split unit and integration fixtures.
  - Add canonical mocks for provider, sandbox, test bridge, and external dependency boundaries.
  - Add production/staging DB URL guards.

### 7. Ops & Recovery Fix Plan

- implement backup system (Postgres + restore)
  - Add scheduled Postgres backups, off-host retention, restore scripts/runbook, backup verification, and restore drills.
  - Define backup ownership, retention, encryption, and access controls.

- implement rollback system (image + DB + migration)
  - Turn rollback tags into an executable rollback path.
  - Pair image rollback with DB restore/migration compatibility checks, health wait, authenticated smoke, and rollback audit record.

- implement DR strategy (RPO/RTO)
  - Define RPO/RTO targets, server rebuild procedure, secret recovery, artifact restore, database restore, DNS/proxy recovery, and DR exercise cadence.

- implement incident response playbook
  - Add severity levels, owner/escalation path, triage checklist, communication template, data-loss procedure, security incident procedure, and postmortem template.
  - Include migration failure, deploy failure, DB outage, auth outage, tenant isolation incident, callback/DLQ failure, and observability loss scenarios.

- implement alerting system (C17 → real sink)
  - Route durable C17 events, health failures, migration failures, backup failures, queue lag, dropped events, auth/rate-limit anomalies, and tenant-isolation violations to real alert sinks.
  - Add acknowledgement, suppression, escalation, and operator dashboard linkage.
