# PRE20-J Multi-Tenant Regression Report

Audit date: 2026-06-17

Scope: C01-C19, frontend, middleware.

Scoring terms:
- PASS: enforced consistently in the audited surface.
- PARTIAL: design or local enforcement exists, but integration is incomplete.
- FAIL: active route/model/service path has no reliable tenant/permission/visibility enforcement.
- N/A: no standalone tenant-facing surface found in this repository.

## 1. Multi-Tenant Consistency Matrix

| System | org_id | permission | visibility | Status |
|---|---|---|---|---|
| C01 Production/bootstrap | N/A | PARTIAL - owner bootstrap is role based | N/A | P1: inherits owner/global permission risk |
| C02 Environment isolation | N/A | N/A | N/A | PASS for environment split; not a tenant isolation layer |
| C03 Owner account management | FAIL - users are global, no org membership boundary in user APIs | PARTIAL - `require_owner` only | PARTIAL - frontend owner-only | P1 |
| C04 RBAC roles | FAIL - role checks do not include org scope | PARTIAL - legacy role/action matrix | N/A | P1 |
| C05 Permission system | PARTIAL - `scope_type/scope_key` supports organization but no hard org binding | PARTIAL - assignments exist, owner wildcard remains global | PARTIAL - menu policy exists | P1 |
| C06 Permission management | PARTIAL - assignment scopes are not checked against actor org membership | PARTIAL - owner-only management, limited API adoption | PARTIAL - frontend consumes permission keys | P1 |
| C07 Module isolation | PARTIAL - module manifests are global/static | PARTIAL - manifests declare permissions | PARTIAL - frontend visibility uses manifests | P1 |
| C08 Module adapter | FAIL - adapter metadata is not org-scoped | PARTIAL - adapter access uses permission manifests | PARTIAL - route/nav bindings exist | P1 |
| C09 Execution provider | FAIL - provider access has no active org enforcement | PARTIAL - permission checks exist, scope adapter pending | PARTIAL - provider visibility can be locked | P1 |
| C10 Sandbox | FAIL - execution context has request scopes but no `org_id` tenant scope | PARTIAL - required permission metadata exists | PARTIAL - sandbox scope is request-local, not tenant-local | P1 |
| C11 Standalone surface | N/A | N/A | N/A | N/A - no standalone C11 implementation found |
| C12 Approval | FAIL - approval tables and APIs have no `org_id` | PARTIAL - legacy governance RBAC | FAIL - approval list/detail are global | P0/P1 |
| C13 Module switch | FAIL - switch state is global/in-memory | PARTIAL - mutation controlled by role paths | FAIL - no per-org switch visibility | P1 |
| C14 Secret/AI/dependency control plane | FAIL - global control-plane metadata | PARTIAL - mostly `require_rbac` admin | PARTIAL - control-plane visibility only | P1 |
| C15 Workflow/callback/results | FAIL - context/result stores are not org-scoped | PARTIAL - execution RBAC exists | PARTIAL - global metadata/results surfaces | P1 |
| C16 Security/control plane | PARTIAL - control plane is isolated from public/app but not tenant-scoped | PARTIAL - role isolation only | PARTIAL - stealth mode protects surface, not tenant visibility | P1 |
| C17 Observability | FAIL - logs/errors/memory tables lack `org_id` and list globally | PARTIAL - AUDIT/admin RBAC | FAIL - observability APIs expose global history to authorized roles | P0 |
| C18 Core multi-tenant | PARTIAL - org/membership exists, C18G only applies to models with `org_id` | PARTIAL - C18F exists but owner bypasses org/module checks | PARTIAL - C18E exists but C18D state is in-memory | P0/P1 |
| C19 IM | PARTIAL - contact identity has `org_id`; conversations/friends are memory-only | PARTIAL - C19E/C19F gates exist, with memory friend state | PARTIAL - global contact directory is intentional but cross-org visible | P1/P2 |
| frontend | FAIL - no active org switch/context, no C18E org visibility integration | PARTIAL - permission guards use C05 keys | PARTIAL - sidebar/route guards exist but can mismatch backend | P1/P2 |
| middleware | PARTIAL - C18H/C18F/C18G exist, but many routes resolve no org context | PARTIAL - middleware C18F only triggers when org/module can be inferred | PARTIAL - no unified route visibility contract | P0/P1 |

