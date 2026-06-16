# PRE20-F Hardcoding Risk Report

Date: 2026-06-16

Mode: static source audit only. No code fix, migration, UI change, production run, or refactor was executed.

Scope covered:

- `backend/app/`: API routes, services, schemas, repositories, middleware, sandbox, core registries.
- `frontend/`: static navigation, proxy allowlists, client libraries, UI fallback metadata.
- `services/`, `schemas/`, `api/`, `repositories/`, `middleware/`, `sandbox/`, `core/`: resolved to implemented paths under `backend/app/`.
- `docs/`: PRE20 and C01-C19 architecture/seal documents used as cross-evidence.
- `tests/`: hardcoded role/org/module/provider fixtures scanned as regression contract evidence.

Risk scale:

- P0 = blocks system scaling or multi-org expansion.
- P1 = blocks feature evolution.
- P2 = maintainability issue.

### 🧱 1. Hardcoded Values Inventory

| Type | Value | Location | Risk |
|---|---|---|---|
| Module hardcoding | `MODULE_MANIFESTS_V1` static tuple | `backend/app/core/modules.py:161` | P0: every new module, page, permission, route namespace, API namespace, dependency, and release policy requires code changes. |
| Module hardcoding | `experimental.foundation_demo` | `backend/app/core/modules.py:186`, `frontend/src/lib/navigation.ts:61`, `frontend/src/app/api/backend/[...path]/route.ts:339` | P1: demo module is wired through backend registry, frontend navigation, and proxy route by name. |
| Module hardcoding | `integration.n8n_test_bridge` | `backend/app/core/modules.py:225`, `backend/app/core/module_adapters.py:1144`, `backend/app/core/workflow_registry.py:9`, `frontend/src/lib/navigation.ts:75` | P1: n8n bridge is a fixed module identity across registry, adapter, workflow, and UI. |
| Module hardcoding | `n8n_test_bridge` without `integration.` namespace | `backend/app/repositories/n8n_test.py:11`, `frontend/src/lib/n8n-test-api.ts:7` | P1: module ID drift from `integration.n8n_test_bridge` can break lookup, audit, binding, or reporting when module IDs become authoritative. |
| Module hardcoding | `business.products` | `backend/app/core/modules.py:546`, `backend/app/core/module_adapters.py:993`, `backend/app/core/execution_providers.py:371`, `frontend/src/lib/navigation.ts:91` | P1: product module is placeholder-bound in multiple layers instead of dynamically registered. |
| Module hardcoding | `business.jobs`, `business.artifacts`, `business.reviews`, `system.*`, `admin.*` fixed module set | `backend/app/core/modules.py:592`, `backend/app/core/modules.py:787`, `frontend/src/lib/navigation.ts:137` | P1: current navigation and access model assume a fixed C-series foundation module catalog. |
| Module hardcoding | `K-series`, `P-series`, `SEO`, `BS` | `backend/app/schemas/module_allocation.py:10`, `backend/app/services/module_allocation_system.py:36` | P1: AI allocation categories are a closed Literal/dict set and block arbitrary module families. |
| Static module binding | `MODULE_SWITCH_REGISTRY_V1` generated from static manifests | `backend/app/core/module_switches.py:27` | P0: switchable modules cannot be added dynamically or per tenant without code deployment. |
| Static module dependency | fixed switch dependency graph | `backend/app/core/module_switches.py:48` | P1: parent/child relationships such as jobs -> n8n/foundation/artifacts/reviews are code-defined. |
| Role hardcoding | `owner`, `admin`, `operator`, `viewer`, `system` permission map | `backend/app/core/rbac.py:19` | P0: RBAC behavior is fixed in code and not tenant/org configurable. |
| Role hardcoding | legacy aliases `super_admin`, `module_admin`, `reviewer`, `bot_agent` | `backend/app/core/rbac.py:31` | P1: role semantics are embedded as aliases, not policy records. |
| Role hardcoding | module permission matrix for `AUTH`, `CORE`, `C09`, `C13`, `K-series`, `P-series`, etc. | `backend/app/core/rbac.py:40` | P1: module/action permissions are fixed lists instead of module-owned permission manifests. |
| Role hardcoding | standard/assignable/unassignable role catalogs | `backend/app/core/roles.py:14`, `backend/app/core/roles.py:26`, `backend/app/core/roles.py:33` | P1: adding a role requires backend code and frontend/test updates. |
| Role hardcoding | owner-only dependency | `backend/app/api/deps.py:130`, `backend/app/api/deps.py:150` | P0: owner remains a privileged global branch for user/permission/module operations. |
| Role hardcoding | control-plane roles `admin`, `system`, `owner` | `backend/app/main.py:72`, `backend/app/main.py:272` | P1: control-plane access cannot be expressed through scoped permissions or tenant policy. |
| Role hardcoding | frontend managed roles `viewer`, `operator`, `reviewer` | `frontend/src/lib/users-api.ts:3` | P1: user creation/update role options are fixed client-side. |
| Role hardcoding | frontend fallback/reserved role metadata | `frontend/src/components/user-management-panel.tsx:48`, `frontend/src/components/user-management-panel.tsx:59` | P2: fallback UI can drift from backend role catalog. |
| Permission hardcoding | base permission seed | `backend/app/core/permissions.py:55` | P1: permission registry is seeded from code, not module install/config or DB-owned policy. |
| Permission hardcoding | high-risk owner full access flags | `backend/app/services/permission_service.py:660`, `backend/app/services/permission_service.py:1454` | P0: owner bypass is duplicated in permission resolution and hard to scope per org. |
| Permission hardcoding | C18F owner bypass | `backend/app/services/permission_isolation.py:282`, `backend/app/services/permission_isolation.py:290` | P0: owner bypasses org membership, module binding, role actions, and module action checks. |
| Permission hardcoding | C18F role action sets | `backend/app/services/permission_isolation.py:28`, `backend/app/services/permission_isolation.py:29`, `backend/app/services/permission_isolation.py:36` | P0: org role capabilities are hardcoded as owner/admin/member action sets. |
| Permission hardcoding | C18F module action rules for `K-series`, `C-series`, `P-series` | `backend/app/services/permission_isolation.py:39` | P0: module family authorization is code-defined and unknown modules fall through to default module actions. |
| Org hardcoding | org ID shape `org_ + uuid4 hex` | `backend/app/schemas/organization.py:12` | P2: stable identifier format is fixed, acceptable as a contract but needs migration if org IDs change. |
| Org hardcoding | module binding org ID shape `org_...` | `backend/app/schemas/module_binding.py:13` | P2: looser C18D org shape differs from C18A org schema and can drift. |
| Org hardcoding | global org sentinel `ALL` | `backend/app/schemas/module_binding.py:9`, `backend/app/schemas/module_binding.py:145` | P0: global visibility uses a magic org marker instead of policy records. |
| Org hardcoding | binding modes `single`, `multi`, `global` | `backend/app/schemas/module_binding.py:15` | P1: org-module sharing modes are closed and not extensible without schema/code changes. |
| Org hardcoding | C18D binding store `_MODULE_BINDINGS` | `backend/app/services/module_binding_service.py:33` | P0: tenant/module visibility is process memory and cannot scale across workers or restarts. |
| Org hardcoding | owner fallback org context | `backend/app/middleware/org_context.py:210`, `backend/app/middleware/org_context.py:230` | P0: owner org resolution has special fallback paths outside explicit active-org context. |
| Org hardcoding | active org required for multi-org users | `backend/app/services/module_visibility_service.py:80` | P1: no dynamic default active-org policy exists for multi-org UX/API calls. |
| Org hardcoding | tests fixed to `org_1`, `org_2`, `org_3` | `tests/backend/test_module_binding_system.py:167`, `tests/backend/test_permission_isolation_layer.py:175`, `tests/backend/test_module_visibility_system.py:140` | P2: regression suite encodes a narrow tenant fixture model. |
| Provider hardcoding | provider contracts static tuple | `backend/app/core/execution_providers.py:369` | P0: provider registry is not dynamic, installable, or DB/config backed. |
| Provider hardcoding | `core.no_op_provider`, `core.mock_provider`, `core.contract_only_provider` | `backend/app/core/execution_providers.py:371`, `backend/app/core/execution_providers.py:392`, `backend/app/core/execution_providers.py:413` | P0: execution provider universe is fixed to safe/no-execute shells. |
| Provider hardcoding | `future.local_backend_provider`, `future.queue_provider`, `future.webhook_provider`, `future.scheduled_provider`, `future.live_provider` | `backend/app/core/execution_providers.py:434`, `backend/app/core/execution_providers.py:451`, `backend/app/core/execution_providers.py:469`, `backend/app/core/execution_providers.py:487`, `backend/app/core/execution_providers.py:505` | P0: future provider names are statically declared placeholders, not real registry entries. |
| Provider hardcoding | `executable=False`, `can_request_execution=False`, `live_provider_connected=False`, `external_endpoint_declared=False` | `backend/app/core/execution_providers.py:361` | P0: all current providers are globally blocked from execution. |
| Provider hardcoding | blocked provider statuses and future provider type sets | `backend/app/services/execution_flow_gate.py:22`, `backend/app/services/execution_flow_gate.py:31` | P0: C13E blocks provider classes by hardcoded status/type lists. |
| Provider hardcoding | dependency binding `integration.n8n_test_bridge -> n8n` disabled/no capability | `backend/app/core/dependency_bindings.py:6`, `backend/app/core/dependency_bindings.py:16` | P1: n8n provider relationship is fixed and disabled by default. |
| Provider hardcoding | external service/provider registry empty | `backend/app/core/external_dependencies.py:6` | P1: no dynamic external provider catalog exists. |
| Execution hardcoding | adapter safe execution types `mock`, `no_op` | `backend/app/services/module_adapter_registry.py:42` | P0: C08 adapter validation rejects non-mock/non-no-op actions. |
| Execution hardcoding | C13E only allows adapter `mock` or `no_op` | `backend/app/services/execution_flow_gate.py:357` | P0: real/async execution cannot pass the final gate. |
| Execution hardcoding | C13E blocks executable/live/external/callback providers | `backend/app/services/execution_flow_gate.py:394`, `backend/app/services/execution_flow_gate.py:396`, `backend/app/services/execution_flow_gate.py:398` | P0: live execution path is structurally blocked. |
| Execution hardcoding | C10 runtime mode `disabled_execution` and capability `mock_only` | `backend/app/sandbox/runtime.py:32`, `backend/app/sandbox/runtime.py:33` | P0: sandbox runtime cannot become a real execution engine by configuration. |
| Execution hardcoding | C10 runtime cannot unlock execution | `backend/app/sandbox/runtime.py:265` | P0: constructor rejects `execution_locked=False`. |
| Execution hardcoding | runner mode `deterministic_mock` and capability `mock_lifecycle_simulation` | `backend/app/sandbox/runner.py:36`, `backend/app/sandbox/runner.py:37` | P0: sandbox runner only simulates lifecycle. |
| Execution hardcoding | bridge modes are mock-only | `backend/app/sandbox/bridge.py:26`, `backend/app/sandbox/bridge.py:48` | P0: C10E bridge has no staging/live execution mode. |
| Execution hardcoding | `run_foundation_demo` fixed demo flags | `backend/app/services/foundation_demo_service.py:338` | P1: successful records are demo-only and not business tasks. |
| Execution hardcoding | `run_n8n_test` blocks external HTTP | `backend/app/services/n8n_test_service.py:286`, `backend/app/services/n8n_test_service.py:288`, `backend/app/services/n8n_test_service.py:385` | P1: n8n bridge cannot evolve into staging/live dispatch without replacing inline lock logic. |
| Execution hardcoding | n8n mock terminal status `completed_demo` | `backend/app/services/n8n_test_service.py:55`, `backend/app/services/n8n_test_service.py:482` | P1: status semantics are demo-specific. |
| API route hardcoding | backend public/app/control-plane prefixes | `backend/app/main.py:69`, `backend/app/main.py:70`, `backend/app/main.py:71` | P1: route segmentation is code-defined and mirrored in frontend proxy. |
| API route hardcoding | backend router include list | `backend/app/main.py:331` through `backend/app/main.py:375` | P1: every new API must be explicitly mounted in code. |
| API route hardcoding | frontend proxy allowlists | `frontend/src/app/api/backend/[...path]/route.ts:7` through `frontend/src/app/api/backend/[...path]/route.ts:130` | P1: frontend access to backend routes is hardcoded and will 404 new APIs unless manually updated. |
| API route hardcoding | frontend blocked security paths `webhook`, `n8n`, `webhook-gateway/ingress` | `frontend/src/app/api/backend/[...path]/route.ts:133`, `frontend/src/app/api/backend/[...path]/route.ts:137` | P1: route blocks are path-string based rather than capability/policy based. |
| API route hardcoding | hardcoded demo/n8n proxy paths | `frontend/src/app/api/backend/[...path]/route.ts:339` | P1: demo endpoints are manually special-cased. |
| Frontend navigation hardcoding | `navigationGroups` static array | `frontend/src/lib/navigation.ts:44` | P0: sidebar/nav does not derive from backend module registry, so module expansion requires frontend code changes. |
| Frontend navigation hardcoding | `foundation-demo`, `n8n-test`, `products` menu entries | `frontend/src/lib/navigation.ts:61`, `frontend/src/lib/navigation.ts:72`, `frontend/src/lib/navigation.ts:88` | P1: demo/test/placeholder UI entries are hardwired. |
| Frontend navigation hardcoding | embedded permission management module under `/users` | `frontend/src/lib/navigation.ts:230` | P1: admin permissions UI is hard-bound to user management route. |
| Frontend provider hardcoding | provider type/status enums include mock/future live values | `frontend/src/lib/execution-provider.ts:3`, `frontend/src/lib/execution-provider.ts:26`, `frontend/src/lib/execution-provider.ts:272` | P1: frontend provider model must change for real provider types/modes. |
| Frontend adapter hardcoding | staging/production readiness labels and P/K pattern guards | `frontend/src/lib/module-adapter.ts:283`, `frontend/src/lib/module-adapter.ts:1256` | P2: frontend safety guards encode specific module naming families. |
| Workflow hardcoding | `WORKFLOW_REGISTRY_V1` static n8n workflows | `backend/app/core/workflow_registry.py:7` | P1: C15A workflow universe is code-defined and currently only n8n test bridge. |
| Workflow hardcoding | C15F whitelist field `allowed_workflows` | `backend/app/schemas/module_workflow_binding.py:107`, `backend/app/services/module_workflow_binding_engine.py:343` | P1: workflow access is static whitelist based and not provider-router driven. |
| Result hardcoding | product/n8n/fallback normalization heuristics | `backend/app/services/result_normalization.py:37`, `backend/app/services/result_normalization.py:194`, `backend/app/services/result_normalization.py:452` | P1: normalization recognizes product/n8n structures through hardcoded names and field paths. |
| Storage/runtime hardcoding | C18 shared modules memory registry | `backend/app/services/shared_module_registry.py:49`, `backend/app/services/shared_module_registry.py:124` | P0: shared-module state mutates private C18D memory and is not durable. |
| Storage/runtime hardcoding | C19 conversation registry | `backend/app/services/conversation_service.py:41` | P0: conversation identity/state is process-local. |
| Storage/runtime hardcoding | C19 friend request registry | `backend/app/services/messaging_permission.py:52` | P0: friendship permissions are process-local. |
| Docs hardcoding | provider mode examples for `K-series`, `C-series`, `P-series`, `business.products`, `experimental.foundation_demo` | `docs/PRE20_D_PROVIDER_SWITCH_ARCHITECTURE.md:299`, `docs/PRE20_D_PROVIDER_SWITCH_ARCHITECTURE.md:317` | P2: design examples encode module-family provider policy and can become copied implementation rules. |
| Docs hardcoding | C14X-D module allocation categories `K-series`, `P-series`, `SEO`, `BS` | `docs/C14X_D_MODULE_ALLOCATION_SYSTEM.md:17` | P2: documentation mirrors the closed module category set found in code. |
| Docs hardcoding | C07 module registry names `experimental.foundation_demo`, `integration.n8n_test_bridge`, `business.products` | `docs/C07_MODULE_REGISTRY_BACKEND.md:119`, `docs/C07_MODULE_REGISTRY_BACKEND.md:127` | P2: seal docs preserve fixed initial module identities and can anchor future work to those names. |
| Environment hardcoding | production-like env set `production`, `prod`, `staging` | `backend/app/main.py:73`, `backend/app/core/session_cookies.py:7`, `backend/app/core/security_headers.py:5` | P1: environment class behavior is hardcoded in three places. |
| Environment hardcoding | default `app_env=development` | `backend/app/core/config.py:18` | P2: safe default is fine but config policy is local to Settings. |
| Environment hardcoding | cookie path `/api/backend` | `backend/app/core/config.py:29`, `backend/app/core/config.py:91` | P2: frontend proxy path is embedded in auth cookie defaults. |
| Environment hardcoding | frontend backend URL env names | `frontend/src/app/api/backend/[...path]/route.ts:151` | P2: only `BACKEND_API_URL` / `NEXT_PUBLIC_API_BASE_URL` are supported. |
| Environment hardcoding | compose env files and network names | `docker-compose.staging.yml:6`, `docker-compose.production.yml:6`, `docker-compose.example.yml:25` | P2: deploy topology names are static and require manual expansion for additional environments. |

