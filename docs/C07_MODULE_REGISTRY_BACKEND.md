# C07B Module Registry Backend

日期：2026-06-11 UTC

C07B 在 C07A 模块隔离方案基础上，新增后端静态 Module Manifest v1 和只读
Module Registry API。目标是让 Barong Ops Console 后端具备模块清单、分类、
权限声明、状态、访问状态和隔离元数据基础能力，为 C07C 前端 module-aware
navigation / route guard 以及后续 C08 Module Adapter 做准备。

C07B 不接真实业务，不实现 Module Adapter，不实现 Execution Provider，不实现模块
sandbox，不实现模块开关，不实现审批门，不实现密钥规则，不接 n8n、WooCommerce、
MinIO、Filebrowser，不接 K01，不接 P 系列，不发布 staging 或 production。

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
  state、C05/C06 regression 测试。

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
- `external_dependencies` 只允许依赖名称，例如 `n8n`、`woocommerce`、`minio`、
  `filebrowser`、`ai_provider`，不得包含 URL、secret、token、password、
  credential、env 等运行值。
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

## 下一步

C07C 应在前端接入 module-aware navigation / route guard：

- 导航项绑定后端 module metadata。
- route guard 支持 namespace。
- business denied 继续 `show_locked`。
- admin/system denied 继续 `hide_when_denied`。
- planned / adapter_pending / unavailable 不触发真实动作。
- frontend proxy 不放开通配。
