# C09D Execution Provider Verification

日期：2026-06-13 UTC

C09D 把 C09B 后端 Execution Provider contract / no-op provider registry 和
C09C 前端 execution status shell / disabled submit state 固化为自动化
verify/test 体系。本阶段只做验证与文档，不实现 runtime execution，不新增
API/UI/migration，不执行 adapter action，不连接 live provider，不发布 staging 或
production，不进入 K01/P 系列。

2026-06-13 C09G 补充：C09 已最终封板，统一封板文档为
`docs/C09_EXECUTION_PROVIDER_SEAL.md`。本文件定义的 verify/test 体系是 C09 sealed
state 的验证基础：Execution Provider Contract v1 冻结，no-op/mock/contract-only model
确认，execution runtime = NO，live provider = NO，execution request system = NO，
queue / worker / webhook = NO。C09G 没有修改 runtime 代码，没有新增测试以外的
API/UI/migration，也没有执行 action 或连接 live provider。

## 做了什么

- 强化 `tests/backend/test_execution_providers_registry.py`，新增 C09D provider
  rule matrix 和负例防回退测试。
- 强化 `tests/frontend/execution-provider.test.mjs`，新增 exact GET-only proxy
  矩阵、Execution Provider action state 矩阵和 status shell 安全展示断言。
- 保留并执行 C08 Module Adapter、C07 Module Isolation、C05/C06 permission
  regression 子集。
- 运行 frontend Node tests、`npm run verify`、`npm run typecheck` 和
  `npm run build`。

本轮没有新增 migration，没有修改 runtime，没有新增 execution submit endpoint，没有
写 operation log/job/artifact，没有读取真实 env，没有连接 n8n/WooCommerce/MinIO/
Filebrowser/live provider，没有执行任何真实业务 action。

## 后端覆盖

`tests/backend/test_execution_providers_registry.py` 覆盖：

- `provider_key` 唯一性和小写 snake_case / dot namespace 命名。
- `provider_version`、`provider_type`、`provider_status`、`lifecycle`、
  execution mode、action type 合法性。
- C07 `module_key`、C08 `adapter_key`、C08 `action_key` binding 存在。
- provider `required_permissions`、`risk_level`、`operation_log_action` 必须继承
  C08 action contract。
- `operation_log_policy.operation_log_action` 必须与 C08 action contract 对齐。
- 所有 provider 均 `executable=false`、`can_request_execution=false`。
- `core.no_op_provider`、`core.mock_provider`、`core.contract_only_provider`、
  future local/queue/webhook/scheduled/live provider 的 access state /
  `block_reason` / `no_execute_reason` 矩阵。
- approval-required / high-risk action 必须等待 C12，且阻断 C09B execution。
- secret-required provider 必须等待 C14，不能声明 secret value、credential 或
  secret read。
- scope-required provider 必须等待 C18，`scope_status=scope_adapter_pending`。
- idempotency/retry/timeout/cancel/concurrency/rate-limit policy 均为
  declared-only，不启用 C09B execution。
- 不允许 live provider connected、external endpoint、callback support、local
  artifact path 或 C09B operation log write。
- `GET /execution-providers/registry` 和 `GET /execution-providers/me` 是
  authenticated read-only API；router 不暴露 POST/PUT/PATCH/DELETE action
  execution endpoint。
- read-only provider calls 不创建 operation logs、jobs 或 artifacts。
- C08/C07/C05/C06 回归：`/module-adapters/*`、`/modules/*`、`/permissions/me`、
  C06B assignments、`/users` owner-only、`/auth/register` 404。

## 前端覆盖

`tests/frontend/execution-provider.test.mjs` 覆盖：

- frontend backend proxy 只精确允许 GET
  `/api/backend/execution-providers/registry` 和 GET
  `/api/backend/execution-providers/me`。
- POST/PUT/PATCH/DELETE 对 execution provider registry paths 均拒绝。
- `/execution-providers/*` wildcard、provider-specific run/execute/submit/cancel/
  retry、`/executions`、`/execution/submit` 均拒绝。