Key evidence:
- Middleware is registered in `backend/app/main.py:316-328`; application routes in `backend/app/main.py:335-354` and control-plane routes in `backend/app/main.py:356-375`.
- Only selected models have explicit `org_id`: `OrganizationRecord`, `OrgMembershipRecord`, `ContactIdentityRecord`, and `OrgScopedMixin` (`backend/app/models/base_mixins.py:37-40`, `backend/app/models/organization.py:14`, `backend/app/models/org_membership.py:31`, `backend/app/models/contact_identity.py:21`).
- Core business/observability models lack `org_id`: `AutomationJob`, `Artifact`, `ReviewItem`, `ApprovalRequestRecord`, `OperationLog`, `MemoryEvent`, `SystemError`, `MessageRecord` (`backend/app/models/job.py:16-17`, `backend/app/models/artifact.py:10-11`, `backend/app/models/review.py:10-11`, `backend/app/models/approval.py:13-14`, `backend/app/models/operation_log.py:10-11`, `backend/app/models/memory.py:11-12`, `backend/app/models/error.py:11-12`, `backend/app/models/message.py:9-10`).

## 2. Critical Violations (P0)

1. P0 - org isolation break: major tenant data tables are not tenant-scoped.

   Affected active surfaces:
   - Jobs: `list_jobs()` returns all `AutomationJob` rows without org filtering (`backend/app/repositories/jobs.py:8-16`); route `/api/app/jobs` calls it directly (`backend/app/api/routes/jobs.py:37-40`).
   - Artifacts: `list_artifacts()` returns all artifacts (`backend/app/repositories/artifacts.py:9-17`); route calls it directly (`backend/app/api/routes/artifacts.py:31-34`).
   - Reviews: `list_reviews()` returns all review items (`backend/app/repositories/reviews.py:16-24`); route calls it directly (`backend/app/api/routes/reviews.py:37-40`).
   - Approval: `ApprovalRepository.query_records()` starts with `select(ApprovalRequestRecord)` and filters only status/requester (`backend/app/repositories/approvals.py:129-151`); `ApprovalService.list_approvals()` does not add org scope (`backend/app/services/approval_service.py:455-467`).
   - Observability: operation logs, memory events, and errors list globally (`backend/app/repositories/operation_logs.py:116-133`, `backend/app/repositories/memory.py:10-23`, `backend/app/repositories/errors.py:8-17`).

2. P0 - permission bypass: owner bypass skips C18F org membership and module binding.

   Evidence:
   - API dependency `require_permission()` returns immediately for owner (`backend/app/api/deps.py:188-203`).
   - C18F `check_permission()` returns allowed for owner before checking active membership or module binding (`backend/app/services/permission_isolation.py:282-293`).
   - C18G `OrgDataIsolationLayer.apply_scope()` returns the unfiltered query for owner (`backend/app/services/data_isolation.py:340-347`).

   Impact: an owner role is not limited to the owner user's active org. If an endpoint accepts or derives a different org/module context, C18F allows it and C18G read scoping is disabled.

3. P0 - middleware non-enforcement for routes without org/module context.

   C18F only runs when it can resolve both `org_id` and `module_id`; otherwise it calls the route without a decision (`backend/app/middleware/permission.py:159-187`). C18G only creates a data-isolation context when `_resolve_org_id()` succeeds; otherwise it calls the route without isolation (`backend/app/middleware/data_isolation.py:151-153`). Many active `/api/app` routes such as `/jobs`, `/artifacts`, `/reviews`, `/errors`, `/memory-events`, and `/operation-logs` do not carry `/org/{org_id}` or module context, so they bypass C18F/C18G at middleware level and then query global tables.

4. P0 - visibility leak through backend global data surfaces.

   Frontend may hide or lock modules by C05 permission, but backend list/detail APIs remain globally callable by users satisfying legacy RBAC. This is a backend visibility leak: data can exist and be returned even when no org-specific module visibility grants it.

## 3. High Risk Issues (P1)

1. P1 - multiple permission systems run in parallel.

   The repository has at least three permission layers:
   - Legacy RBAC: `require_rbac()` and `backend/app/core/rbac.py`.
   - C05 scoped assignments: `require_permission()` and `permission_service.user_has_permission()`.
   - C18F org/module/action isolation: `services.permission_isolation.check_permission()`.

   Most business/control APIs still use `require_rbac()` (`backend/app/api/routes/jobs.py:37`, `backend/app/api/routes/artifacts.py:31`, `backend/app/api/routes/reviews.py:37`, `backend/app/api/routes/approval.py:116`, `backend/app/api/routes/memory.py:47`, `backend/app/api/routes/operation_logs.py:23`). C05 assignments are therefore not the authoritative backend gate.

