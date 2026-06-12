# K06D Backend Test Strategy

Status: K06D backend test strategy draft, pending owner review.

Date: 2026-06-12.

## 1. 当前建议

建议下一步做 K06E backend service-level tests。

K06E should validate the dormant K backend module before any router registration decision. The test slice should focus on module-local behavior and keep K unregistered, disabled by default, and isolated from live services.

K06D only writes this plan. K06D does not create tests.

## 2. K06E 可测试内容

K06E can test:

- models import.
- schemas validation.
- feature flag returns false.
- access disabled behavior.
- scope_shim filters.
- service list/get/create/update/archive with isolated test DB.
- child-resource service behavior for attributes, keywords, and risk terms if the isolated DB fixture is available.
- router object exists but unregistered.
- router module import does not register itself.
- no live provider.
- no n8n.
- no external service.
- no env read.

Recommended first pass:

- Unit tests for `feature_flags.py`.
- Unit tests for `scope_shim.py`.
- Unit tests for `schemas.py`.
- Unit tests for `access.py` disabled behavior.
- Service-level tests for product create/list/get/update/archive using an isolated test DB only if DB setup is explicitly approved for K06E.

## 3. K06E 测试边界

- 只允许 `tests/backend/modules/k_series/product_knowledge/**`.
- 可以使用 isolated Docker project.
- 不碰 staging/production.
- 不读取 env.
- 不连接 live services.
- 不注册 router.
- 不改 `backend/app/main.py`.
- 不改 core config/permissions/deps.
- 不改 frontend.
- 不修改 C series runtime.
- 不修改 P-series workflow JSON.
- 不修改 n8n draft lane.
- 不创建 migration.
- 不修改 existing migration.

If K06E needs any non-test runtime change, it must stop and request a new owner-approved task instead of widening the test task.

## 4. K06E 是否需要数据库

Service-level tests may need a test DB because the K service layer uses SQLAlchemy sessions and the `k_product_knowledge_*` model family.

If DB is needed:

- Use an isolated Docker project.
- Do not connect staging/prod DB.
- Do not run production/staging scripts.
- Do not read production/staging env.
- Do not connect live providers.
- Keep the router unregistered.

If K06E only covers schema/access/unit tests:

- A DB is not required.
- Tests can remain pure Python unit tests around schemas, feature flags, access disabled behavior, and scope shim query construction.

## 5. K06E 输出

Recommended future K06E outputs:

- `tests/backend/modules/k_series/product_knowledge/test_feature_flags.py`
- `tests/backend/modules/k_series/product_knowledge/test_scope_shim.py`
- `tests/backend/modules/k_series/product_knowledge/test_schemas.py`
- `tests/backend/modules/k_series/product_knowledge/test_access_disabled.py`
- Optional service tests under `tests/backend/modules/k_series/product_knowledge/` if isolated DB setup is approved.
- `docs/k_series/K06E_BACKEND_TEST_REPORT.md`

K06D does not create these files.