- Execution Provider API client 只调用 safe GET paths。
- frontend public model/normalizer 强制 `executable=false` 和
  `can_request_execution=false`，并清理 unsafe runtime strings。
- action state 矩阵覆盖：
  - execution required / missing provider -> waiting C09。
  - provider contract no-execute -> execution_provider_required。
  - approval required -> waiting C12。
  - secret required -> waiting C14。
  - scope required -> waiting C18。
- `ExecutionProviderStatusShell` 只展示 status/access/no-execute/safe message，
  按钮始终 disabled，且没有 `onClick`、`onSubmit`、`formAction`、`fetch` 或 mutation
  API call。
- `ModuleAdapterShell` 继续 execution-aware but no-execute。

`frontend/scripts/verify-foundation.mjs` 继续作为静态 verifier，检查 C09 execution
provider allowlist、no wildcard、no action route、no live provider marker，并保留
C08/C07/C05/C06 前端回归规则。

## Regression Matrix

本轮回归覆盖：

- C08 Module Adapter：backend registry/access/no-execute tests、
  frontend module-adapter Node tests、adapter shell no mutation。
- C07 Module Isolation：backend module registry tests、frontend module-isolation
  Node tests、navigation/route guard/proxy allowlist。
- C05/C06 permission system：backend permissions API、permission assignments、
  permission service tests；frontend permissions 和 permission-management Node
  tests。
- User management owner-only、Permission Management owner-only、
  `role_default_permissions` 不自动生效、`super_admin` 不默认全局。

## Test Results

本地 `python` 不存在，`python3` 环境没有 pytest；后端验证按项目既有方式使用
`docker-compose.example.yml` 的独立 example project
`barong-ops-console-c09d-test` 执行。

- `docker-compose -p barong-ops-console-c09d-test -f docker-compose.example.yml build backend`：通过。
- `docker-compose -p barong-ops-console-c09d-test -f docker-compose.example.yml run --rm backend python -m alembic -c backend/alembic.ini upgrade head`：通过，仅应用仓库已有 migration 到 example test DB。
- `docker-compose -p barong-ops-console-c09d-test -f docker-compose.example.yml run --rm backend python -m pytest tests/backend/test_execution_providers_registry.py`：通过，`12 passed in 28.70s`。
- `docker-compose -p barong-ops-console-c09d-test -f docker-compose.example.yml run --rm backend python -m pytest tests/backend/test_module_adapters_registry.py tests/backend/test_modules_registry.py tests/backend/test_permissions_api.py tests/backend/test_permission_assignments_api.py tests/backend/test_permissions_service.py`：通过，`46 passed in 58.21s`。
- `node --test tests/frontend/execution-provider.test.mjs`：通过。
- `node --test tests/frontend/permissions.test.mjs tests/frontend/permission-management.test.mjs tests/frontend/module-isolation.test.mjs tests/frontend/module-adapter.test.mjs tests/frontend/execution-provider.test.mjs`：通过，5 个 frontend test files passed。
- `npm run verify`：通过，`Frontend foundation checks passed.`。
- `npm run typecheck`：通过。
- `npm run build`：通过，Next.js production build 成功，生成 18 个静态页面。

## 边界

C09D 没有：

- 新增或修改 migration。
- 新增 execution submit API、execution queue、worker、webhook runtime 或 scheduler。
- 修改 runtime execution provider 行为。
- 执行 adapter action。
- 写真实 operation log/job/artifact。
- 读取或写入真实 env。
- 连接 live provider。
- 发布 staging 或 production。
- 接入 K01 或 P 系列。

## 下一步

C09E staging validation、C09F production-independent final seal 和 C09G unified final
seal 已完成。统一封板文件为 `docs/C09_EXECUTION_PROVIDER_SEAL.md`。

后续阶段不得复用 C09D 测试通过结果来暗示 execution runtime、live provider、execution
request system、queue/worker/webhook 或 adapter action execution 已被批准。任何这些能力都
必须进入新的明确任务并重新验收。
