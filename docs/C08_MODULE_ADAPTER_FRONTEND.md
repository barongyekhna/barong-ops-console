# C08C Module Adapter Frontend Shell

日期：2026-06-12 UTC

C08C 在 C08B 后端 Module Adapter Contract v1 和只读 adapter registry API
完成后，实现前端 adapter-aware 展示壳。C08C 只展示 adapter contract 和安全
placeholder，不执行 action，不创建任务，不连接 provider，不新增后端 API，不新增
migration，不发布 staging 或 production。

2026-06-12 C08D 补充：Adapter contract verify/test 体系已完成并归档在
`docs/C08_MODULE_ADAPTER_VERIFICATION.md`。前端 C08D 继续强化
`tests/frontend/module-adapter.test.mjs` 和 `frontend/scripts/verify-foundation.mjs`，
覆盖 adapter proxy exact allowlist、no wildcard、adapter helper/provider/shell/API
client 文件存在、no-execute helper、available_actions 安全降级、execution_required 等待
C09、approval_required 等待 C12、dependency safe display、K01/P 系列不默认启用、
live provider/action route 禁止，以及 C05/C06/C07 回归。C08D 未新增前端业务 UI，
未新增后端 API，未执行 adapter action，未连接 provider。

## 实现范围

新增前端 adapter 类型、helper 和 API client：

- `frontend/src/lib/module-adapter.ts`
- `frontend/src/lib/module-adapter-api.ts`

新增 provider / hooks：

- `frontend/src/components/adapter-access-provider.tsx`
- `AdapterAccessProvider`
- `useAdapterAccess`
- `useAdapterRegistry`
- `useAdapterState(adapterKey)`
- `useAdapterStateForModule(moduleKey)`

新增 rendering shell：

- `frontend/src/components/module-adapter-shell.tsx`
- `AdapterSurfaceShell`
- `AdapterSurfacePlaceholder`
- `AdapterStatusBadge`
- `AdapterCapabilitiesList`
- `AdapterActionContractsList`
- `AdapterDependencySummary`
- `AdapterDataContractsSummary`
- `AdapterUnavailableNotice`

更新：

- console layout 挂载 `AdapterAccessProvider`，与 C07C `ModuleAccessProvider` 并存。
- console shell 在当前 module route 下方展示通用 `AdapterSurfaceShell`。
- frontend backend proxy 精确允许 C08B 两个只读 API。
- `frontend/scripts/verify-foundation.mjs` 检查 C08C proxy allowlist 和禁止宽通配。
- `tests/frontend/module-adapter.test.mjs` 覆盖 C08C helper/proxy/rendering 纯逻辑。

## API 调用

前端只通过现有 restricted same-origin backend proxy 调用：

- `GET /module-adapters/registry`
- `GET /module-adapters/me`

API client 使用同源 backend proxy 和 HttpOnly session cookie，不在前端读取或拼接
auth secret，不打印 token、password、secret 或 Authorization header。请求失败时返回空集合、safe error summary 和
`adapter_access_unknown=true`，不会让页面崩溃。

如果 `/module-adapters/me` 暂不可用，前端将 adapter access 视为 unknown。非 owner 不会因
registry 可读而看到 admin/system adapter metadata；owner full access 仍可看到安全 metadata。

## Provider / Hook 设计

`AdapterAccessProvider` 与 C07C `ModuleAccessProvider` 并存：

- C07 module access 仍负责模块是否 visible、locked、hidden、unavailable。
- C08 adapter access 只在模块边界内展示 adapter surfaces / contracts。
- `useAdapterRegistry()` 返回按当前用户 access state 过滤后的 safe registry items。
- `useAdapterState(adapterKey)` 查询单个 adapter。
- `useAdapterStateForModule(moduleKey)` 用于当前 route module 的展示壳。

admin/system adapter 在 access unknown 且当前用户不是 owner full access 时会被过滤，避免
`/module-adapters/me` 失败时暴露 owner-only metadata。

## Rendering Shell

`AdapterSurfaceShell` 根据当前 pathname 匹配 C07 `navigationModuleRecords`，找到当前
`module_key` 后展示对应 adapter。它不改变 C07 route guard，不改变 business
`show_locked`，不改变 admin/system `hide_when_denied`。

展示内容包括：

- adapter status badge。
- supported surfaces：navigation、dashboard card、module page、action panel、status widget 等。
- pages / nav / route / api bindings 摘要。
- capabilities 摘要。
- action contracts 摘要。
- data / input / output contracts 摘要。
- dependency declarations 的安全依赖名。
- adapter unavailable / locked / pending notice。

文案明确 action 只是 contract：

- `Adapter contract is available, but execution is not connected yet.`
- `Execution Provider not connected`
- `等待 C09 Execution Provider`
- `等待 C12 Approval Gate`

## Actions / Capabilities

C08C 允许展示 capabilities 和 action contracts，但所有 action 都不可执行：