2. P1 - C18D/C18I/C19 state is memory-only.

   In-memory registries:
   - Module bindings: `_MODULE_BINDINGS` (`backend/app/services/module_binding_service.py:33-34`).
   - Shared modules: `_SHARED_MODULES` (`backend/app/services/shared_module_registry.py:49-50`).
   - Conversations: `_DIRECT_CONVERSATION_REGISTRY` (`backend/app/services/conversation_service.py:41`).
   - Friend requests: `_FRIEND_REQUESTS` (`backend/app/services/messaging_permission.py:52-53`).
   - Callback records: `CallbackResultStore._bindings/_records` (`backend/app/services/callback_handler.py:208-209`).
   - Module switch runtime state uses in-memory `_records` (`backend/app/services/module_switch_runtime_gate.py:43-44`).

   Impact: workers can disagree on module visibility, friend status, conversations, callback state, or switch state. Restart loses state. This violates the "no memory-only org state" rule.

3. P1 - C18E visibility is not the frontend's active tenant source.

   C18E exposes `/org/{org_id}/visible-modules` and checks active membership (`backend/app/api/module_visibility.py:45-60`, `backend/app/services/module_visibility_service.py:50-82`). The frontend navigation uses `/modules/me` and static manifests instead (`frontend/src/lib/module-registry-api.ts:107`, `frontend/src/components/console-shell.tsx:38-42`). `/modules/me` itself requires `REGISTRY/admin` (`backend/app/api/routes/modules.py:56`), so normal users fall back to frontend permission-only logic.

4. P1 - global control-plane configuration is not tenant aware.

   Control-plane routes are protected by role (`backend/app/main.py:218-294`) but operate as global metadata. This is acceptable only for true platform-admin surfaces. The current app does not separate platform-admin visibility from tenant-admin visibility.

5. P1 - deliberate `without_org_data_isolation()` usage requires stronger local invariants.

   `without_org_data_isolation()` is used in contact identity, conversation participant resolution, global contact directory, and data-isolation middleware session validation (`backend/app/services/contact_identity_service.py:223`, `backend/app/services/contact_identity_service.py:321`, `backend/app/services/contact_identity_service.py:364`, `backend/app/services/conversation_service.py:79`, `backend/app/services/global_contact_directory.py:82`, `backend/app/middleware/data_isolation.py:182`). Some local checks exist, but this creates a recurring bypass pattern that must be treated as privileged code.

## 4. UI vs Backend Mismatch Report

1. Jobs/artifacts/reviews mismatch.

   Frontend navigation requires C05 keys: `jobs.read`, `artifacts.read`, `reviews.read` (`frontend/src/lib/navigation.ts:141-168`). Backend routes use legacy RBAC: `OPERATIONS/read`, `OPERATIONS/write`, `GOVERNANCE/read`, `GOVERNANCE/write/admin` (`backend/app/api/routes/jobs.py:37-126`, `backend/app/api/routes/artifacts.py:31-60`, `backend/app/api/routes/reviews.py:37-93`). A user can be UI-locked by missing C05 assignment while still passing backend RBAC, or can have a C05 assignment while being blocked by role.

2. Module visibility mismatch.

   Frontend calls `/modules/me` (`frontend/src/lib/module-registry-api.ts:107`), but backend requires `REGISTRY/admin` for that endpoint (`backend/app/api/routes/modules.py:56`). Ordinary users fall back to `moduleAccessUnknown` permission fallback (`frontend/src/lib/module-registry.ts:669-741`), not org-specific C18E visibility.

3. C18E API is not wired to sidebar.

   Backend has `/org/{org_id}/visible-modules` (`backend/app/api/module_visibility.py:45-60`). Frontend does not call that endpoint; no active org switch or active org state is present in `frontend/src`.

4. Backend exists but UI hides or proxy blocks some actions.

   Frontend proxy allows GET list paths for `jobs`, `artifacts`, `reviews`, `errors`, and `memory-events` (`frontend/src/app/api/backend/[...path]/route.ts:15-21`, `frontend/src/app/api/backend/[...path]/route.ts:304`). Backend also has POST/write routes for several of these systems. The proxy reduces UI exposure but does not make backend permission and tenant enforcement consistent.

5. Planned UI modules have no matching tenant-safe backend.

   `products.read` and `settings.read` appear in frontend navigation (`frontend/src/lib/navigation.ts:92`, `frontend/src/lib/navigation.ts:218`) but no tenant-scoped product/settings API was found in the audited backend surfaces.

## 5. Memory/State Leakage Report

1. C18D module binding state is process-local.

   `_MODULE_BINDINGS` stores module-to-org visibility in memory (`backend/app/services/module_binding_service.py:33-34`). C18E and C18F depend on this state for visibility/module binding. In multi-worker deployment, org_1 may see a module on worker A while worker B denies or loses it.

