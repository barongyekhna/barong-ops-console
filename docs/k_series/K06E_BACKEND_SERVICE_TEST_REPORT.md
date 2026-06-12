# K06E Backend Service Test Report

Status: K06E non-DB backend module contract tests added, pending owner review.

Date: 2026-06-12.

## 1. K06E 目标

K06E creates non-DB unit and contract tests for the dormant K series Product
Knowledge backend module skeleton.

Scope:

- Test module-local feature flag, constants, scope shim, schemas, disabled
  access behavior, router object contract, service callable contract, and model
  table-name contract.
- Do not register the K router.
- Do not modify backend runtime code.
- Do not execute real DB operations.
- Do not connect live providers or workflow systems.

## 2. 创建的测试文件列表

Created under `tests/backend/modules/k_series/product_knowledge/`:

1. `test_feature_flags.py`
2. `test_constants.py`
3. `test_scope_shim.py`
4. `test_schemas.py`
5. `test_access_disabled.py`
6. `test_router_contract.py`
7. `test_service_contract.py`
8. `test_models_contract.py`

## 3. 测试覆盖范围

- Feature flag default:
  `is_k_product_knowledge_enabled()` returns `False`.
- Feature flag source does not import env readers or core config.
- Constants:
  `MODULE_KEY`, `API_PREFIX`, K Scope Shim defaults, K-prefixed permission keys,
  and K-prefixed operation actions.
- Scope shim:
  default context, normalization with defaults, normalization with custom
  values, `where` filter path, and `filter` fallback path.
- Schemas:
  create payload minimum fields, update partial payload, read/list basic fields,
  archive request, attribute/keyword/risk-term patch payloads, and absence of
  provider secret field names.
- Access:
  disabled feature flag denies access and does not default-allow owner role.
  The disabled behavior raises `HTTPException` with module-local
  `KFeatureDisabled` detail.
- Router contract:
  router module imports, `APIRouter` object exists, prefix matches
  `/api/k/product-knowledge`, K06 route paths exist, and router module does not
  call `include_router`.
- Service contract:
  expected service functions exist and are callable, keep `db` as explicit first
  parameter, and are checked only by `inspect.signature` without executing DB
  logic.
- Model contract:
  current 10 SQLAlchemy model classes exist, all `__tablename__` values use the
  `k_product_knowledge_` prefix, product model has `workspace_key`,
  `business_context`, and `scope_mode`, and foreign keys only point inside the K
  table family.
- Live provider touchpoints:
  service layer source has no `n8n`, WooCommerce, Google Sheets, OpenAI,
  DeepSeek, Claude, SERP, WeCom, MinIO, Filebrowser, `requests`, `httpx`, or
  `aiohttp` touchpoints.

## 4. Boundary Confirmation

- 是否修改 backend runtime: no.
- 是否注册 router: no.
- 是否修改 `backend/app/main.py`: no.
- 是否修改 core config: no.
- 是否修改 core permissions: no.
- 是否修改 core auth/deps: no.
- 是否创建 migration: no.
- 是否修改已有 Alembic migration: no.
- 是否运行 Alembic: no.
- 是否连接 Postgres: no.
- 是否运行 staging/production: no.
- 是否读取 env: no.
- 是否连接 live services: no.
- 是否修改 frontend: no.
- 是否修改 P-series workflow JSON: no.
- 是否读取或处理 P-series workflow JSON: no.
- 是否修改 n8n draft lane: no.
- 是否 commit: no.

## 5. py_compile 结果

Command:

```bash
PYTHONPYCACHEPREFIX=/tmp/k06e_pycache python3 -m py_compile \
  tests/backend/modules/k_series/product_knowledge/test_feature_flags.py \
  tests/backend/modules/k_series/product_knowledge/test_constants.py \
  tests/backend/modules/k_series/product_knowledge/test_scope_shim.py \
  tests/backend/modules/k_series/product_knowledge/test_schemas.py \
  tests/backend/modules/k_series/product_knowledge/test_access_disabled.py \
  tests/backend/modules/k_series/product_knowledge/test_router_contract.py \
  tests/backend/modules/k_series/product_knowledge/test_service_contract.py \
  tests/backend/modules/k_series/product_knowledge/test_models_contract.py
```

Result: passed. Exit code 0. No error output.

## 6. Docker / pytest 结果

Docker pre-check command was run:

```bash
docker ps --format '{{.ID}} {{.Names}} {{.Image}} {{.Status}} {{.Command}}'
```

Result:

- No C-series temporary test/build/release container was found.
- Existing long-running prod/staging/dev/live service containers were left
  untouched.

Docker project name:

```text
barong-k-series-product-knowledge-test
```

First exact pytest command:

```bash
docker-compose -p barong-k-series-product-knowledge-test \
  -f docker-compose.example.yml run --rm --no-deps backend \
  sh -c 'pytest tests/backend/modules/k_series/product_knowledge -q'
```

Result: failed before collecting tests because the existing backend image did
not include the newly created K06E test directory.

Observed output:

```text
ERROR: file or directory not found: tests/backend/modules/k_series/product_knowledge
no tests ran in 0.01s
```

Follow-up action:

```bash
docker-compose -p barong-k-series-product-knowledge-test \
  -f docker-compose.example.yml build backend
```

Result: passed. The isolated image was rebuilt and tagged:

```text
barong-k-series-product-knowledge-test_backend:latest
```

Second exact pytest command after rebuild:

```bash
docker-compose -p barong-k-series-product-knowledge-test \
  -f docker-compose.example.yml run --rm --no-deps backend \
  sh -c 'pytest tests/backend/modules/k_series/product_knowledge -q'
```

Result: failed before running K06E tests because pytest loaded
`/app/tests/backend/conftest.py` and the container pytest import path did not
include `/app`.

Observed output:

```text
ImportError while loading conftest '/app/tests/backend/conftest.py'.
tests/backend/conftest.py:5: in <module>
    from backend.app.core.config import Settings, get_settings
E   ModuleNotFoundError: No module named 'backend'
```

No repository config or conftest file was modified. To verify the tests without
changing project test configuration, the command was retried with command-local
`PYTHONPATH=/app`:

```bash
docker-compose -p barong-k-series-product-knowledge-test \
  -f docker-compose.example.yml run --rm --no-deps backend \
  sh -c 'PYTHONPATH=/app pytest tests/backend/modules/k_series/product_knowledge -q'
```

Result: passed.

```text
31 passed in 2.91s
```

Docker cleanup command:

```bash
docker-compose -p barong-k-series-product-knowledge-test \
  -f docker-compose.example.yml down -v
```

Cleanup result: passed.

```text
Removing network barong-k-series-product-knowledge-test_default
```

## 7. 失败/跳过项和原因

- Exact pytest command before image rebuild failed because the backend image was
  stale and did not contain the new test directory.
- Exact pytest command after image rebuild failed before K06E collection because
  pytest's container import path did not include `/app` while loading the
  existing `tests/backend/conftest.py`.
- No K06E test assertion failed.
- No tests were skipped.
- No runtime code, conftest, or pytest config was modified.

## 8. K06F 前的建议

- Review K06E tests before any router registration decision.
- Keep K router unregistered unless owner explicitly approves K06F.
- Keep K API disabled by default unless owner explicitly approves formal module
  switch work.
- If the team wants the exact Docker pytest command to work without
  `PYTHONPATH=/app`, handle that in a separate owner-approved test environment
  task because it may require pytest config, Dockerfile, compose, or conftest
  changes.
- K06F still requires explicit owner approval before touching router
  registration, core config, core permissions, core auth/deps, frontend,
  staging/production, migrations, Postgres, or live services.
