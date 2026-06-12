# C08D Module Adapter Verification

日期：2026-06-12 UTC

C08D 把 C08A/C08B/C08C 的 Module Adapter 规则固化为自动校验和测试体系。
C08D 只做 verify/test，不开发业务功能，不实现 Execution Provider，不实现 Module
Switch，不实现 Approval Gate，不新增后端业务 API，不新增前端业务 UI，不新增
migration，不接 K01/P 系列，不连接真实 provider，不发布 staging 或 production。

## 做了什么

C08D 强化三类检查：

- 后端 `tests/backend/test_module_adapters_registry.py`：Module Adapter v1
  contract、adapter registry、access state、no-execute、no-secret、no-live
  provider 和 C05/C06/C07 回归。
- 前端 `tests/frontend/module-adapter.test.mjs`：adapter shell/helper/proxy
  纯逻辑，确认 action contract 只展示 disabled declaration，不生成 executable
  payload，不创建 mutation API 调用。
- `frontend/scripts/verify-foundation.mjs`：只读静态 verifier，检查 C08 proxy
  精确 allowlist、adapter helper/provider/shell/test 文件存在，以及 no-live/no-execute
  防回退规则。

这些检查都不访问网络、不读真实 env、不连接 database、不调用 production/staging，
不执行 adapter action，不连接 n8n/WooCommerce/MinIO/Filebrowser live provider。

## 后端 Registry Contract

后端 adapter registry contract 校验覆盖：

- `adapter_key` 必须唯一，且为小写 snake_case 或 dot namespace。
- `adapter_version` 必须符合 `x.y.z`。
- `module_key` 必须存在于 C07 module registry。
- `adapter_status`、`lifecycle`、`supported_surfaces` 必须合法。
- `pages`、`nav_bindings`、`route_bindings`、`api_bindings` 必须结构合法。
- route bindings 必须落在对应 module `route_namespace` 内。
- API bindings 必须落在对应 module `api_namespace` 内，或显式 `no_api`。
- nav bindings 必须绑定同一个 `module_key`，不得绕过 C07 module-aware navigation。
- capabilities、actions、action_contracts 必须对齐。
- action/action_contract 必须声明 `action_key`、`required_permission`、
  `risk_level` 和 `operation_log_action`。
- execution required action 必须声明 `requires_execution_provider=true`，但
  `executable_before_c09=false`。
- approval required action 必须声明 approval requirement，但不可执行。
- `draft`、`adapter_pending`、`disabled`、`deprecated` 不可 executable。
- `contract_ready`、`test_ready`、`staging_ready`、`production_ready` 只代表
  contract 状态，不代表 action 可执行。
- dependency declarations 只能包含安全依赖名，不允许 secret/token/password/env/
  url/webhook/credential/API key。
- status provider 和 health provider 不允许 live check、secret read、provider URL
  或 env/token 值。
- data/input/output contracts 必须可 JSON 序列化、可版本化，不包含真实样本 secret。
- permission bindings 必须可追踪到 C07 manifest permission。
- scope bindings 在 C18 前只能保持 `adapter_pending`。
- K01/P 系列不得默认 runtime enabled/executable。
- n8n/WooCommerce/MinIO/Filebrowser 只能作为 dependency name 声明，不得 live
  connected。
- registry 不得包含 production/staging env 值、provider URL、webhook secret 或 API key。

## 后端 Access State

后端 adapter access state 校验覆盖：

- 未登录访问 `GET /module-adapters/registry` 返回 401。
- 未登录访问 `GET /module-adapters/me` 返回 401。
- owner 可访问 `GET /module-adapters/registry` 和 `GET /module-adapters/me`。
- owner full access 可见 `admin.users` / `admin.permissions` adapter metadata。
- non-owner admin/system adapter hidden，且不返回 action surfaces/contracts。
- business adapter 无权限时 visible + locked/show_locked。
- `adapter_pending`、`disabled`、`deprecated` 不可 executable。
- execution required action 返回 unavailable，`execution_provider_state` 保持
  `required_not_implemented_c08b` 或 `adapter_pending`，不会执行。
- approval required action 只返回 approval declaration，available actions 为空，
  不会执行。
- `role_default_permissions` 不自动生效。
- `super_admin` 不默认全局 adapter access。
- `/modules/registry`、`/modules/me`、`/permissions/me`、C06B assignment API、
  `/users` owner-only 和 `/auth/register` 404 不回退。

