# C07D Module Isolation Verification

日期：2026-06-11 UTC

C07D 把 C07A/C07B/C07C 的模块隔离规则固化为自动测试和只读 verifier。C07D
只做 verify/test 体系，不开发业务功能，不实现 Module Adapter，不实现 Execution
Provider，不实现 module switch，不新增后端业务 API，不新增前端业务 UI，不新增
migration，不接 K01/P 系列，不接 n8n/WooCommerce/MinIO/Filebrowser，不发布
staging 或 production。

2026-06-11 C07E 补充：staging 模块隔离验收已归档在
`docs/C07_MODULE_STAGING_ACCEPTANCE.md`。C07E 使用本文件的测试/verifier 作为
staging 发布前后检查矩阵：frontend `verify/typecheck/build` 和三组 Node tests 通过；
Docker 后端最小测试 `tests/backend/test_modules_registry.py`,
`tests/backend/test_permissions_api.py`, `tests/backend/test_permission_assignments_api.py`
通过；发布后 staging/production smoke、dual env status 和 safe release plan 通过。
C07E 未执行 Alembic，未操作 postgres，未发布 production，未读取真实 env，未接真实业务。

## 做了什么

C07D 强化三类自动化检查：

- 后端 `tests/backend/test_modules_registry.py`：Module Manifest v1 contract、
  registry 安全元数据、access state 和 C05/C06 回归。
- 前端 `tests/frontend/module-isolation.test.mjs`：navigation module_key、
  module access helper、route guard、proxy allowlist、安全降级和 C05/C06 helper 回归。
- `frontend/scripts/verify-foundation.mjs`：只读检查 C07 proxy、navigation、C07C
  helper/provider/test 文件、K01/P 系列菜单禁用和真实外部接入禁用。

这些检查都不访问网络、不读真实 env、不连接 database、不调用 production/staging。

## 后端 contract 校验

后端 registry contract 测试覆盖：

- 每个 manifest 必须包含 Module Manifest v1 必填字段。
- `module_key` 必须唯一，并符合小写 dot namespace 规则。
- `category`、`status`、`lifecycle`、`denied_behavior` 必须合法。
- business 模块必须使用 `show_locked`。
- admin/system 模块必须使用 `hide_when_denied`。
- `route_namespace` 必须存在并以 `/` 开头。
- `api_namespace` 必须存在，或通过 `no_api=true` 和 `api_namespace="no_api"`
  明确声明无 API。
- `required_permissions` 必须出现在同模块 `permission_manifest` 中。
- permission key 必须符合 `module.action` 格式，不能使用 `product`、`task`、
  `automation`、`manage_all` 这类泛名。
- permission manifest 的 `module_key`、`category`、`menu_policy` 必须和模块一致。
- `external_dependencies` 只能是安全依赖名，不允许 secret、token、password、
  credential、env、URL、API key 或 provider URL。
- `planned`、`adapter_pending`、`unavailable` 不会返回 executable access。
- K01 不在当前 runtime registry；若未来进入，只能保持 adapter_pending/disabled/
  hidden/unavailable，不得 enabled/executable。
- P 系列真实业务模块不得在 C07D 注册为 enabled/executable。
- `integration.n8n_test_bridge` 只能是 test/integration bridge，保持
  `adapter_pending`，不得表示真实 n8n 接入。
- registry 序列化结果不能包含 `.env.production`、`.env.staging`、provider URL、
  webhook secret、API key、Bearer token 或真实域名。

后端 access state 回归覆盖：

- owner full access 可以看到 admin/system。
- non-owner 无显式授权时 admin/system 为 hidden。
- business 无权限时 visible + locked。
- `role_default_permissions` 不自动生效。
- `super_admin` 不默认全局可见 admin/system。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。
- `/permissions/me` 不被破坏。
- C06B assignment API 不被破坏。

## 前端测试

前端 module isolation 测试覆盖：

