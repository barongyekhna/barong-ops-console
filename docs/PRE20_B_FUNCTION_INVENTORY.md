# PRE20-B Function Inventory

Generated: 2026-06-16

Purpose: reverse-map the current `barong-ops-console` implementation into a real product function inventory. This is a code-derived productization view, not an implementation plan.

## Scan Scope

Scanned implementation surfaces:

- `backend/app/`
- `backend/app/services/`
- `backend/app/schemas/`
- `backend/app/api/`
- `backend/app/repositories/`
- `backend/app/middleware/`
- `backend/app/sandbox/`
- `frontend/` excluding generated `node_modules` and `.next`
- `tests/`
- `docs/`
- `backend/alembic/versions/`

Repository note: there are no top-level `services/`, `schemas/`, `api/`, `repositories/`, `middleware/`, or `migrations/` directories. Their active equivalents are under `backend/app/`; migrations are under `backend/alembic/versions/`.

Tests were inspected statically. They were not executed.

## Status Rules

- `REAL`: API + service/repository + durable DB support with migration + tests. Frontend coverage is tracked separately.
- `PARTIAL`: API without durable DB, schema/service without complete implementation, backend-only feature, or feature depending on missing migration/UI.
- `MOCK`: demo, foundation/test bridge, contract-only/no-execute, 501/schema-only, in-memory-only, or no persistence.

Coverage fields:

- `backend coverage`: `full`, `partial`, `none`
- `frontend coverage`: `full`, `partial`, `none`
- `persistence`: `DB`, `memory`, `none`

## Function Classification Table

