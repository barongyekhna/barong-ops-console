# C07B Module Registry Backend

日期：2026-06-11 UTC

C07B 在 C07A 模块隔离方案基础上，新增后端静态 Module Manifest v1 和只读
Module Registry API。目标是让 Barong Ops Console 后端具备模块清单、分类、
权限声明、状态、访问状态和隔离元数据基础能力，为 C07C 前端 module-aware
navigation / route guard 以及后续 C08 Module Adapter 做准备。

C07B 不接真实业务，不实现 Module Adapter，不实现 Execution Provider，不实现模块
sandbox，不实现模块开关，不实现审批门，不实现密钥规则，不接 n8n、WooCommerce、
MinIO、Filebrowser，不接 K01，不接 P 系列，不发布 staging 或 production。

2026-06-11 C07C 补充：前端 module-aware navigation / route guard 已完成并归档在
`docs/C07_MODULE_FRONTEND_ISOLATION.md`。C07C 通过 frontend proxy 调用本文件记录的
`GET /modules/registry` 和 `GET /modules/me`，将 sidebar、No Permission、Module
Unavailable 和 route namespace guard 对齐到 C07B access state。C07C 没有修改本后端
API contract，没有新增后端 API 或 migration。

2026-06-11 C07D 补充：模块隔离 verify/test 体系已完成并归档在
`docs/C07_MODULE_ISOLATION_VERIFICATION.md`。C07D 强化
`tests/backend/test_modules_registry.py`，把本文件的 Module Manifest v1、registry
validation、access state、K01/P 系列禁止、真实 provider 禁止和 C05/C06 回归固化为自动
测试。C07D 没有修改后端 runtime contract，没有新增后端 API 或 migration。

2026-06-11 C07E 补充：staging 模块隔离验收已归档在
`docs/C07_MODULE_STAGING_ACCEPTANCE.md`。C07E 已将本文件的 C07B backend runtime 通过
safe release 发布到 staging backend，未执行 Alembic，未操作 staging/production
postgres，未读取真实 env，未发布 production。发布后未登录 `/modules/registry` 和
`/modules/me` 均返回 401；owner/non-owner live login 因无 approved staging owner
凭据和 active non-owner 测试账号未执行，相关 access-state 规则由
`tests/backend/test_modules_registry.py` 的 Docker 回归覆盖。

2026-06-12 C07F 补充：production 模块隔离发布已归档在
`docs/C07_MODULE_PRODUCTION_RELEASE.md`。C07F 已将本文件记录的 C07B backend runtime
通过 OPS01 safe release 发布到 production；未执行 Alembic upgrade，未操作 postgres，
未读取真实 env，未发布 staging，未接 K01/P 系列或真实业务。production 未登录
`/modules/registry` 与 `/modules/me` 返回 401，production backend 容器内 C07B 关键文件
存在且 hash 与当前 workspace 一致。

2026-06-12 C07G 补充：C07 模块隔离体系已在
`docs/C07_MODULE_ISOLATION_SEAL.md` 完成最终封板。C07G 确认本文件记录的后端静态 module
registry、Module Manifest v1 schema、`GET /modules/registry`、`GET /modules/me` 和 access
state 计算已形成 C07 后端最终状态；C07G 未新增后端 API、migration 或真实业务接入。

## 实现范围

新增后端集中模块 registry：

- `backend/app/schemas/module.py`：Module Manifest v1、navigation、permission
  manifest、release requirements、access state 和 API response schema。
- `backend/app/core/modules.py`：代码内静态 manifest source，不新增数据库表或
  migration。
- `backend/app/services/module_registry.py`：registry 校验、manifest 查询、用户访问
  状态计算。
- `backend/app/api/routes/modules.py`：新增只读 API，同时保留现有 F10 `/modules`
  foundation registry API。
- `tests/backend/test_modules_registry.py`：C07B API、registry validation、access
  state、C05/C06 regression 测试；C07D 在同一文件中补强 contract 负向测试、安全
  元数据扫描、planned/adapter_pending/unavailable 不可执行和 K01/P 系列禁止接入回归。

## Module Manifest v1 字段

C07B runtime manifest 至少包含：

