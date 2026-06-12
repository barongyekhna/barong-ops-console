# K06D C07 Module Isolation Compatibility Review

Status: K06D compatibility review draft, pending owner review.

Date: 2026-06-12.

## 1. K06D 目标

K06D 只审查 K 后端模块如何适配已封板的 C07 模块隔离规则，并输出后续接入决策文档。

K06D 不写 runtime 代码，不注册 router，不修改 `backend/app/main.py`，不修改 core config / permissions / auth / deps，不写 frontend，不写 tests，不创建或修改 migration，不运行 Docker / Alembic / Postgres / staging / production，不读取 env，不连接 live services。

## 2. C07 当前观察

只读检查范围：

- `docs/C07_MODULE_ISOLATION_PLAN.md`
- `docs/MODULE_CONTRACT.md`
- `backend/app/api/routes/modules.py`
- `backend/app/models/registry.py`
- `backend/app/repositories/registry.py`
- `backend/app/schemas/registry.py`
- `backend/app/main.py`
- `backend/app/core/permissions.py`
- `backend/app/core/config.py`
- `backend/app/api/deps.py`
- permission registry / assignment service related files

Current observations:

- module registry 是否存在: PARTIAL. 当前代码存在 `module_registry` / `agent_registry` / `workflow_registry` models、repository、schema，以及 `/modules` foundation registry route。但 `docs/C07_MODULE_ISOLATION_PLAN.md` 明确说明当前 `/modules` 是 foundation registry route，不是 C07 Module Manifest v1 业务模块 API。正式 C07 Module Manifest registry runtime 是否已完成: UNKNOWN。
- module isolation docs 是否存在: yes. `docs/C07_MODULE_ISOLATION_PLAN.md` 和 `docs/MODULE_CONTRACT.md` 存在，并定义 module key、route namespace、API namespace、permission manifest、data boundary、status/lifecycle、external dependency、release gate 等规则。
- module adapter 是否已经存在或是否等待 C08: waits for C08. C07 文档说明 C07 不实现 Module Adapter，C08 才定义模块如何真正接入控制台和 adapter interface。当前只读检查未确认可用的 runtime adapter。
- module switches 是否已经存在或是否等待 C13: waits for C13. C07 文档说明 C13 才定义模块启停、feature flag、模块开关 API/UI 和运行时 enforcement。当前 `backend/app/core/config.py` 未观察到 K 或通用 module switch。
- scope 是否已经存在或是否等待 C18: PARTIAL / waits for C18. 当前 `backend/app/core/permissions.py` 已有 `global`、`module`、`company`、`factory`、`department`、`organization` scope constants 和 assignment scope validation；但 C07 文档说明完整 organization structure / formal scope、scope admin 和组织权限等待 C18。
- router registration 是否有正式模式: PARTIAL / UNKNOWN. 当前 `backend/app/main.py` 采用显式 `app.include_router(...)` 注册现有 routers。C07 文档定义未来业务模块 API namespace 规则，但未在只读检查中确认正式 module-aware router registration registry。
- permission registration 是否有正式模式: PARTIAL / UNKNOWN. 当前 `backend/app/core/permissions.py` 有集中 `BASE_PERMISSION_REGISTRY_SEED`，`permission_service` 通过 `upsert_permission_registry` 写入 permission registry。C07 文档要求未来模块提供 Permission Manifest 并可注册到 `permission_registry`，但未确认正式 module Permission Manifest 自动注册模式已完成。K permission keys 当前未进入 core registry。

## 3. K06B 当前状态

- K backend module path: `backend/app/modules/k_series/product_knowledge/`.
- Router object exists in `backend/app/modules/k_series/product_knowledge/router.py`, but it is not registered in the FastAPI app.
- Feature flag default is disabled: `is_k_product_knowledge_enabled()` returns `False`.
- K feature flag does not read env and does not depend on core config.
- K Scope Shim uses:
  - `workspace_key = default_independent_store`
  - `business_context = independent_store`
  - `scope_mode = adapter_pending`
- K module constants use module-local K-prefixed permissions such as `k.product_knowledge.read`, `k.product_knowledge.create`, `k.product_knowledge.update`, and `k.product_knowledge.archive`.
- Service layer uses K Scope Shim filters for product list/detail/update/archive and child-resource access.
- K models use the isolated `k_product_knowledge_` table family.
- 未改 `backend/app/main.py`.
- 未改 core config.
- 未改 core permissions.
- 未改 core auth/deps.
- 未接 frontend.
- 未接 staging/production.
- 未接 live provider.
- K06C import smoke 已通过 in isolated Docker import smoke, with no Python code changed in K06C.

## 4. K 与 C07 的兼容性判断

| Item | Judgment | Notes |
| --- | --- | --- |
| 代码目录是否符合 C07 模块隔离 | yes for current dormant stage | K code is isolated under `backend/app/modules/k_series/product_knowledge/`. It does not modify C runtime, frontend, or P-series assets. Formal Module Manifest registration is still pending. |
| K table family 是否符合数据库隔离 | yes | K models use `k_product_knowledge_*` tables and avoid core users / roles / permissions / organizations / operation_logs schema changes. User trace fields are UUID-by-value, not FK to core users. |
| K feature flag fallback 是否符合 C07 当前阶段 | yes | Local `feature_flags.py` returns `False` and does not read env. This is compatible with adapter-pending / disabled-by-default, while formal C13 switch integration remains pending. |
| K Scope Shim 是否符合 C07 当前阶段 | yes | The shim keeps K in `scope-adapter-pending` and constrains queries by `workspace_key`, `business_context`, and `scope_mode`. Formal scope integration still waits for C18. |
| K permission constants 是否可以先保留 module-local | yes | Module-local constants are safe while router is unregistered and feature flag is disabled. They must not be treated as effective granted permissions until formal permission registration is approved. |
| K router 是否应该继续 unregistered | yes | Current C07/C08/C13/C18 runtime status does not justify exposing the API path. Keeping it unregistered preserves the dormant boundary. |
| K 是否可以进入 service-level tests | yes | K06E can test imports, schemas, disabled access, scope shim, and service behavior under isolated test DB without router registration or live services. |
| K 是否可以进入 router registration | not recommended now | Router registration touches `backend/app/main.py` or a future router registry and makes a route externally reachable. It needs explicit owner approval and C registration pattern review. |
| K 是否需要等 C08/C13/C18 | yes for formal integration | Formal module adapter waits for C08, module switch / feature flag integration waits for C13, formal scope waits for C18. Service-level tests do not need to wait for those gates if they remain isolated. |

## 5. 结论

Recommended next step: K06E should first do backend service-level tests for the existing dormant K module.

K06F should not immediately register the K router. Router registration is a runtime entry-point decision and should remain blocked unless the owner explicitly approves K06F.

If K router registration is later requested, required preconditions should include:

- K06D reviewed by owner.
- K06E backend tests pass.
- Owner explicitly approves route registration and the exact runtime touchpoints.
- C07 module isolation registration pattern is confirmed.
- C08 Module Adapter status is reviewed.
- C13 module switch / feature flag status is reviewed.
- C18 formal scope status is reviewed, even if K remains shimmed and disabled.
- API remains disabled by default.
- No frontend menu exposure.
- No live provider, no n8n, no staging/production.
- Rollback plan exists for removing the route registration.
