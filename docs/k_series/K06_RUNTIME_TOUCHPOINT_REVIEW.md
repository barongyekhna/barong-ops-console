# K06 Runtime Touchpoint Review

Status: K06A read-only runtime touchpoint review, pending owner review.

Date: 2026-06-12.

## 1. 现有 backend 结构观察

Read-only scan commands observed these top-level backend directories:

```text
backend/app/api
backend/app/api/routes
backend/app/cli
backend/app/core
backend/app/db
backend/app/models
backend/app/repositories
backend/app/schemas
backend/app/services
```

API/runtime observations:

- `backend/app/main.py` creates the FastAPI app and manually calls
  `app.include_router(...)` for each route module.
- Existing route files live under `backend/app/api/routes`.
- Existing routers use `APIRouter`, pydantic response models, SQLAlchemy
  sessions from `get_db`, and dependencies from `backend/app/api/deps.py`.
- Current routes do not appear to use a global `/api` prefix in `main.py`.
  Therefore a future K router can define the full prefix
  `/api/k/product-knowledge` inside its own router if approved.
- `backend/app/api/deps.py` provides `get_current_user`, `require_owner`, and
  `require_permission`.
- `require_permission` delegates to `user_has_permission` and owner users pass
  through.
- `backend/app/core/permissions.py` defines permission validation, scope
  constants, and the base permission registry seed. No K permission entries
  were observed.
- `backend/app/core/config.py` uses pydantic settings. No K feature flag was
  observed.
- `backend/app/repositories/operation_logs.py` provides
  `create_operation_log`, `list_operation_logs`, and `get_operation_log`.
- `backend/app/services/foundation_service.py` has `commit_foundation_write`,
  which creates an operation log and commits a write.
- `tests/backend` currently contains flat backend test files, not an existing
  `tests/backend/modules` tree.
- No `backend/app/modules` directory was observed.

## 2. K06B 最小 runtime touchpoints

Future K06B should prefer K-only paths:

```text
backend/app/modules/k_series/product_knowledge/**
tests/backend/modules/k_series/product_knowledge/**
```

Suggested K-only files:

- `backend/app/modules/k_series/product_knowledge/__init__.py`
- `backend/app/modules/k_series/product_knowledge/models.py` or
  `db_models.py`
- `backend/app/modules/k_series/product_knowledge/schemas.py`
- `backend/app/modules/k_series/product_knowledge/router.py`
- `backend/app/modules/k_series/product_knowledge/service.py`
- `backend/app/modules/k_series/product_knowledge/access.py`
- `backend/app/modules/k_series/product_knowledge/scope_shim.py`
- `backend/app/modules/k_series/product_knowledge/feature_flags.py`

Possible non-K touchpoints:

- `backend/app/main.py`: required only if K06B must register the router in the
  running FastAPI app. This is outside the K allowlist and requires owner
  approval.
- `backend/app/core/config.py`: required only if K06B must bind
  `K_PRODUCT_KNOWLEDGE_ENABLED` into the existing pydantic settings. This is
  outside the K allowlist and requires owner approval.
- `backend/app/core/permissions.py` or permission registry seed path: required
  only if K permissions must be registered in core permission bootstrap during
  K06B. This is outside the K allowlist and requires owner approval.
- `backend/app/models/__init__.py` or central model imports: required only if
  SQLAlchemy model discovery needs central imports. This is outside the K
  allowlist and requires owner approval.

If owner approval is not granted for non-K touchpoints, K06B should produce a
disabled, unregistered K module skeleton only.

## 3. 不应触碰的 core runtime

K06B should not touch:

- users
- roles
- permissions core runtime
- auth core runtime
- organizations
- scope
- operation_logs schema
- module registry runtime
- staging/prod config
- Docker production configuration
- frontend runtime
- P-series workflow JSON
- n8n draft lane

K06B must not alter these tables:

- `users`
- `roles`
- `permissions`
- `organizations`
- `operation_logs`

## 4. K06B 风险

- API 路由注册点可能需要小改。
- 权限检查可能需要适配现有 `require_permission` 风格。
- Feature flag 机制可能暂缺。
- Scope adapter 未完成。
- Operation log 写入可能只能 placeholder or existing service call。
- Current permission registry does not include K permission keys; adding them
  to core registry is outside K module paths and requires owner approval.
- Current config has no K flag; adding it to core config is outside K module
  paths and requires owner approval.
- Current backend has no `backend/app/modules` package; K06B may need to create
  that tree under the approved K module path.
- Current tests are flat under `tests/backend`; creating
  `tests/backend/modules/k_series/product_knowledge/**` is allowed only in
  K06B after owner approval and is not part of K06A.

## 5. K06B 建议

Recommended first runtime slice after owner approval:

- disabled-by-default router
- schemas
- service layer
- access shim
- read/list/create/update/archive product
- attributes read/manage
- keywords read/manage
- risk terms read/manage
- no live provider
- no frontend
- no n8n
- no staging/production
- no env read
- no migration

Recommended route registration strategy:

- If owner approves `backend/app/main.py`, include the K router there while the
  router itself still returns disabled responses by default.
- If owner does not approve `backend/app/main.py`, keep the router object inside
  the K module but do not register it.

Recommended operation log strategy:

- Use existing operation log contracts only.
- Do not change `operation_logs` schema.
- For K06B, write operation logs only for create/update/archive/manage actions
  if the existing service call can be used without core rewrites.
- Read endpoints should not write operation logs in the first version.