- `module_key`
- `display_name`
- `description`
- `category`
- `status`
- `lifecycle`
- `route_namespace`
- `api_namespace`
- `no_api`
- `navigation`
- `required_permissions`
- `permission_manifest`
- `denied_behavior`
- `unavailable_behavior`
- `external_dependencies`
- `execution_provider_required`
- `module_adapter_required`
- `sandbox_required`
- `feature_flag_key`
- `audit_log_actions`
- `operation_log_policy`
- `allowed_scope_types`
- `data_boundary`
- `release_requirements`
- `staging_acceptance_required`
- `production_release_required`
- `docs_path`

`no_api=true` 表示该模块当前没有后端业务 API；此时 `api_namespace` 使用明确的
`no_api` 标记。C07B 不新增业务 module API。

## Registry 校验

`validate_module_manifests()` 会校验：

- `module_key` 唯一，并使用稳定小写 dot namespace。
- `category`、`status`、`denied_behavior` 合法。
- business 模块默认 `show_locked`。
- admin/system 模块默认 `hide_when_denied`。
- `route_namespace` 非空且以 `/` 开头。
- `api_namespace` 非空，或明确 `no_api=true`。
- `external_dependencies` 允许动态安全依赖 key，不使用 provider allowlist；
  不得包含 URL、secret、token、password、credential、env 等运行值。
- `required_permissions` 必须出现在同模块 `permission_manifest` 中。
- permission keys 使用可追踪的 `module.action` 格式。
- permission manifest 的 `module_key`、`category`、`menu_policy` 必须和模块一致。
- `allowed_scope_types` 必须来自现有 C05/C06 scope 类型。

## 初始内置模块

C07B 只注册当前控制台已有或平台内置模块，不虚构真实可执行的业务模块：

- `core.dashboard`
- `experimental.foundation_demo`
- `integration.n8n_test_bridge`
- `admin.users`
- `admin.permissions`
- `admin.modules`
- `admin.agents`
- `admin.workflows`
- `admin.settings`
- `business.products`
- `business.jobs`
- `business.artifacts`
- `business.reviews`
- `system.errors`
- `system.memory_events`
- `system.operation_logs`

占位模块使用 `planned` 或 `adapter_pending`，不会被标记为 executable：

- `business.products`：`planned`，`no_api=true`。
- `admin.settings`：`planned`，`no_api=true`。
- `integration.n8n_test_bridge`：`adapter_pending`，只声明 `n8n` 依赖名，不连接真实
  n8n。

K01 没有进入 runtime registry。K01 只作为 C07A 文档中的未来示例保留，C07B 不开发、
不启用、不导航、不提供 API。

## API

### `GET /modules/registry`

要求登录。未登录返回 401。

返回安全的静态 module registry metadata，包括 manifest 字段、权限声明、状态、
route/API namespace 和隔离元数据。该接口不返回真实 env、secret、token、password、
credential、provider URL 或内部运行配置。

### `GET /modules/me`

要求登录。未登录返回 401。

基于当前登录用户和 C05/C06 effective permissions 返回每个模块的访问状态：

- `module_key`
- `visible`
- `locked`
- `hidden`
- `unavailable`
- `executable`
- `access_state`
- `denied_behavior`
- `reason`
- `required_permissions`
- `missing_permissions`
- `status`
- `category`
- `route_namespace`

`access_state` 当前可为：

- `available`
- `locked`
- `hidden`
- `unavailable`
- `planned`
- `adapter_pending`

C07B 不返回 `executable=true`，因为本阶段不实现执行能力。

## 访问规则

- owner full access 全局可见，可看到 `admin.users`、`admin.permissions` 等
  admin/system 模块。
- owner 不依赖 assignment，也不依赖 `role_default_permissions`。
- non-owner 只基于 explicit effective permission assignments。
- `role_default_permissions` 不自动授予模块访问。
- `super_admin` 不默认全局可见 admin/system 模块。
- `admin.users` 和 `admin.permissions` 继续 owner-only。
- admin/system 模块对无权限用户 `hide_when_denied`，返回
  `access_state="hidden"`。
- business 模块对无权限用户 `show_locked`，返回 `visible=true`、
  `locked=true`、`access_state="locked"`。