### ⚠️ 2. Critical Hardcoding (P0)

1. Static module system blocks dynamic module expansion.
   Evidence: `MODULE_MANIFESTS_V1` in `backend/app/core/modules.py:161`, switch registry generated from it in `backend/app/core/module_switches.py:27`, static frontend navigation in `frontend/src/lib/navigation.ts:44`.
   Impact: adding a module requires coordinated backend registry, switch graph, permissions, adapter, route, proxy, and frontend edits. No module install/config/DB registry exists.

2. C18 module/org visibility is not durable.
   Evidence: `_MODULE_BINDINGS` in `backend/app/services/module_binding_service.py:33`, `runtime_storage="process_memory_registry"` in `backend/app/schemas/module_binding.py:146`, shared modules mutating private C18D memory in `backend/app/services/shared_module_registry.py:124`.
   Impact: multi-worker and restart behavior splits tenant/module visibility, so multi-org expansion cannot be trusted.

3. Owner bypass is embedded across org and permission layers.
   Evidence: `require_owner` in `backend/app/api/deps.py:130`, C18F owner bypass in `backend/app/services/permission_isolation.py:282`, owner full access flags in `backend/app/services/permission_service.py:660`, org lifecycle owner-only rule in `backend/app/schemas/organization.py:617`.
   Impact: owner is a global override, not a scoped policy. Delegated org admins, regional owners, reseller owners, service owners, or future org types cannot be modeled safely.

