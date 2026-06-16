# PRE20-E Function Runtime Report

Generated: 2026-06-16

Mode: static source audit only. No production runtime was started, no business code was changed, no migration was created, and no UI or architecture was modified.

### 1. Function Runtime Matrix

| Function | Module | Status | API | DB | Frontend | Notes |
|---|---|---|---|---|---|---|
| Auth login / logout / me | C01-C05 auth | 🟢 FULLY RUNNABLE | Mounted: `/api/public/auth/login`, `/me`, `/logout` | `users`, `auth_sessions`, login lockout fields, security rate-limit tables | Login page, auth provider, route guards | Real DB-backed session cookie flow with password verification, session hash persistence, logout invalidation, and permission resolution. |
| Internal user management | C01-C05 users | 🟢 FULLY RUNNABLE | Mounted: `/api/app/users/*` | `users`, operation logs | `/users` management panel | Owner-gated create/update/disable/enable/reset-password flow uses service and repository logic. |
| Session management | C01-C05 auth | 🟢 FULLY RUNNABLE | API-callable through auth routes and deps | `auth_sessions`, login failure/lockout fields | Auth provider consumes `/auth/me`; no dedicated session admin UI | Session validation, seen-at update, expiration, lockout, and invalidation are real. |
| RBAC role catalog and route checks | C01-C05 RBAC | 🟡 PARTIALLY RUNNABLE | Mounted: `/api/app/users/roles`; route deps active | User role stored on `users`; no role policy tables | User UI and route guards use role metadata | Fixed/static roles work, but there is no DB-backed role policy management or role migration beyond `users.role`. |
| Permission registry and assignments | C01-C05 permissions | 🟢 FULLY RUNNABLE | Mounted: `/api/app/permissions/*` | `permission_registry`, `user_permission_assignments`, `role_default_permissions` | Embedded in `/users` | Real permission catalog, assignment, revoke/update, high-risk confirmation, and current-user permission resolution. |
| Foundation data loop: jobs, artifacts, reviews, errors, memory | C01-C05 foundation | 🔴 NOT RUNNABLE | Mounted app APIs exist | Foundation tables exist | `/jobs`, `/artifacts`, `/reviews`, `/errors`, `/memory-events` | DB-backed demo/metadata records only; job/review/memory actions explicitly mark demo or no model/business execution. |
| Module registry and module access state | C06-C09 module | 🟡 PARTIALLY RUNNABLE | Mounted: `/api/control-plane/modules`, `/registry`, `/me` | `module_registry`; static manifest registry | `/modules`, navigation/module guards | Registry metadata and access state are callable, but module execution remains disabled. |
| Module adapter system | C06-C09 adapter | 🔴 NOT RUNNABLE | Mounted: `/api/control-plane/module-adapters/*` | No adapter persistence migration | Adapter shell/client types exist | Contract registry only; adapters expose declared surfaces and `can_request_execution=false`, no executable action path. |
| Execution provider registry | C06-C09 provider | 🔴 NOT RUNNABLE | Mounted: `/api/control-plane/execution-providers/*` | No provider persistence migration | Provider status shell/client types exist | Providers are no-op/mock/contract/future placeholders; `executable=false` and `can_request_execution=false`. |
| Sandbox runner/runtime/bridge | C10 sandbox | 🔴 NOT RUNNABLE | No mounted production execution endpoint | Memory/contracts only | None | Runtime is explicitly `disabled_execution` and `mock_only`; no process, network, filesystem, DB write, or real computation is allowed. |
| Approval flow and persistence | C10-C12 approval | 🟢 FULLY RUNNABLE | Mounted: `/api/app/approval/*` | `approval_requests`, `approval_workflows`, `approval_decisions` | No approval console; API callable | Real durable approval records and decisions. It intentionally does not execute approved actions. |
| Execution gating | C10-C12 gate | 🔴 NOT RUNNABLE | Service-level gate, no user execution endpoint | None | None | C13E validates the C08-C14-C09-C10 contract chain but execution remains locked and no runtime work is performed. |
| Capability/model/dependency/AI binding controls | C13-C16 control plane | 🔴 NOT RUNNABLE | Mounted C14/C14X read/validation APIs | None | Proxy/client tests only, no product pages | Static or schema-only registries for AI bindings, model locks, capability routing, allocations, prompts, and dependencies. |
| Emergency kill switch | C13 control plane | 🔴 NOT RUNNABLE | No mounted control API | Process memory only | None | Global kill switch state is a process-local variable; not durable or cluster-wide. |
| Webhook gateway | C13-C16 workflow ingress | 🟡 PARTIALLY RUNNABLE | Backend mounted: `/api/control-plane/webhook-gateway/*`; frontend proxy blocks ingress | Replay/security helpers, no durable queue | No frontend | HMAC/replay/contract checks exist, but ingress does not dispatch live n8n/workflow execution. |
| Workflow registry and module-workflow binding | C13-C16 workflow | 🔴 NOT RUNNABLE | Mounted read/decision APIs | None | Proxy/client tests only | Static/read-only workflow registry and binding decisions; no workflow execution runtime. |
| Payload standardization and result normalization | C13-C16 execution contracts | 🟡 PARTIALLY RUNNABLE | Mounted transform APIs | None | Proxy/client tests only | Normalization logic executes, but it is not connected to a durable execution/result lifecycle. |
| Callback handler and failure handling | C13-C16 callback/failure | 🔴 NOT RUNNABLE | Mounted callback/failure/DLQ APIs | Process memory only | None | Callback store and DLQ are in-memory; replay prepares plans but does not dispatch real recovery. |
| Security system and control-plane isolation | C13-C16 security | 🟢 FULLY RUNNABLE | Middleware and public firewall routes mounted | `security_rate_limit_buckets`, `security_replay_nonces`, auth/session tables | Frontend proxy blocklist and auth flow | Control-plane session/role isolation, security headers, replay/rate-limit storage, and direct webhook/n8n firewall are active. |
| Event collector | C17 observability | 🔴 NOT RUNNABLE | Middleware/service only | Process memory/logging only | None | Audit event queue and recent buffer are process-local; no durable event API/table. |
| Structured logs | C17 observability | 🟡 PARTIALLY RUNNABLE | No product API | None | None | Schema/normalizer/service tests exist, but there is no mounted log API or durable log table. |
| Execution trace | C17 observability | 🟡 PARTIALLY RUNNABLE | No product API | None | None | Trace aggregation/schema logic exists, but no mounted trace API or durable trace table. |
| Storage layer | C17 observability | 🔴 NOT RUNNABLE | No product API | In-memory adapter only | None | Only `InMemoryStorageAdapter` is implemented for validation/tests. |
| Audit query engine | C17 observability | 🔴 NOT RUNNABLE | No mounted API | Depends on in-memory storage adapter | None | Query engine operates over local adapter records, not a durable audit index. |
| Operation log API | C17 observability | 🟢 FULLY RUNNABLE | Mounted: `/api/app/operation-logs/*` | `operation_logs` | No direct page; API callable | Real DB-backed operation log listing/detail API. |
| Execution replay | C17 observability | 🔴 NOT RUNNABLE | No mounted replay API | Snapshot/dry-run memory inputs | None | Replay is snapshot/dry-run oriented unless an external executor is injected; no production replay path. |
| Anomaly detection | C17 observability | 🔴 NOT RUNNABLE | No mounted API | Process memory rolling window | None | Detection logic exists as service/test utility; no durable stream, alert store, or product API. |
| Organization lifecycle | C18 multi-tenant OS | 🟡 PARTIALLY RUNNABLE | Mounted: `/api/app/org/*` | Model/repo/service exist, but no Alembic migration for `organizations` | None; frontend proxy does not allow it | API logic exists but will fail in a migration-managed production DB without the missing table. |
| Organization membership | C18 multi-tenant OS | 🟡 PARTIALLY RUNNABLE | Mounted: `/api/app/org/{org_id}/members*` | Model/repo/service exist, but no Alembic migration for `org_memberships` | None; frontend proxy does not allow it | Membership checks are implemented, but runtime DB table is missing. |
| Module binding | C18 multi-tenant OS | 🔴 NOT RUNNABLE | Mounted app APIs | Process memory `_MODULE_BINDINGS` | None | Tenant/module binding is in-memory only and diverges across workers/restarts. |
| Shared module binding | C18 multi-tenant OS | 🔴 NOT RUNNABLE | Mounted app APIs | Process memory `_SHARED_MODULES` and `_MODULE_BINDINGS` | None | Shared module registry is not durable and mutates private in-memory C18D state. |
| Module visibility system | C18 multi-tenant OS | 🟡 PARTIALLY RUNNABLE | Mounted visibility APIs | Depends on missing membership migration and in-memory bindings | None | Visibility decisions can run in-process, but the authoritative binding source is not durable. |
| Permission isolation layer | C18 multi-tenant OS | 🟡 PARTIALLY RUNNABLE | Middleware active | Permission DB exists; org membership migration missing | Partial through existing permission UI | C18F permission checks exist, but tenant membership and module binding dependencies are incomplete. |
| Data isolation and org context | C18 multi-tenant OS | 🟡 PARTIALLY RUNNABLE | Middleware active | No complete tenant schema migration coverage | None | Org context and data isolation middleware exist, but production isolation depends on incomplete C18 persistence. |
| Contact identity system | C19 IM | 🟡 PARTIALLY RUNNABLE | Mounted: `/api/app/contacts/*` | Model/repo/service exist, but no Alembic migration for `contact_identities` | None; frontend proxy does not allow it | Identity lookup/update logic exists, but the runtime table is missing. |
| Contact directory | C19 IM | 🟡 PARTIALLY RUNNABLE | Mounted: `/api/app/contacts/directory` | Depends on missing `contact_identities` and `org_memberships` migrations | None | Directory query joins C18/C19 tables that are not migrated. |
| Message system | C19 IM | 🔴 NOT RUNNABLE | Mounted: `/api/app/messages/send`, `/permission/check`; history/read return 501 | `messages` model exists but no migration/repository/write path | None; frontend proxy does not allow it | Send returns an accepted envelope only; no persistence, no delivery, no history, no read state. |
| Conversation system | C19 IM | 🔴 NOT RUNNABLE | Mounted: `/api/app/conversations/*` | Process memory only; no conversation migration | None; frontend proxy does not allow it | Direct conversations are in-memory; group creation is reserved and returns 501. |
| Cross-org communication | C19 IM | 🟡 PARTIALLY RUNNABLE | Mounted: `/api/app/comm/cross-org/check` | Depends on incomplete C18/C19 persistence and in-memory IM boundary | None; frontend proxy does not allow it | Policy and permission decisions exist, but no durable message/runtime path exists. |
| Messaging permission and friends | C19 IM | 🔴 NOT RUNNABLE | Mounted: `/api/app/friends/*` | Process memory `_FRIEND_REQUESTS` | None; frontend proxy does not allow it | Friend requests/status are in-memory only; no migration or persistence. |
| Attachments | C19 IM | 🔴 NOT RUNNABLE | Mounted: `/api/app/attachments/upload`, `/{message_id}` | None | None; frontend proxy does not allow it | Both upload and fetch return C19G 501 schema/placeholder responses. |
| Communication extensions | C19 IM | 🔴 NOT RUNNABLE | No mounted runtime routes | None | None | C19H is schema-only future API placeholder; not executable. |