- `planned`、`adapter_pending`、`unavailable`、`disabled` 不会返回可执行状态。
- 声明外部依赖的模块在 C07B 不连接 provider，也不会触发真实业务动作。

## 明确不做

C07B 明确不做：

- 不实现 Module Adapter。
- 不实现 Execution Provider。
- 不实现模块 sandbox。
- 不实现 module switch 或 feature flag 管理。
- 不实现审批门。
- 不实现密钥规则。
- 不接真实 n8n。
- 不接 WooCommerce。
- 不接 MinIO。
- 不接 Filebrowser。
- 不接 K01。
- 不接 P 系列。
- 不写真实业务数据。
- 不新增 frontend UI。
- 不新增 migration。
- 不发布 staging。
- 不发布 production。

## C07C 前端接入引用

C07C 已消费本文件提供的后端 contract：

- `GET /modules/registry`：用于前端类型和 navigation registry 对齐测试。
- `GET /modules/me`：用于当前用户 module access state。
- `access_state="locked"`：business denied 时 sidebar 显示 locked，route guard 显示无权访问。
- `access_state="hidden"`：admin/system denied 时 sidebar 隐藏，直接访问显示无权访问。
- `access_state="planned"`、`adapter_pending`、`unavailable`：显示模块暂不可用，不触发真实动作。

C07C 仍保持 User Management / Permission Management owner-only，继续不接真实业务、
不接 K01/P 系列、不接 n8n/WooCommerce/MinIO/Filebrowser、不实现 Module Adapter 或
Execution Provider。

## C07D 后端测试引用

C07D 后端 contract 测试入口：

- `tests/backend/test_modules_registry.py`

新增和强化覆盖：

- Module Manifest v1 必填字段、唯一 `module_key`、合法 category/status/lifecycle/
  denied_behavior。
- business `show_locked` 与 admin/system `hide_when_denied`。
- route namespace 与 API namespace/no_api 规则。
- permission manifest key 格式、required permission 对齐、泛名 permission key 禁止。
- external dependencies 只能是动态安全依赖 key，不得包含 secret/token/password/
  env/URL/credential/API key；unknown service 交给 C14D quarantine/proposal。
- `planned`、`adapter_pending`、`unavailable` 不可执行。
- K01 未进入当前 runtime registry；P 系列真实业务模块未接入。
- `integration.n8n_test_bridge` 只能保持 test/integration + adapter_pending。
- owner/non-owner module access state、`role_default_permissions` 不自动生效、
  `super_admin` 不默认全局、`/users` owner-only、`/auth/register` 404、
  `/permissions/me` 和 C06B assignment API 回归。

## C07E staging 验收引用

C07E 对本后端 contract 的 staging 结论：

- staging backend safe release 成功。
- 未执行 Alembic upgrade。
- 未操作 staging postgres 容器或数据库。
- 未登录 `GET /modules/registry` 返回 401。
- 未登录 `GET /modules/me` 返回 401。
- C07D Docker 后端测试覆盖 owner full access、non-owner admin/system hidden、
  business locked/show_locked、planned/adapter_pending/unavailable 不可执行、
  `/users` owner-only、`/auth/register` 404、`/permissions/me` 和 C06B assignment API。
- K01/P 系列未进入 runtime registry，`integration.n8n_test_bridge` 保持
  adapter_pending/test-only，未连接真实 provider。

## C07F production 发布引用

C07F 对本后端 contract 的 production 结论：

- production backend safe release 成功。
- 未执行 Alembic upgrade，production current/head 仍为 `c05b_permissions_001 (head)`。
- 未操作 production/staging postgres 容器或数据库。
- 未登录 `GET /modules/registry` 返回 401。
- 未登录 `GET /modules/me` 返回 401。
- production backend 容器包含 C07B `routes/modules.py`、`services/module_registry.py`、
  `core/modules.py` 和 `schemas/module.py`。
- owner/non-owner live login 因无 approved production auth material 未执行，相关
  access-state 规则由 C07D Docker tests 和 C07E staging 验收覆盖。

## 下一步

C07G 已完成 C07 模块隔离最终封板，记录在 `docs/C07_MODULE_ISOLATION_SEAL.md`。下一步应
进入 C08 Module Adapter，但不得在本文件或 C07G 中启动 K01/P 系列或真实 provider 接入。
