# K06 Backend CRUD API Skeleton Plan

Status: K06A design draft, pending owner review.

Date: 2026-06-12.

## 1. K06A 目标

K06A only prepares the backend CRUD API skeleton design for the K series
Product Knowledge module.

- K06A 只做 backend CRUD API skeleton 设计。
- K06A 不写 backend runtime。
- K06A 不写 frontend。
- K06A 不写 tests。
- K06A 不创建 migration。
- K06A 是 K06B 的前置审核材料。

K06B may start only after this design is reviewed and the owner explicitly
approves backend runtime skeleton work.

## 2. K06 总体边界

- K API 默认 disabled。
- K API 使用 K Scope Shim。
- K API 不接正式 scope。
- K API 不修改 users / roles / permissions / organizations /
  operation_logs 表结构。
- K API 不连接 live provider。
- K API 不接前端菜单。
- K API 不接 n8n。
- K API 不接 staging/production。
- K API 只服务 K 产品知识库表族。

K06 must remain `scope-adapter-pending` until the relevant C series gates are
complete and the owner approves formal integration.

## 3. 未来允许代码路径

K06B may use these paths only after owner approval:

```text
backend/app/modules/k_series/product_knowledge/**
tests/backend/modules/k_series/product_knowledge/**
```

Current backend observation:

- The repository currently has `backend/app/api`, `backend/app/core`,
  `backend/app/models`, `backend/app/repositories`, `backend/app/schemas`, and
  `backend/app/services`.
- No `backend/app/modules` directory was observed in the K06A read-only scan.
- K06B should create the minimum K module directory only if the owner approves
  backend runtime work.
- Because routers are currently registered manually in `backend/app/main.py`,
  any actual route registration outside the K module path requires owner
  approval. Without that approval, K06B should keep the K router unregistered
  and disabled by default.

## 4. 未来禁止代码路径

K06B must not:

- 不改 users / roles / permissions / organizations / scope core runtime。
- 不改 operation_logs 表结构。
- 不改 C module registry runtime，除非 K24/K25 或老板批准。
- 不改 frontend。
- 不改 P-series。
- 不改 n8n draft lane。
- 不改 staging/production config。
- 不读 env。
- 不修改 existing Alembic migration。
- 不创建新的 migration。
- 不连接 live services。
- 不默认启用 K API。
- 不默认挂前端菜单。
- 不绕过 K Scope Shim。

If K06B needs a file outside `backend/app/modules/k_series/product_knowledge/**`
or `tests/backend/modules/k_series/product_knowledge/**`, that file must be
listed as an explicit runtime touchpoint and approved by the owner before
editing.

## 5. K06B 建议文件拆分

Future backend skeleton files may be split as follows:

```text
backend/app/modules/k_series/product_knowledge/__init__.py
backend/app/modules/k_series/product_knowledge/models.py
backend/app/modules/k_series/product_knowledge/schemas.py
backend/app/modules/k_series/product_knowledge/router.py
backend/app/modules/k_series/product_knowledge/service.py
backend/app/modules/k_series/product_knowledge/access.py
backend/app/modules/k_series/product_knowledge/scope_shim.py
backend/app/modules/k_series/product_knowledge/feature_flags.py
tests/backend/modules/k_series/product_knowledge/test_product_knowledge_api.py
```

Alternative naming:

- `db_models.py` may be used instead of `models.py` if K06B wants to avoid
  confusion with existing global `backend/app/models`.
- `repository.py` may be added later if service code would otherwise mix query
  construction and business validation.

K06A does not create these files.

## 6. K06B 进入条件

K06B may begin only when all conditions are true:

- K06A 文档审核通过。
- 当前 worktree clean。
- 老板明确批准写 backend runtime。
- Codex prompt 明确只允许 K backend module paths。
- API 默认 disabled。
- 不接 frontend。
- 不接 staging/production。
- 不读 production/staging env。
- 不连接 live provider。
- 不接 n8n。
- If router registration in `backend/app/main.py` is needed, the owner must
  explicitly approve that touchpoint because it is outside the K module path.