4. C18F module action rules are hardcoded by module family.
   Evidence: `K-series`, `C-series`, `P-series` rules in `backend/app/services/permission_isolation.py:39`; default module actions in `backend/app/services/permission_isolation.py:49`.
   Impact: new module families either receive broad default actions or require code changes before permissions are accurate.

5. Provider registry and provider execution state are static and no-execute.
   Evidence: `EXECUTION_PROVIDER_CONTRACTS_V1` in `backend/app/core/execution_providers.py:369`; `executable=False`, `can_request_execution=False`, `live_provider_connected=False` in `backend/app/core/execution_providers.py:361`.
   Impact: no provider can be added, activated, or moved to live by registry/config/DB policy.

6. C13E and C10 force execution to mock/no-op.
   Evidence: C13E allows only `mock`/`no_op` adapter actions in `backend/app/services/execution_flow_gate.py:357`; C10 runtime is `disabled_execution`/`mock_only` in `backend/app/sandbox/runtime.py:32`; unlock is rejected in `backend/app/sandbox/runtime.py:265`.
   Impact: new execution engines, live n8n dispatch, queues, schedulers, and real sandboxes cannot pass the current runtime path.

7. Frontend navigation is static and not backend registry driven.
   Evidence: `navigationGroups` in `frontend/src/lib/navigation.ts:44`.
   Impact: new modules can exist in backend but remain unreachable or misrepresented in the UI until frontend code changes.

