# C08B Module Adapter Backend Registry

日期：2026-06-12 UTC

C08B 在 C08A Module Adapter 方案基础上，实现后端 Module Adapter
contract v1、代码内静态 adapter registry、只读 API 和后端 contract
测试。C08B 只提供声明式元数据能力，为 C08C 前端 adapter rendering
shell 和 C09 Execution Provider 做准备。

C08B 不执行 action，不连接外部 provider，不实现 Execution Provider，不实现
Module Switch，不实现 Approval Gate，不新增 migration，不新增前端 UI，不接 K01，
不接 P 系列，不接 n8n/WooCommerce/MinIO/Filebrowser live provider，不发布
staging 或 production。

2026-06-12 C08C 补充：前端 adapter rendering shell / adapter surface placeholders
已完成并归档在 `docs/C08_MODULE_ADAPTER_FRONTEND.md`。C08C 通过现有 frontend
backend proxy 只读消费本文件记录的 `GET /module-adapters/registry` 和
`GET /module-adapters/me`，展示 adapter status、supported surfaces、bindings、
capabilities、action/data contracts 和安全 dependency names。C08C 未修改本后端 API
contract，未新增后端 API，未新增 migration，未执行 action，未连接 live provider。

## 实现范围

新增后端文件：

- `backend/app/schemas/module_adapter.py`：Module Adapter Contract v1、
  safe registry response 和当前用户 adapter access state schema。
- `backend/app/core/module_adapters.py`：代码内静态 adapter registry。
- `backend/app/services/module_adapter_registry.py`：contract validation、
  C07 module binding 校验、dependency safety 校验和 access state 计算。
- `backend/app/api/routes/module_adapters.py`：只读 API。

更新：

- `backend/app/main.py` include 新 router。
- `tests/backend/test_module_adapters_registry.py` 覆盖 C08B contract/API/
  access state/regression。

## Module Adapter Contract v1 字段

`ModuleAdapterContractV1` 包含：

- `adapter_key`
- `adapter_version`
- `module_key`
- `manifest_version`
- `display_name`
- `description`
- `adapter_status`
- `lifecycle`
- `supported_surfaces`
- `pages`
- `nav_bindings`
- `route_bindings`
- `api_bindings`
- `capabilities`
- `actions`
- `action_contracts`
- `status_provider`
- `health_provider`
- `data_contracts`
- `input_contracts`
- `output_contracts`
- `permission_bindings`
- `scope_bindings`
- `operation_log_bindings`
- `audit_events`
- `feature_flag_bindings`
- `dependency_declarations`
- `execution_requirements`
- `sandbox_requirements`
- `approval_requirements`
- `secret_requirements`
- `fallback_behavior`
- `unavailable_behavior`
- `test_contracts`
- `docs_path`

`ModuleAdapterRead` 是安全输出 schema。registry/service 校验会拒绝 secret、
token、password、Authorization header、env path、provider URL、webhook URL
或 credential-shaped runtime value。`secret_requirements` 只声明 future C14 需求
形状，不声明任何密钥值。

## Static Adapter Registry

C08B 第一版使用代码内静态 registry，不新增数据库表，不新增 Alembic migration。

初始 adapter：

- `core.dashboard.adapter`
  - `module_key=core.dashboard`
  - `adapter_status=sealed`
  - 只声明 dashboard shell metadata，无 action。
- `admin.users.adapter`
  - `module_key=admin.users`
  - `adapter_status=sealed`
  - 声明 owner-only user management surfaces 和 action contracts。
  - action contracts 只声明，不执行。
- `admin.permissions.adapter`
  - `module_key=admin.permissions`
  - `adapter_status=sealed`
  - 声明 owner-only permission management surfaces 和 action contracts。
  - approval 只声明 future C12，不执行审批。
- `business.products.placeholder.adapter`
  - `module_key=business.products`
  - `adapter_status=adapter_pending`
  - 绑定 C07 planned placeholder module。
  - requires execution provider，但 C08B 不实现 C09，所有 action 不可执行。
- `integration.n8n_test_bridge.adapter`
  - `module_key=integration.n8n_test_bridge`
  - `adapter_status=adapter_pending`
  - 只声明 `n8n` 安全依赖名，`live_connection_allowed=false`。
  - 不连接真实 n8n，不返回 webhook URL，不触发 test bridge action。

没有注册 K01 runtime adapter。没有注册 P01/P02/P03/P04/P05/P06/P07/P08。
没有注册 WooCommerce、MinIO、Filebrowser live adapter。

## API

C08B 新增两个 authenticated read-only API：

- `GET /module-adapters/registry`
- `GET /module-adapters/me`

两个 API 都要求登录，未登录返回 401。

`GET /module-adapters/registry` 返回安全 adapter registry metadata，不返回
secret、token、password、Authorization header、env path、provider URL、webhook URL
或 credential value。

`GET /module-adapters/me` 基于当前用户、C07 module access state 和 C05/C06
effective permissions 返回 adapter access state，包括：