- `isAdapterExecutable()` 永远返回 `false`。
- `normalizeAdapterAccessState()` 会把后端返回的 `available_actions` 安全降级为空。
- `getActionContractState()` 不生成 executable payload。
- action button 始终 disabled，显示 `Execution Provider not connected`。

需要 execution provider 的 action 显示等待 C09。需要 approval 的 action 显示等待 C12。
C08C 不创建 operation log，因为没有 action execution。

## Dependency Safety

dependency declarations 只展示安全依赖名：

- `n8n`
- `woocommerce`
- `minio`
- `filebrowser`
- `ai_provider`
- `serp`
- `wecom`
- `google_sheets`

前端 helper 会过滤 secret、token、password、Authorization、credential、env、URL、
webhook、API key 形态的值。UI 只展示 dependency key，不展示 provider URL、token、env、
credential、webhook 或 secret requirement。

## 明确不做

C08C 明确不做：

- 不实现 Execution Provider。
- 不实现 Module Switch。
- 不实现 Approval Gate。
- 不实现模块 sandbox。
- 不实现密钥规则。
- 不新增后端 API。
- 不新增 migration。
- 不接 K01。
- 不进入 K-series worktree。
- 不接 P01/P02/P03/P04/P05/P06/P07/P08。
- 不新增 SEO/GEO 或真实业务页面。
- 不接 n8n/WooCommerce/MinIO/Filebrowser live provider。
- 不调用 external provider。
- 不执行任何 adapter action。
- 不创建任务。
- 不写数据库。
- 不发布 staging。
- 不发布 production。

K01/P 系列只能作为 future example 出现在文档或安全 placeholder 中，不会进入默认
production navigation 或 live action。

## 测试

新增 `tests/frontend/module-adapter.test.mjs`，使用 Node 内置 test runner，不安装新依赖。
覆盖：

- `/module-adapters/registry` 和 `/module-adapters/me` proxy 精确 allowlist。
- `/api/backend/module-adapters/not-allowed` 不被宽通配放行。
- `verify-foundation` 检查 C08C allowlist，并保持 C05/C06/C07 检查。
- `adapter_pending`、`disabled`、`deprecated` 不可执行。
- execution required / approval required action 不可执行。
- owner 可见 admin adapter metadata，non-owner admin/system hidden。
- business no permission locked。
- missing adapter access state 安全降级。
- dependency declarations 只保留安全名称。
- role defaults 和 `super_admin` 不默认全局。
- status badge / action contract state / unavailable notice / K01/P 系列默认不启用。
- C05/C06/C07 owner-only 和 route guard 回归。
- C08D 增强：module-adapter API client 不允许 POST/PUT/PATCH/DELETE。
- C08D 增强：adapter shell 不允许 `fetch()` / `apiRequest()` action execution call。
- C08D 增强：即使后端误返回 `available_actions`，前端也清空并转入 unavailable。
- C08D 增强：verifier 检查 live provider/action route 标记不得出现。

## 下一步

C08E staging Module Adapter 验收已完成，归档文档为
`docs/C08_MODULE_ADAPTER_STAGING_ACCEPTANCE.md`。staging frontend safe release 已
发布 C08C adapter shell；staging bundle 命中 adapter API paths、
`AdapterAccessProvider`、`Action contracts`、C09 Execution Provider 等待文案和 C12
Approval Gate 等待文案。frontend proxy 精确允许
`/api/backend/module-adapters/registry` 和 `/api/backend/module-adapters/me`，并拒绝
`/api/backend/module-adapters/not-allowed`。C08E 未执行 adapter action，未接
K01/P 系列或 live provider，未发布 production。

C08F production Module Adapter 发布归档已完成，归档文档为
`docs/C08_MODULE_ADAPTER_PRODUCTION_RELEASE.md`。production frontend safe release
已发布 C08C adapter shell；production `/dashboard` HTML 和 production chunk 命中
`AdapterAccessProvider`、adapter API paths、`Action contracts`、C09 Execution
Provider 等待文案、C12 Approval Gate 等待文案、adapter shell disabled/unavailable
文案和 dependency safety helper。production frontend proxy 精确允许
`/api/backend/module-adapters/registry` 和 `/api/backend/module-adapters/me`，并拒绝
`/api/backend/module-adapters/not-allowed`。C08F 未执行 adapter action，未接
K01/P 系列或 live provider，未发布 staging。

C08G Module Adapter 封板已完成，归档文档为
`docs/C08_MODULE_ADAPTER_SEAL.md`。C08G 确认前端 C08C adapter shell 已承接到
C08D verification、C08E staging 和 C08F production；本轮不修改 frontend runtime，不新增
UI/API，不发布 staging/production，不读取 env，不执行 adapter action，不接 K01/P 系列、
live provider 或真实业务。

下一步只建议 C09 Execution Provider；C08G 不启动 C09。