8. C19 communication state is process-local.
   Evidence: `_DIRECT_CONVERSATION_REGISTRY` in `backend/app/services/conversation_service.py:41`, `_FRIEND_REQUESTS` in `backend/app/services/messaging_permission.py:52`.
   Impact: multi-org communication and permissions cannot scale beyond one process.

### 🔥 3. High Risk Hardcoding (P1)

1. Frontend proxy uses route allowlists.
   Evidence: allowlist sets in `frontend/src/app/api/backend/[...path]/route.ts:7` through `frontend/src/app/api/backend/[...path]/route.ts:130`.
   Risk: new backend APIs return frontend 404 until manually added; C18/C19 APIs can be mounted but inaccessible through the console.

2. Backend router mounting is a single fixed list.
   Evidence: `app.include_router(...)` block in `backend/app/main.py:331` through `backend/app/main.py:375`.
   Risk: API expansion is centralized and code-bound, not module registration driven.

3. Module ID drift exists for n8n bridge.
   Evidence: registry/UI use `integration.n8n_test_bridge`; repository/API payloads use `n8n_test_bridge` in `backend/app/repositories/n8n_test.py:11` and `frontend/src/lib/n8n-test-api.ts:7`.
   Risk: future module binding, audit, permission, and workflow ownership can split under two IDs.