### 2. Fully Runnable Functions List

- C01-C05 auth login/logout/me.
- C01-C05 internal user management.
- C01-C05 DB-backed session management.
- C01-C05 permission registry and assignment management.
- C10-C12 approval persistence API.
- C13-C16 security hardening and control-plane isolation.
- C17 operation log API.

### 3. Partially Runnable Functions List

- C01-C05 fixed RBAC role catalog and route checks.
- C06-C09 module registry and module access state.
- C13-C16 webhook gateway validation layer.
- C13-C16 payload standardization and result normalization.
- C17 structured log model/service.
- C17 execution trace model/service.
- C18 organization lifecycle API.
- C18 organization membership API.
- C18 module visibility system.
- C18 permission isolation layer.
- C18 data isolation and org context middleware.
- C19 contact identity system.
- C19 contact directory.
- C19 cross-org communication policy check.

### 4. Non-Runnable Functions List (Mock/Placeholder)

- C01-C05 foundation data loop as real business execution.
- C06-C09 module adapter execution.
- C06-C09 execution provider execution.
- C10 sandbox runner/runtime/bridge.
- C10-C12 execution gating as an actual execution path.
- C13-C16 capability/model/dependency/AI binding controls as runtime controls.
- C13 emergency kill switch as durable control-plane switch.
- C13-C16 workflow registry and module-workflow binding as runtime execution.
- C13-C16 callback handler and failure handling as durable callback/DLQ runtime.
- C13-C16 foundation demo and n8n test bridge as real integration execution.
- C17 event collector as durable observability.
- C17 storage layer.
- C17 audit query engine.
- C17 execution replay.
- C17 anomaly detection.
- C18 module binding.
- C18 shared module binding.
- C19 message system.
- C19 conversation system.
- C19 messaging permission/friends.
- C19 attachments and communication extensions.