2. C18I shared modules are process-local and synchronized into C18D memory.

   `_SHARED_MODULES` is memory-only (`backend/app/services/shared_module_registry.py:49-50`) and `_sync_c18d_binding()` writes into C18D's in-memory registry (`backend/app/services/shared_module_registry.py:124-125`).

3. C19 conversation and friend state is process-local.

   Conversations use `_DIRECT_CONVERSATION_REGISTRY` (`backend/app/services/conversation_service.py:41`). Friend status uses `_FRIEND_REQUESTS` (`backend/app/services/messaging_permission.py:52-53`). This can leak or lose communication state by worker, and it is not auditable tenant state.

4. C15 callback and C13 switch state are process-local.

   Callback bindings/results are stored in dictionaries (`backend/app/services/callback_handler.py:208-209`). Module switch runtime uses dictionaries (`backend/app/services/module_switch_runtime_gate.py:43-44`). These stores are not keyed by org and are not shared across workers.

5. C17 anomaly/storage layers contain rolling/in-memory state.

   Storage/anomaly components keep process memory state such as `_records` and `_rolling_records` (`backend/app/services/storage_layer.py:354-363`, `backend/app/services/anomaly_detection.py:574`, `backend/app/services/anomaly_detection.py:1340-1343`). These are observability internals, but they should not be treated as tenant-safe persistence.

## 6. Cross-Org Access Analysis

Scenario 1: cross-org data access.

Result: FAIL.

`org_1` and `org_2` separation is not enforceable for core business data because the records do not carry `org_id`. The following APIs can return global data to any caller satisfying legacy RBAC:
- `/api/app/jobs`
- `/api/app/artifacts`
- `/api/app/reviews`
- `/api/app/approval/list`
- `/api/app/errors`
- `/api/app/memory-events`
- `/api/app/operation-logs`

Scenario 3: shared module isolation.

Result: PARTIAL/FAIL.

C18D/C18I correctly model "shared logic does not mean shared data" in schemas and event payloads, but the binding state is memory-only and C18G cannot isolate data for tables that lack `org_id`. Shared module visibility can therefore be inconsistent, and data isolation relies on downstream models that are not tenant-scoped.

Scenario 5: implicit join/global query.

Result: FAIL.

Global queries exist throughout repositories without org conditions. Examples include direct list/select calls for jobs, artifacts, reviews, approvals, logs, memory, and errors. Because the relevant models lack `org_id`, SQLAlchemy loader criteria cannot add a tenant filter.

## 7. Owner Bypass Analysis

Scenario 2: owner bypass.

Result: FAIL.

Owner bypass exists in multiple layers:
- `require_permission()` returns success for owner before assignment lookup (`backend/app/api/deps.py:188-203`).
- C18F owner receives all actions before C18C membership or C18D module binding checks (`backend/app/services/permission_isolation.py:282-293`).
- C18G read scoping is disabled for owner (`backend/app/services/data_isolation.py:340-347`).
- C18H falls back to an owner org when it cannot resolve a single active membership (`backend/app/middleware/org_context.py:231-236`), but this fallback does not constrain C18F/C18G owner access to that org.

Conclusion: owner is a global superuser, not an org owner constrained to `Organization.owner_user_id`. This violates the stated rule that owner must not bypass `org_id` across tenants.

## 8. System-wide Tenant Score

Scoring method: PASS = 1, PARTIAL = 0.5, FAIL = 0. N/A rows are excluded per column.

- org consistency: 19%
- permission consistency: 50%
- visibility consistency: 41%

Overall regression result: FAIL.

Required before this can be considered tenant-safe:
- Add or derive `org_id` for all tenant data records, especially jobs, artifacts, reviews, approvals, logs, memory, errors, messages, and context packets.
- Make backend API authorization use one authoritative permission path that includes org, module, action, and visibility.
- Remove global owner bypass from tenant data access, or separate platform owner from org owner explicitly.
- Persist C18D/C18I/C19/C15/C13 state or mark these systems non-production/non-tenant until persisted.
- Wire frontend visibility to the same backend org/module visibility contract used by APIs.

Verification performed:
- Static audit of backend models, routes, repositories, services, middleware, and frontend guards/proxy/navigation.
- `node --test tests/frontend/module-isolation.test.mjs tests/frontend/permissions.test.mjs`: passed, 2 test files.
- Backend pytest suite was not executed because `pytest` is not installed in the current environment (`pytest: command not found`).