- 每个 navigation record 必须有 `module_key`，或未来显式 core exception。
- navigation `module_key` 必须存在于 mock/known registry。
- User Management 映射 `admin.users`。
- Permission Management 映射 `admin.permissions`，仍是 `/users` 内 owner-only panel。
- `admin.users` 和 `admin.permissions` 对 non-owner 隐藏，对 owner 可见。
- business 模块无权限时 locked/show_locked。
- planned、adapter_pending、unavailable 模块显示不可用状态，不能 enter。
- missing module access state 或 `/modules/me` 失败时安全降级，不向 non-owner 暴露
  admin/system。
- `external_dependencies` 归一化后只保留安全名称，展示数据不得包含 secret、token、
  password、credential、env、URL。
- wildcard permission 不能绕过模块 access state、owner-only 或 locked/hidden 状态。
- `role_default_permissions` 不自动生效、`super_admin` 不默认全局的 C05/C06 假设保留。
- C05D `permissions.test.mjs` 和 C06C `permission-management.test.mjs` 继续作为回归矩阵。
- `ModuleRouteGuard` 的 hidden、locked、unavailable、owner path decision 可用纯 helper
  测试。
- `ModuleUnavailable` 和 `No Permission` 文案不暴露内部凭据。

## Proxy allowlist

`frontend/scripts/verify-foundation.mjs` 现在检查：

- backend proxy 精确包含 `GET /modules/registry`。
- backend proxy 精确包含 `GET /modules/me`。
- C07 module allowlist 只有 `modules/registry` 和 `modules/me`。
- 不允许 `/modules/*`、`requestedPath.startsWith("modules/")` 或 module API 宽通配。
- `/permissions/me` 和 `/permissions/registry` 仍保留。
- C06B assignment API 所需 GET/POST/PATCH/DELETE 路径仍保留。
- C07C module registry helper、API helper、ModuleAccessProvider 和
  `tests/frontend/module-isolation.test.mjs` 必须存在。

## 防回退规则

business `show_locked` 防回退：

- 后端测试要求 business manifest `denied_behavior="show_locked"`。
- 前端测试遍历 business navigation，确认 denied fallback 仍 visible + locked。
- route guard 对 locked business 只显示 No Permission，不进入页面。

admin/system `hide_when_denied` 防回退：

- 后端测试要求 admin/system manifest `denied_behavior="hide_when_denied"`。
- non-owner 无显式授权时 admin/system access state 必须 hidden。
- `/modules/me` 失败时前端 fallback 仍强制隐藏 non-owner admin/system。

planned / adapter_pending / unavailable 防误执行：

- 后端测试确认这些 status 的 access `executable=false`。
- 前端测试确认这些状态 badge 为 planned/adapter_pending/unavailable，route decision 为
  `module_unavailable`，`canEnter=false`。
- C07D 不新增任何 create/run/publish 业务 action。

## 明确不做

C07D 不做：

- 不做 Module Adapter。
- 不做 Execution Provider。
- 不做 module switch。
- 不做模块 sandbox。
- 不做审批门。
- 不做密钥规则。
- 不新增后端业务 API。
- 不新增前端业务 UI。
- 不新增 migration。
- 不接 K01。K01 是未来业务模块，不能在 C07D 默认启用。
- 不接 P01/P02/P03/P04/P05/P06/P07/P08。P 系列是真实业务流，不能在 C07D 接入。
- 不接真实 n8n、WooCommerce、MinIO、Filebrowser。C07D 只允许现有 test bridge
  安全文案和 test-only route。
- 不读取真实 env。
- 不操作 production/staging 容器或数据库。
- 不发布 staging。
- 不发布 production。
- 不执行 safe release execute。

## 下一步

C07E staging 验收已归档。下一步是 C07F：production 模块隔离发布归档。C07F 应只做
production 发布归档，不进入 K01/P 系列，不接真实业务。
