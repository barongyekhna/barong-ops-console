# K06B Backend Module Skeleton Report

Status: K06B backend module skeleton created, pending owner review.

Date: 2026-06-12.

## 1. K06B 目标

K06B creates the K series Product Knowledge backend module skeleton only.

- K series = Product Knowledge / 白苏婉 2.0.
- Module code exists under the isolated K path.
- Router is not registered in `backend/app/main.py`.
- API is disabled by default through a module-local feature flag.
- No live provider, n8n, WooCommerce, Google Sheets, staging, or production
  integration is connected.

## 2. 创建的 backend module 文件

Created under `backend/app/modules/k_series/product_knowledge/`:

1. `__init__.py`
2. `constants.py`
3. `feature_flags.py`
4. `scope_shim.py`
5. `access.py`
6. `models.py`
7. `schemas.py`
8. `service.py`
9. `router.py`
10. `errors.py`

Parent package marker files were not created:

- `backend/app/modules/__init__.py`: no
- `backend/app/modules/k_series/__init__.py`: no

## 3. Runtime Touchpoint Confirmation

- 是否注册 router: no.
- 是否修改 `backend/app/main.py`: no.
- 是否修改 core config: no.
- 是否修改 core permissions: no.
- 是否修改 core auth/deps: no.
- 是否修改 users / roles / permissions / organizations / scope: no.
- 是否修改 `operation_logs` schema: no.
- 是否连接 live providers: no.
- 是否读取 env: no.
- 是否写 frontend: no.
- 是否写 tests: no.
- 是否创建 migration: no.
- 是否修改已有 Alembic migration: no.
- 是否运行 Docker / Alembic / Postgres / staging / production: no.

## 4. API Disabled-by-default 机制

`feature_flags.py` provides:

```text
is_k_product_knowledge_enabled() -> bool
```

The function returns `False` intentionally and does not read env or core config.

`access.py` checks this flag before fallback access logic. When disabled, it
raises a module-local disabled error mapped to HTTP 404, keeping the dormant API
hidden. Because the router is also unregistered, the API is not reachable from
the FastAPI app in this task.

## 5. K Scope Shim 使用方式

`scope_shim.py` defines the adapter-pending context:

```text
workspace_key = default_independent_store
business_context = independent_store
scope_mode = adapter_pending
```

The service layer uses this context for product list/detail/update/archive and
for child-resource access. Child tables do not carry formal scope fields; they
are reached only after the parent product is found inside the K Scope Shim
boundary.

K06B does not implement formal scope and does not modify users, roles,
permissions, organizations, or core scope.

## 6. Skeleton / TODO 部分

- Router object exists but is not registered.
- Feature flag is a K-local hard-coded disabled default.
- Non-owner K-prefixed permission fallback is a placeholder and does not grant
  access until core permission registry integration is approved.
- Operation log actions are constants only; write hooks are intentionally not
  implemented in K06B.
- Formal module registration waits for C07/C08/C13 and owner approval.
- Formal scope adapter waits for C18 and owner approval.
- Core user trace mapping is not written because current core user ids are int
  while K05 user trace fields are UUID-by-value.
- Provider execution, keyword research live calls, media storage, and P-series
  integration are not implemented.

## 7. K06C 需要老板批准的事项

K06C or later needs explicit owner approval before any of these touchpoints:

- Register the K router in `backend/app/main.py`.
- Add a real K feature flag to `backend/app/core/config.py` or the official
  module switch system.
- Register K permission keys in the core permission registry.
- Wire non-owner K-prefixed permission checks through the official permission
  service.
- Decide how K UUID user trace fields map to current core users.
- Add operation log writes through the existing operation log service.
- Add tests under the approved K test path.
- Connect formal scope adapter after C18.
- Connect any live provider after the required C gates and owner approval.

## 8. 是否建议进入 K06C

Yes, after owner review.

Recommended K06C scope should remain narrow: review this skeleton, decide
whether to add tests or only keep the module dormant, and separately approve any
core runtime touchpoint before registration, config, permission registry, or
formal scope work.