C08D 也检查 `/module-adapters` router 只暴露 authenticated read-only GET contract
API，不存在 action execution endpoint。

## 前端 Shell Contract

前端 adapter shell 校验覆盖：

- `AdapterAccessProvider`、adapter hooks、`AdapterSurfaceShell` 和
  `module-adapter-api.ts` 文件必须存在。
- `/module-adapters/registry` 和 `/module-adapters/me` 只能通过 restricted backend
  proxy 以 GET 调用。
- `/api/backend/module-adapters/not-allowed` 不被宽通配放行。
- `adapter_pending`、`draft`、`disabled`、`deprecated` 不可 executable。
- execution required action 显示等待 C09 Execution Provider，按钮 disabled。
- approval required action 显示等待 C12 Approval Gate，按钮 disabled。
- action contract state 不包含 executable payload。
- module-adapter API client 不创建 POST/PUT/PATCH/DELETE action execution call。
- owner 可见 admin adapter metadata；non-owner admin/system adapter hidden。
- business adapter no permission locked。
- missing adapter access state 安全降级，不暴露 admin/system metadata。
- dependency declarations 只展示安全依赖名，不展示 URL/env/token/secret/webhook。
- `AdapterUnavailableNotice` 不暴露内部凭据。
- `AdapterStatusBadge` 覆盖 draft、adapter_pending、disabled、deprecated、sealed。
- C05 permissions、C06 permission-management、C07 module-isolation、User Management
  owner-only、Permission Management owner-only 回归继续通过。
- K01/P 系列 future example 不会默认启用。
- 不出现真实 n8n/WooCommerce/MinIO/Filebrowser live action 文案或执行入口。

## Proxy Allowlist

`frontend/scripts/verify-foundation.mjs` 校验：

- 精确允许 GET `/module-adapters/registry`。
- 精确允许 GET `/module-adapters/me`。
- 不允许 `/module-adapters/*` 宽通配。
- 继续精确允许 GET `/modules/registry` 和 GET `/modules/me`。
- 继续保留 `/permissions/me`、`/permissions/registry` 和 C06B assignment API 路径。
- adapter helper/provider/shell/API client/test 文件存在。
- module-isolation test 文件仍存在。
- 主 navigation 不默认启用 K01 或 P 系列菜单。
- 不出现 live n8n/WooCommerce/MinIO/Filebrowser action route 或明显 live 接入标记。

## No-Execute Rules

C08D 的核心防回退规则：

- 后端 `available_actions` 永远为空。
- 前端 `normalizeAdapterAccessState()` 即使收到误标的 `available_actions`，也会清空并
  转入 `unavailable_actions`。
- `isAdapterExecutable()` 永远返回 false。
- action panel surface 始终 disabled，直到后续正式阶段实现执行能力。
- `executable_before_c09` 在 action、action_contract 和 execution requirement 上都必须是
  false。

execution required action 只能等待 C09，因为 C08 只有 action contract，没有 Execution
Provider、队列、结果写入、operation log execution 或 provider dispatch。

approval required action 只能等待 C12，因为 C08 只有 approval declaration，没有 Approval
Gate、审批记录、审批状态机或审批执行授权。

dependency declarations 只能展示安全名称，因为 C08 不读取 env、不保存 secret、不连接 provider。
真实 URL、token、credential、webhook、API key 必须留给后续 secret/provider 阶段处理。

## 边界

- K01 没有在 C08D 默认启用。K01 是未来业务模块，不在 C08D 开发，也不进入
  `/opt/barong-ops-console-worktrees/k-series-product-knowledge`。
- P 系列没有在 C08D 接入。P01/P02/P03/P04/P05/P06/P07/P08 是未来真实业务流，不读取或修改
  workflow JSON。
- n8n/WooCommerce/MinIO/Filebrowser 没有在 C08D live connected。只允许安全 dependency
  name 或现有 test bridge 文案。
- C08D 不做 Execution Provider。
- C08D 不做 Module Switch。
- C08D 不做 Approval Gate。
- C08D 不做 sandbox、secret rules、n8n 接入规范或组织 scope。
- C08D 不发布 staging/production。

## 下一步

下一步是 C08E staging Module Adapter 验收。C08E 只能做 staging contract runtime 验收，
不得接 K01/P 系列、不得连接真实 provider、不得执行 adapter action。