| Area | Function | Status | Backend coverage | Frontend coverage | Persistence | Evidence / product note |
|---|---|---:|---:|---:|---:|---|
| C01-C05 | auth login/logout/me | REAL | full | full | DB | `/api/public/auth/*`, `auth_service`, `auth_sessions`, login UI/auth provider, `test_auth_api.py`. |
| C01-C05 | user management | REAL | full | full | DB | `/api/app/users/*`, `user_management_service`, `users`, User Management UI, `test_user_management_api.py`. |
| C01-C05 | session management | REAL | full | partial | DB | DB-backed session hashes/cookies, session invalidation, rate-limit hooks, no separate session UI. |
| C01-C05 | RBAC role catalog/core checks | PARTIAL | partial | partial | none | Static role helpers and route guards exist; no DB-backed role policy management. |
| C01-C05 | permission registry and assignments | REAL | full | full | DB | `permission_registry`, `user_permission_assignments`, API and embedded permissions UI, backend/frontend tests. |
| C01-C05 | foundation data loop: jobs/artifacts/reviews/errors/memory | MOCK | full | full | DB | DB-backed demo/foundation records; actions are explicitly `*_demo`, no real business execution. |
| C06-C09 | module registry and module access state | PARTIAL | partial | full | DB | Static C07 manifests plus legacy DB registry; frontend navigation/modules use it, execution remains disabled. |
| C06-C09 | module adapter system | MOCK | partial | partial | none | Static C08 contract registry and adapter shell; no adapter persistence or executable action. |
| C06-C09 | execution provider registry | MOCK | partial | partial | none | Static C09 no-op/mock/contract-only registry; `can_request_execution=False` by design. |
| C10-C12 | sandbox runner/runtime/bridge | MOCK | partial | none | memory | C10 runner, runtime and bridge are deterministic mock-only, no production execution API. |
| C10-C12 | approval flow and persistence | REAL | full | none | DB | `/api/app/approval/*`, approval repos/tables/migration/tests; no frontend approval console. |
| C10-C12 | execution gating | MOCK | partial | none | none | C13E validates a no-execute contract chain; it does not open a real execution path. |
| C13-C16 | capability/model/dependency binding system | MOCK | partial | partial | none | C14X APIs expose read-only/empty/no-runtime contracts for AI bindings, model locks, allocations, prompts and dependencies. |
| C13-C16 | emergency kill switch | MOCK | partial | none | memory | Global process variable only, no DB or mounted control API. |
| C13-C16 | webhook gateway | PARTIAL | partial | none | none | HMAC/replay/contract gate exists; no real workflow dispatch or durable webhook queue. |
| C13-C16 | workflow registry and module-workflow binding | MOCK | partial | none | none | Static/read-only C15A/C15F contracts; no runtime workflow execution. |
| C13-C16 | payload standardization and result normalization | PARTIAL | partial | partial | none | Working transform APIs and proxy tests exist, but no durable execution/result lifecycle. |
| C13-C16 | callback handler and failure handling | MOCK | partial | none | memory | Callback result store and DLQ are process-memory; no durable queue or replay persistence. |
| C13-C16 | security system and control-plane isolation | REAL | full | partial | DB | C16 middleware, security headers, rate-limit/replay DB tables, frontend proxy isolation tests. |
| C17 | event collector | MOCK | partial | none | memory | Emits to logger and in-memory buffer only. |
| C17 | structured logs | PARTIAL | partial | none | none | Normalizer/schema/service/tests exist, no API or durable log table. |
| C17 | trace system | PARTIAL | partial | none | none | Trace aggregation/schema/tests exist, no mounted API or durable trace table. |
| C17 | storage layer | MOCK | partial | none | memory | C17D includes only `InMemoryStorageAdapter`. |
| C17 | audit query engine | MOCK | partial | none | memory | Query engine targets C17D memory adapter, no API or DB-backed index. |
| C17 | operation log API | REAL | full | none | DB | `/api/app/operation-logs/*`, repo/table/migration/tests; no direct frontend page. |
| C17 | replay system | MOCK | partial | none | memory | Snapshot/dry-run replay only, no mounted replay API or executor. |
| C17 | anomaly detection | MOCK | partial | none | memory | In-memory rolling detection; no alert persistence or production stream. |
| C18 | organization system | PARTIAL | partial | none | DB | API/service/repo/model/tests exist, but `organizations` has no Alembic migration. |
| C18 | membership system | PARTIAL | partial | none | DB | API/service/repo/model/tests exist, but `org_memberships` has no Alembic migration. |
| C18 | module binding | MOCK | partial | none | memory | `_MODULE_BINDINGS` process dictionary, no DB persistence. |
| C18 | shared module binding | MOCK | partial | none | memory | `_SHARED_MODULES` plus mutation of C18D in-memory state. |
| C18 | visibility system | PARTIAL | partial | none | memory | Visibility logic works over in-memory bindings and membership data; no durable binding storage. |
| C18 | permission isolation | PARTIAL | partial | partial | DB | Permission middleware/checks exist, but tenant membership/org tables are not migrated. |
| C18 | data isolation and org context | PARTIAL | partial | none | none | Middleware/context injection exists; production isolation depends on incomplete C18 persistence. |
| C19 | identity system | PARTIAL | partial | none | DB | Contact identity service/repo/model/tests exist, but `contact_identities` has no migration. |
| C19 | contact directory | PARTIAL | partial | none | DB | Directory query joins contact/org/membership tables, all dependent on missing C18/C19 migrations. |
| C19 | message system | MOCK | partial | none | none | `messages/send` returns envelope only; fetch/read APIs are 501; no message persistence. |
| C19 | conversation system | MOCK | partial | none | memory | Direct conversations are in-memory; group conversations return 501. |
| C19 | cross-org communication | PARTIAL | partial | none | none | Policy and permission gate exist; no message persistence and relies on partial C18/C19 identity data. |
| C19 | messaging permission and friend directory | MOCK | partial | none | memory | Friend requests are `_FRIEND_REQUESTS` in process memory. |
| C19 | attachment schema | MOCK | partial | none | none | Upload/fetch routes return C19G 501 placeholder notices. |
| C19 | future communication extensions | MOCK | partial | none | none | C19H is schema-only with no runtime routes. |

## System Statistics

Inventory size: 42 function entries.

- total real functions: 7
- total partial functions: 14
- total mock functions: 21
- backend completeness: 60% (`25 / 42`, weighted as full=1, partial=0.5, none=0)
- frontend completeness: 21% (`9 / 42`, weighted as full=1, partial=0.5, none=0)
- DB completeness: 27% (`11.5 / 42`, migrated DB=1, DB model without migration or DB dependency on missing tenant tables=0.5)

Migration gap found by model-table vs Alembic-table comparison:

- `organizations`: model/repo/service exists, no migration.
- `org_memberships`: model/repo/service exists, no migration.
- `contact_identities`: model/repo/service exists, no migration.
- `messages`: model exists, no migration; route does not persist messages.