- `adapter_key`
- `module_key`
- `visible`
- `hidden`
- `locked`
- `unavailable`
- `adapter_status`
- `adapter_access_state`
- `supported_surfaces`
- `available_surfaces`
- `disabled_surfaces`
- `action_contracts`
- `available_actions`
- `locked_actions`
- `unavailable_actions`
- `required_permissions`
- `missing_permissions`
- `requires_execution_provider`
- `execution_provider_state`
- `requires_approval`
- `reason`

C08B 不新增 action execution endpoint。

## Lifecycle / Status

合法 `adapter_status` 和 `lifecycle`：

- `draft`
- `adapter_pending`
- `contract_ready`
- `test_ready`
- `staging_ready`
- `production_ready`
- `disabled`
- `deprecated`
- `sealed`

规则：

- `draft`、`adapter_pending`、`disabled`、`deprecated` 不可 executable。
- `contract_ready` 只表示 contract 可读，不代表可执行。
- `test_ready` 只表示测试可验证，不代表 production 可执行。
- `staging_ready` / `production_ready` 也不等于 action 可执行。
- `sealed` 表示 adapter contract 封板。
- C08B 不做 C13 module switch。

## Supported Surfaces

C08B schema 支持：

- `navigation`
- `dashboard_card`
- `module_page`
- `detail_page`
- `action_panel`
- `settings_panel`
- `audit_log_view`
- `status_widget`
- `future_approval_panel`

surface 是声明，不是 UI 实现。C08B 不新增前端 UI，action surface 在 C09 前
保持 disabled/unavailable。

## Bindings

`pages`、`route_bindings` 必须落在对应 C07 `route_namespace` 内。
`api_bindings` 必须落在对应 C07 `api_namespace` 内，或显式 `no_api`。
`nav_bindings` 必须绑定同一个 `module_key`，且不得绕过 C07 denied behavior：

- business adapter 使用 `show_locked`。
- admin/system adapter 使用 `hide_when_denied`。

Adapter 不允许创建未注册 module，也不允许把 route/API 挂到其他模块 namespace。

## Capabilities / Actions

`capabilities` 描述 adapter 能力。`actions` 和 `action_contracts` 只描述用户可触发
动作的合同字段：

- `action_key`
- `required_permission`
- `risk_level`
- `requires_approval`
- `requires_execution_provider`
- `input_contract`
- `output_contract`
- `operation_log_action`
- `executable_before_c09=false`

C08B 不执行 action，不创建任务，不调用 provider。需要 Execution Provider 的 action
返回 `unavailable_actions`，`execution_provider_state=required_not_implemented_c08b`
或 `adapter_pending`。

## Status / Health

`status_provider` 和 `health_provider` 是 static contract：

- `live_provider_connected=false`
- `live_check_allowed=false`
- `secret_read_allowed=false`
- `mock_only=true` for health

C08B 不做 live health check，不读取 secret，不连接外部 provider。

## Data/Input/Output Contracts

`data_contracts`、`input_contracts`、`output_contracts` 声明数据对象、版本、读写边界、
输入字段、输出安全摘要和 operation log projection。它们用于后续 C08D/C09 验证，
不是 runtime execution schema。

## Permissions / Scope / Logs

`permission_bindings` 必须能追踪到 C07 manifest 的 permission manifest。`/me`
仍基于 C05/C06 effective permissions：

- owner full access 可见 admin/users/permissions adapters。
- non-owner admin/system adapters 返回 `hidden`，不暴露 action surfaces。
- business adapter 无权限返回 `locked`，保持 C07 `show_locked`。
- `role_default_permissions` 不自动生效。
- `super_admin` 不默认全局 adapter access。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。

`scope_bindings` 在 C18 前只能是 `adapter_pending`。`operation_log_bindings` 只声明
future action 到 operation log action 的映射；C08B 不写 operation log。

## Dependency Declarations

`dependency_declarations` 只允许安全依赖名：

- `n8n`
- `woocommerce`
- `minio`
- `filebrowser`
- `ai_provider`
- `serp`
- `wecom`
- `google_sheets`

依赖声明不得包含 secret、token、password、env、Authorization header、URL、
webhook、API key 或 credential value。C08B 只声明依赖名和 `live_connection_allowed=false`。

## Validation

`validate_adapter_contracts()` 校验：

- `adapter_key` 唯一且命名合法。
- `adapter_version` 合法。
- `module_key` 存在于 C07 module registry。
- `adapter_status` / `supported_surfaces` 合法。
- route/API/nav binding 不越界。
- permissions 来自 C07 manifest 并在 adapter 中可追踪。
- actions 和 action_contracts 对齐，并声明 permission、risk、operation log action。
- execution action 需要 `requires_execution_provider=true`，但 `executable_before_c09=false`。
- dependency declarations 不含敏感 runtime 值。
- `adapter_pending`、`disabled`、`deprecated` 不可执行。
- K01/P 系列不能默认 enabled/executable。
- n8n/WooCommerce/MinIO/Filebrowser 只能声明安全依赖名，不能连接 live provider。

## 下一步

C08C 已实现前端 adapter rendering shell / adapter surface placeholders，只显示安全
placeholder 和 pending/unavailable/disabled 状态，不接真实业务 UI，不触发 action。
下一步应进入 C08D Adapter contract verify/test 体系，继续固化 no-execute、
no-provider、no-secret 和 C05/C06/C07 regression 检查。