4. Workflow registry is fixed to n8n test bridge.
   Evidence: `WORKFLOW_REGISTRY_V1` in `backend/app/core/workflow_registry.py:7`.
   Risk: new workflows require code changes and C15F whitelist updates.

5. AI/module allocation categories are closed.
   Evidence: `ModuleAllocationModuleId = Literal["K-series", "P-series", "SEO", "BS"]` in `backend/app/schemas/module_allocation.py:10`, `MODULE_CATEGORY_CAPABILITIES` in `backend/app/services/module_allocation_system.py:36`.
   Risk: new AI module families cannot be configured without code/schema changes.

6. Static permission seed blocks module-owned permissions.
   Evidence: `BASE_PERMISSION_REGISTRY_SEED` in `backend/app/core/permissions.py:55`.
   Risk: new modules cannot ship permissions independently.

7. Control-plane roles are hardcoded.
   Evidence: `CONTROL_PLANE_ROLES = ("admin", "system", "owner")` in `backend/app/main.py:72`.
   Risk: scoped permission assignments cannot govern control-plane access.

8. Demo/test bridge routes are special-cased.
   Evidence: `foundation-demo/run`, `foundation-demo/latest`, `n8n-test/run`, `n8n-test/latest` in `frontend/src/app/api/backend/[...path]/route.ts:339`.
   Risk: test/demo routes get first-class treatment while future real module routes require manual additions.