## Risk Analysis

### Mock still in production path

- Foundation Demo and n8n Test Bridge are mounted under `/api/control-plane` and exposed in the frontend, but both are explicitly demo/mock-only.
- C08 adapters, C09 providers, C10 sandbox, C13E execution gate, and C14 capability/model/dependency controls are no-execute contract paths.
- C17 event buffers, storage adapter, replay, audit query, and anomaly detection use in-memory state.
- C18 module binding/shared modules and C19 conversations/friend requests use process memory.

### Schema-only APIs

- `POST /api/app/attachments/upload` and `GET /api/app/attachments/{message_id}` return C19G 501.
- `GET /api/app/messages/{conversation_id}` and `POST /api/app/messages/read` return C19C 501.
- Group conversation creation returns C19D 501.
- C19H future communication extensions are schema-only and have no runtime routes.

### Orphan backend services

- C17 structured logs, trace, storage, audit query, replay, and anomaly detection are service/test-level without mounted product APIs.
- Emergency kill switch has service-level state but no mounted API or DB persistence.
- Organization, membership, and contact identity services are implemented but production migrations are missing.
- `MessageRecord` exists without a repository, migration, or write path from `messages/send`.

### UI dead links / unreachable surfaces

- `/products` and `/settings` are visible pages but only empty states.
- C18 and C19 backend APIs have no frontend navigation or proxy allowlist coverage.
- Approval persistence has no frontend approval/review workflow.
- C14/C15 control-plane APIs are reachable through proxy allowlists/tests but do not have complete product pages.

### Duplicate or split functionality

- Legacy DB registry routes `/modules`, `/agents`, `/workflows` coexist with static C07 `/modules/registry`.
- C17 operation logs are durable DB records while C17 structured logs/traces/storage are separate non-durable service models.
- C18 shared modules mutate the same in-memory module binding store used by module binding.
- Conversation models appear in both C19 message and conversation schemas.
- Webhook gateway, callback handler, and n8n test bridge all model external workflow ingress, but only as gated/mock/contract surfaces.

## Productization Assessment

### What can already be shipped

- Internal authentication, DB-backed session cookies, login/logout/me, and owner-created user management.
- Permission registry and user permission assignment management for internal operators.
- Security hardening that is already mounted: control-plane isolation, security headers, login rate limiting, replay nonce storage.
- DB-backed operation log read API.
- Backend approval persistence API, as a governance record system only.

### What is partially shippable

- Module registry/navigation/access-state as metadata and permission-gated console shell.
- Webhook gateway and payload/result normalization as validation/contract utilities, not as a workflow execution system.
- C18 organization, membership, contact identity, and directory APIs only after migrations are added and UI/proxy coverage is built.
- Cross-org communication decisioning as a policy check, not as messaging.
- C17 structured log/trace/anomaly logic as libraries or test utilities, not as production observability.

### What cannot be shipped

- Real module execution, live n8n dispatch, live execution providers, or sandboxed production actions.
- IM product: durable conversations, message history, read state, attachments, media, group chat, friend directory persistence.
- Multi-tenant module binding/shared module persistence.
- C14 AI/model/capability allocation as runtime AI execution controls.
- Durable replay, audit query, trace search, anomaly alerting, or C17 storage.

### What breaks in production

- C18/C19 DB-backed routes will fail in a migration-managed production database unless `organizations`, `org_memberships`, `contact_identities`, and `messages` migrations are added.
- Any multi-worker deployment will diverge for in-memory kill switch, module bindings, shared modules, conversations, friend requests, callback store, DLQ, C17 event buffers, C17 storage, replay, and anomaly windows.
- Frontend cannot call C18/C19 APIs through the current backend proxy allowlist.
- Execution attempts remain blocked by design at adapter/provider/gate/sandbox layers.
- Message send accepts and emits an envelope but does not create retrievable message history.

## Bottom Line

The current system is strongest as an internal authenticated control-plane foundation with user/permission/session/security primitives and durable audit/approval metadata. It is not yet a product-ready automation runtime, multi-tenant OS, or IM system. The dominant blockers are no-execute/mock execution layers, missing C18/C19 migrations, process-memory state, and absent frontend/product flows for tenant and messaging features.