### 5. Critical Gaps (P0)

- Missing DB migrations: `organizations`, `org_memberships`, `contact_identities`, `messages`, durable conversations, attachments, friend requests, module bindings, shared modules, callback result store, DLQ, C17 logs/traces/storage/replay/anomaly tables.
- Missing API routes: no real adapter/provider execution endpoint, no live provider router, no production sandbox execution endpoint, no emergency kill-switch control API, no mounted C17 structured-log/trace/replay/anomaly APIs, no implemented message-history/read/attachment APIs.
- Missing frontend integration: no C18 tenant UI, no C19 IM UI, no frontend proxy allowlist for org/contacts/conversations/messages/friends/attachments, no approval console, no operation-log page, and `products`/`settings` are empty states.
- Execution blocked paths: C08 action contracts are mock/no-op only, C09 providers cannot request execution, C10 runtime is `mock_only`, C12 approval does not execute approved actions, C13E validates and blocks unsafe runtime state, C14/C15 layers are read-model/contract oriented, and frontend proxy blocks webhook ingress.
- Mock/demo production risk: foundation demo and n8n test bridge can create successful-looking DB records while explicitly setting demo/mock/no-external-call flags.
- Multi-worker risk: C13 kill switch, C18 module/shared bindings, C19 conversations/friends, C15 callback/DLQ, and C17 buffers diverge across workers and reset on restart.