9. Result normalization depends on product/n8n heuristics.
   Evidence: wrapper keys `raw_output`, `n8n_output` in `backend/app/services/result_normalization.py:37`; product name checks in `backend/app/services/result_normalization.py:194`.
   Risk: new provider result shapes need code updates instead of schema registry mappings.

10. Environment classification is duplicated.
    Evidence: production env sets in `backend/app/main.py:73`, `backend/app/core/session_cookies.py:7`, and `backend/app/core/security_headers.py:5`.
    Risk: adding `preview`, `qa`, `canary`, or region-specific envs requires multiple code edits and can drift.

### 🟡 4. Medium Risk Hardcoding (P2)

1. Test fixtures hardcode `org_1`, `org_2`, `org_3`.
   Evidence: `tests/backend/test_module_binding_system.py:167`, `tests/backend/test_module_visibility_system.py:140`, `tests/backend/test_permission_isolation_layer.py:175`.
   Impact: tests prove intended behavior but can overfit org scenarios.

2. Frontend fallback role metadata duplicates backend role catalog.
   Evidence: `frontend/src/components/user-management-panel.tsx:59`.
   Impact: UI can display stale role semantics when backend role definitions change.

3. Frontend managed roles are fixed.
   Evidence: `frontend/src/lib/users-api.ts:3`.
   Impact: role creation/edit UX lags backend role policy.

4. Static URL/env variable names are limited.
   Evidence: `frontend/src/app/api/backend/[...path]/route.ts:151`.
   Impact: additional backend endpoints or service discovery modes need code changes.

5. Cookie path is fixed to `/api/backend` by default.
   Evidence: `backend/app/core/config.py:29`, `backend/app/core/config.py:91`.
   Impact: auth coupling to current Next.js proxy path must be coordinated for route topology changes.

6. Security headers and blocked proxy paths are string-policy based.
   Evidence: CSP/HSTS in `backend/app/core/security_headers.py:7`, proxy path blocks in `frontend/src/app/api/backend/[...path]/route.ts:133`.
   Impact: acceptable security constants, but routing/security policy is not centralized.

7. Compose environment names are fixed.
   Evidence: `.env.staging` in `docker-compose.staging.yml:6`, `.env.production` in `docker-compose.production.yml:6`.
   Impact: additional deploy tiers require new compose files or templating.

### 🧠 5. Architecture Flexibility Score

- module flexibility %: 25%
  - Reason: backend has structured module manifests and switch policy evaluation, but the source of truth is static code and frontend navigation/proxy are not registry-driven.

- provider flexibility %: 10%
  - Reason: provider contracts are well-shaped but static, all current providers are no-execute, and C13E/C10 block live/staging execution classes.

- org flexibility %: 35%
  - Reason: org and membership schemas exist, but C18D bindings/shared modules are process-memory, `ALL` is a magic global sentinel, owner bypass is global, and active-org behavior has special fallbacks.

- execution flexibility %: 5%
  - Reason: C08/C09/C10/C13 explicitly enforce mock/no-op/disabled execution. PRE20-D architecture describes a future router, but current code has no dynamic provider router.

### 🚨 6. Expansion Blockers

- where new modules will break
  - Backend module registry: `backend/app/core/modules.py:161` must be edited.
  - Module switch graph: `backend/app/core/module_switches.py:27` and dependency/group policies must be updated.
  - Permissions: `backend/app/core/permissions.py:55` and C18F module rules in `backend/app/services/permission_isolation.py:39` may need edits.
  - Adapters/providers/workflows: `backend/app/core/module_adapters.py:494`, `backend/app/core/execution_providers.py:369`, and `backend/app/core/workflow_registry.py:7` are static.
  - Frontend: `frontend/src/lib/navigation.ts:44` and proxy allowlists in `frontend/src/app/api/backend/[...path]/route.ts:7` must be changed.

- where new org types will break
  - Owner lifecycle: `backend/app/schemas/organization.py:617` denies all org management unless user is the owner user.
  - C18F role model: `backend/app/services/permission_isolation.py:28` through `backend/app/services/permission_isolation.py:39` only understands fixed role/module action sets.
  - Module binding: `backend/app/schemas/module_binding.py:15` only supports single/multi/global with `ALL`.
  - Active org context: `backend/app/services/module_visibility_service.py:80` has no configurable default-selection policy for multi-org users.

- where new providers will break
  - Provider registry: `backend/app/core/execution_providers.py:369` must be edited.
  - Provider type/status gates: `backend/app/services/execution_flow_gate.py:22` and `backend/app/services/execution_flow_gate.py:31` may block new provider classes.
  - Execution flags: `backend/app/core/execution_providers.py:361` force all providers to no-execute.
  - External dependency registry: `backend/app/core/external_dependencies.py:6` is empty/static.
  - Frontend provider model: `frontend/src/lib/execution-provider.ts:3` and `frontend/src/lib/execution-provider.ts:26` need enum updates.

- where new execution engines will break
  - Adapter validation: `backend/app/services/module_adapter_registry.py:42` accepts only `mock` and `no_op`.
  - C13E gate: `backend/app/services/execution_flow_gate.py:357`, `backend/app/services/execution_flow_gate.py:394`, `backend/app/services/execution_flow_gate.py:396` reject real/executable/live/callback paths.
  - C10 runtime: `backend/app/sandbox/runtime.py:32`, `backend/app/sandbox/runtime.py:265` permanently lock execution.
  - C10 bridge/runner: `backend/app/sandbox/bridge.py:48`, `backend/app/sandbox/runner.py:36` are mock-only.
  - C15 workflow and result layers: `backend/app/core/workflow_registry.py:7` and `backend/app/services/result_normalization.py:194` are hardcoded around current n8n/product shapes.

### 🔧 7. Refactor Required Map

- must convert to config
  - Environment class policy: `PRODUCTION_LIKE_ENVS` / `PRODUCTION_ENVS`.
  - Cookie/proxy path coupling: default `/api/backend`.
  - Frontend backend URL resolution and deploy environment names.
  - Security proxy blocked-path policy if more public ingress classes are added.

- must convert to registry
  - Module manifests, navigation metadata, route namespaces, feature flags, release requirements.
  - Module switch dependency/group/inheritance policy.
  - Provider contracts and provider type/status capabilities.
  - Workflow registry, module-workflow bindings, result-normalization mappings.
  - AI module allocation categories and capability budgets.
  - Permission definitions and module-owned permission manifests.

- must convert to DB
  - C18D module bindings and shared modules.
  - C19 conversations, friend requests, message state, read state, attachments.
  - C13 emergency kill switch if it must be cluster-wide.
  - C15 callback context/results and DLQ.
  - C17 audit/event/storage/anomaly state if used for production operations.
  - Role policy, org role grants, scoped owner/delegation records.

- must remain constant
  - Public/app/control-plane route boundary names, unless a versioned API gateway replaces them.
  - Security header defaults and sensitive marker deny-lists, with centralized ownership.
  - Stable ID format validators after migration contract is decided.
  - Safe default execution posture: no silent fallback from live/staging to mock.
  - High-risk operation requiring explicit approval and audit policy.