### 6. Execution Blockers Map

- C08-C15 execution lock points:
  - C08 adapters expose contracts and UI shells but no executable action endpoint.
  - C08 action contracts are constrained to `mock` or `no_op`; bypass before C09 is blocked.
  - C09 provider contracts set `executable=false` and `can_request_execution=false`; future/live providers are placeholders.
  - C10 runtime is `disabled_execution` and `mock_only`; process, network, filesystem, DB writes, staging, and production mutation are explicitly disallowed.
  - C12 approval persists decisions only and states that approved actions are not executed.
  - C13E only validates the sealed contract chain and blocks unsafe runtime/provider states.
  - C14 binding/model/dependency/secret layers are static validation/read models, not live provider controls.
  - C15 workflow registry is read-only, webhook ingress validates but does not dispatch, callback/DLQ stores are in-memory, and recovery replay does not execute.
  - Frontend execution/provider shells expose status but keep request execution disabled.

- C18 isolation blockers:
  - `organizations` and `org_memberships` have models/repositories/services but no Alembic migrations.
  - Module bindings and shared module bindings are process-memory registries.
  - Visibility, permission isolation, and cross-org defaults depend on those memory registries.
  - Frontend proxy does not expose C18 API routes, and no tenant admin UI exists.
  - Production tenant isolation cannot be considered durable until tenant tables and binding tables are migrated.

- C19 IM runtime blockers:
  - `contact_identities` and `messages` lack Alembic migrations.
  - Conversation and friend-request state is process memory only.
  - Message send returns an accepted envelope but does not persist or deliver a message.
  - Message history and read-state endpoints return 501.
  - Attachment upload/fetch endpoints return 501.
  - No websocket/push delivery, media runtime, group chat runtime, or frontend IM surface exists.
  - Cross-org communication depends on incomplete C18/C19 persistence and memory-based module boundaries.

### 7. System Reality Score

- Audited function entries: 42.
- 🟢 FULLY RUNNABLE: 7 / 42 = 16.7%.
- 🟡 PARTIALLY RUNNABLE: 14 / 42 = 33.3%.
- 🔴 NOT RUNNABLE / mock-only / placeholder: 21 / 42 = 50.0%.

Interpretation: the system is strongest as an authenticated internal control-plane foundation. It is not yet a production automation runtime, multi-tenant OS, or IM product.

### 8. Production Readiness Verdict

- Can system run end-to-end? No. Auth, users, permissions, approval records, security middleware, and operation logs can run as foundation services, but C06-C19 do not form an end-to-end executable product path.
- What breaks immediately? Real execution requests have no live route/provider/runtime; C18/C19 DB-backed APIs hit missing migrations in a migration-managed production database; frontend proxy returns 404 for C18/C19 routes; message history/read/attachments return 501; in-memory state is lost or split across workers.
- What is safe? Internal auth, owner-managed users, fixed RBAC checks, permission assignment, DB-backed approval records, security isolation, operation logs, and explicit demo/metadata views when labeled as demo.
- What is unsafe? Presenting module adapters/providers/sandbox as real execution, presenting foundation/n8n demo success as live workflow success, relying on C18 isolation for production tenancy, relying on C19 for messaging, or relying on C17 memory-backed observability for audit/replay/anomaly guarantees.
