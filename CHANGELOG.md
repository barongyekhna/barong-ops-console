# Changelog

本项目的重要文档和工程变更记录在此文件中。

## [Unreleased]

### Added

- C13A：新增 `docs/C13A_MODULE_SWITCH_SYSTEM_DESIGN.md`，完成 Module Switch
  System 架构层设计；定义 `ModuleSwitchRegistry`、`ON` / `OFF` / `DEPRECATED` /
  `MAINTENANCE` switch state model、`ModuleSwitchGate` 和 required integration
  position `C08 -> C13A -> C12 -> C09 -> C10`。
- C13A：明确 gate 规则为 `ON` allow flow，`OFF` block request，并保守规定
  `DEPRECATED`、`MAINTENANCE`、missing registry 和 invalid state 均 fail closed；
  blocked request 不进入 C12，不创建 C09 execution request，不调用 C10 sandbox。
- C13A：更新 README 与 ARCHITECTURE 的模块开关架构说明；本轮只做设计文档，未修改
  backend/frontend runtime，未新增 API/UI/migration，未修改 approval logic，未修改
  sandbox，未执行 adapter action，未引入 runtime execution。
- C09G：新增 `docs/C09_EXECUTION_PROVIDER_SEAL.md`，归档 C09 Execution
  Provider 统一最终封板；覆盖 C09A-C09F 完整生命周期、Execution Provider Contract v1
  冻结状态、no-op/mock/contract-only model、production gateway 非依赖、C08/C07/C05/C06
  对齐、C10-C20 边界和 sealed state。
- C09G：更新 README 与 C09A-F 文档的最终封板口径；明确 C09 是能力层和合同层，不是
  执行系统上线；execution runtime = NO，live provider = NO，execution request system =
  NO，queue/worker/webhook = NO，adapter action executable = NO。
- C09G：本轮只做文档封板；未修改 backend/frontend runtime 代码，未新增 API/UI/migration，
  未发布 staging/production，未创建 execution request，未执行 adapter action，未连接 live
  provider，未进入 C10，未 git commit。
- C09D：新增 `docs/C09_EXECUTION_PROVIDER_VERIFICATION.md`，归档 Execution
  Provider verify/test 体系；明确 C09D 只做自动化验证和文档，不新增 runtime、
  execution submit API、migration、staging/production 发布、adapter action execution、
  live provider 或 K01/P 系列接入。
- C09D：强化 `tests/backend/test_execution_providers_registry.py`，新增 provider
  rule matrix 和负例防回退，覆盖 provider key 唯一/命名、C08 action binding、
  permission/risk/operation-log inheritance、approval C12、secret C14、scope C18、
  no-live/no-callback/no-artifact-path/no-log-write、read-only API 和 C08/C07/C05/C06
  regression。
- C09D：强化 `tests/frontend/execution-provider.test.mjs`，新增 exact GET-only
  proxy allowlist 矩阵、execution_required / approval_required / secret_required /
  scope_required action state 矩阵，以及 `ExecutionProviderStatusShell` disabled
  no-submit 安全展示断言。
- C09C：新增前端 Execution Provider 只读模型、GET-only API client、状态壳层和
  disabled action submit state；新增文件包括
  `frontend/src/lib/execution-provider.ts`、
  `frontend/src/lib/execution-provider-api.ts`、
  `frontend/src/components/execution-provider-status-shell.tsx`、
  `tests/frontend/execution-provider.test.mjs` 和
  `docs/C09_EXECUTION_PROVIDER_FRONTEND.md`。
- C09C：frontend backend proxy 精确加入
  `GET /api/backend/execution-providers/registry` 和
  `GET /api/backend/execution-providers/me`；继续拒绝 execution provider wildcard、
  `/executions`、`/execution` 以及 execute/run/submit/cancel/retry 通道。
- C09C：`AdapterAccessProvider` 现在只读加载 C09B provider registry/access state；
  C08 `ModuleAdapterShell` 的 `action_contract` 展示升级为 execution-aware but no-execute，
  找不到 provider 时显示 `provider_pending` / waiting C09，approval/secret/scope required
  分别显示 waiting C12/C14/C18。
- C09C：所有前端 provider/action state 继续强制 `executable=false`、
  `can_request_execution=false`，不生成 submit payload、request id、idempotency key、
  operation log 或 artifact ref，不执行 adapter action，不连接 live provider，不创建真实任务，
  不新增 migration，不发布 staging/production。
- C09B：新增后端 Execution Provider Contract v1、Execution Request/Result/State
  schema 草案、静态 no-op/mock/contract-only/future provider registry 和只读 API；
  新增文件包括 `backend/app/schemas/execution_provider.py`、
  `backend/app/core/execution_providers.py`、
  `backend/app/services/execution_provider_registry.py`、
  `backend/app/api/routes/execution_providers.py` 和
  `tests/backend/test_execution_providers_registry.py`。
- C09B：新增 authenticated read-only `GET /execution-providers/registry` 和
  `GET /execution-providers/me`；registry 返回安全 provider metadata，`/me` 基于 C05/C06
  effective permissions、C07 module access、C08 adapter access 和 C08 action_contract
  返回 provider/action visibility、locked/hidden/unavailable/blocked reason、approval /
  secret / scope status 和 no-execute reason。
- C09B：provider validation 覆盖 `provider_key` 唯一和命名、version/type/status/
  lifecycle、execution mode/action type、C07 `module_key`、C08 `adapter_key` /
  `action_key`、继承 C08 `required_permission` / `risk_level` /
  `operation_log_action`、approval-required 和 execution-required no-execute、
  secret requirement declared-only、schema 可序列化、no live provider、no operation log
  write，以及 C05/C06/C07/C08 回归。
- C09B：初始 registry 只注册 `core.no_op_provider`、`core.mock_provider`、
  `core.contract_only_provider`、`future.local_backend_provider`、`future.queue_provider`、
  `future.webhook_provider`、`future.scheduled_provider` 和 `future.live_provider`；
  所有 provider 均 `executable=false`、`can_request_execution=false`，future providers
  保持 provider_pending 或 disabled。
- C09B：新增 `docs/C09_EXECUTION_PROVIDER_BACKEND.md`，归档 contract 字段、request/result/
  state schema、provider lifecycle/status、C08 action binding、permission/risk/approval/
  secret/scope 阻断、API 语义、operation_log_policy declared-only 和 no-execute 安全边界；
  本轮没有新增 frontend UI、migration、execution submit API、queue、worker、webhook
  execution、live provider、adapter action execution 或真实业务任务。
- C09A：新增 `docs/C09_EXECUTION_PROVIDER_PLAN.md`，完成 Execution Provider
  审计与方案设计；确认 C08 Module Adapter 已在 `17b371a` 封板，C09 可以开始，C09
  目标是定义 adapter action 如何形成受控 execution request，而不是执行真实 action、
  接 live provider 或接真实业务。
- C09A：定义 Execution Provider Contract v1 草案字段，覆盖 `provider_key`、
  `provider_version`、`provider_type`、`provider_status`、execution modes、module/
  adapter/action binding、request/result/state schemas、required permissions、risk
  level、approval/secret/scope requirements、idempotency/retry/timeout/cancel/
  concurrency/rate-limit policies、operation log/audit/artifact/callback/failure
  policies、fallback/unavailable behavior、tests 和 docs path。
- C09A：定义 execution request 生命周期和 schema，包括 `draft`、`requested`、
  `blocked_permission`、`blocked_approval_required`、
  `blocked_provider_unavailable`、`accepted`、`queued`、`running`、`succeeded`、
  `failed`、`cancelled`、`timed_out`、`retry_scheduled`、`skipped`、`rejected`、
  `archived`，以及 `execution_id`、`request_id`、`idempotency_key`、actor、
  target scope、provider、status、result summary、artifact refs、safe error 和
  operation log ref。
- C09A：明确 C09 与 C12 Approval Gate、C13 Module Switch、C14 Secret Rules、
  C15 n8n 接入和 C18 formal scope 的边界；high-risk action 不直接执行，secret-bearing
  provider 不读取 env 或 credential，future n8n provider 只作为 C15 预留。
- C09A：规划 C09B-C09G 拆分：C09B 后端 contract/no-op provider registry、C09C
  前端 execution status shell / disabled submit state、C09D verify/test、C09E
  staging 验收、C09F production 发布归档、C09G 封板；本轮没有新增 API/UI/migration，
  没有发布 staging/production，没有执行 adapter action。
- C08G：新增 `docs/C08_MODULE_ADAPTER_SEAL.md`，归档 C08 Module Adapter
  最终封板；确认 C08A 方案、C08B 后端 adapter registry/contract、C08C 前端 adapter
  shell/placeholders、C08D verify/test、C08E staging 验收和 C08F production 发布归档
  链条完整。
- C08G：更新 README、CHANGELOG、backend/frontend README 和 C08A-F 文档，明确 C08
  已封板；本轮不发布 staging/production，不修改 runtime 代码，不新增 API/UI/migration，
  不读取或修改 env，不执行 adapter action，不接 K01/P 系列或真实业务。
- C08G：封板边界保留 `/users` owner-only、`/auth/register` 404、
  `role_default_permissions` 不自动生效、`super_admin` 不默认全局；下一步建议 C09
  Execution Provider，但 C08G 不启动 C09。
- C08F：新增 `docs/C08_MODULE_ADAPTER_PRODUCTION_RELEASE.md`，归档 production
  Module Adapter 发布；经批准按 OPS01 safe release 顺序发布 production backend 和
  frontend，生产 `/module-adapters/registry`、`/module-adapters/me` 未登录均返回
  401，frontend proxy exact allowlist 对 `/api/backend/module-adapters/registry` 和
  `/api/backend/module-adapters/me` 返回 401，`/api/backend/module-adapters/not-allowed`
  返回 404。
- C08F：production frontend bundle 命中 C08C adapter shell 证据，包括
  `AdapterAccessProvider`、adapter API paths、`Action contracts`、C09 Execution
  Provider 等待文案、C12 Approval Gate 等待文案和 dependency safety helper；C08F
  未执行 Alembic upgrade，production current/heads 仍为 `c05b_permissions_001 (head)`。
- C08F：确认 production/staging smoke、dual-env status、safe-release plan、C05/C06/C07
  未登录回归均通过；未读取真实 env，未操作 production/staging postgres，未直接查库，
  未创建测试账号，未 grant/update/revoke 权限 assignment，未执行 adapter action，未接
  K01/P 系列或 n8n/WooCommerce/MinIO/Filebrowser live provider。
- C08E：新增 `docs/C08_MODULE_ADAPTER_STAGING_ACCEPTANCE.md`，归档 staging
  Module Adapter 验收；经批准执行 staging backend/frontend safe release，发布 C08B
  `/module-adapters/registry`、`/module-adapters/me` 和 C08C frontend adapter
  shell。staging 未登录 adapter backend/proxy 均返回 401，proxy
  `/api/backend/module-adapters/not-allowed` 返回 404，staging bundle 命中
  `AdapterAccessProvider`、`Action contracts`、C09 Execution Provider 和 C12
  Approval Gate marker。
- C08E：确认本轮未执行 Alembic upgrade，未操作 staging/production postgres，未直接
  查库，未读取真实 env，未发布 production，未创建测试账号，未 grant/update/revoke
  权限 assignment，未执行 adapter action，未接 K01/P 系列或 n8n/WooCommerce/MinIO/
  Filebrowser live provider；owner/non-owner live API 因无 approved staging auth
  material 未运行，由 Docker backend tests 和 frontend Node tests 覆盖 contract。
- C08D：新增 `docs/C08_MODULE_ADAPTER_VERIFICATION.md`，归档 Adapter contract
  verify/test 体系；明确 C08D 只做测试和只读 verifier，不实现 Execution Provider、
  Module Switch、Approval Gate、sandbox、secret rules、n8n 接入、K01/P 系列、真实业务或
  staging/production 发布。
- C08D：强化 `tests/backend/test_module_adapters_registry.py`，覆盖 Module Adapter v1
  必填字段、`adapter_key` 唯一和命名、version/status/lifecycle/surface、C07 `module_key`
  绑定、route/API/nav namespace、permission/action/operation-log bindings、execution/
  approval no-execute、dependency/status/health/data contract safety、scope pending、
  K01/P 系列不启用、live provider 禁止，以及 `/modules/*`、`/permissions/me`、C06B
  assignment API、`/users` owner-only、`/auth/register` 404 回归。
- C08D：强化 `tests/frontend/module-adapter.test.mjs`，覆盖 adapter proxy exact
  allowlist、`/module-adapters/*` 宽通配禁止、helper/provider/shell/API client 文件存在、
  `adapter_pending`/draft/disabled/deprecated 不可执行、`available_actions` 安全降级、
  execution_required 等待 C09、approval_required 等待 C12、action state 不生成 payload、
  API client 不创建 POST/PUT/PATCH/DELETE execution call、dependency safe display、
  owner/non-owner metadata 行为和 C05/C06/C07 回归。
- C08D：强化 `frontend/scripts/verify-foundation.mjs`，继续检查 C05/C06/C07 proxy
  allowlist，同时新增 C08D no-execute/no-live 静态检查：adapter helper 必须强制
  `isAdapterExecutable()` 返回 false，adapter shell 不允许 `fetch()`/`apiRequest()` action
  调用，adapter API client 不允许 mutation method 或 action execution route，live
  n8n/WooCommerce/MinIO/Filebrowser provider/action marker 继续禁止。
- C08C：新增前端 Module Adapter 类型、normalizer 和 no-execute helper：
  `frontend/src/lib/module-adapter.ts`；覆盖 `ModuleAdapterContract`、
  `ModuleAdapterAccessState`、adapter status/lifecycle/surface/action/capability/
  binding/dependency/execution/approval 类型，以及 `isAdapterExecutable()`
  永远返回 false、action contract state 不生成 executable payload。
- C08C：新增 `frontend/src/lib/module-adapter-api.ts`，通过现有 restricted
  frontend backend proxy 调用 authenticated read-only `GET /module-adapters/registry`
  和 `GET /module-adapters/me`；API 失败时返回 safe unknown/unavailable 降级，不打印
  token、password、secret 或 Authorization header。
- C08C：新增 `AdapterAccessProvider`、`useAdapterAccess`、`useAdapterRegistry`、
  `useAdapterState(adapterKey)` 和 `useAdapterStateForModule(moduleKey)`，与 C07C
  `ModuleAccessProvider` 并存；C07 仍负责 module visible/locked/hidden/unavailable，
  C08C 只展示 adapter surfaces/contracts。`/module-adapters/me` 不可用时，非 owner
  不暴露 admin/system adapter metadata。
- C08C：新增 `AdapterSurfaceShell`、`AdapterSurfacePlaceholder`、
  `AdapterStatusBadge`、`AdapterCapabilitiesList`、`AdapterActionContractsList`、
  `AdapterDependencySummary`、`AdapterDataContractsSummary` 和
  `AdapterUnavailableNotice`；展示 adapter status、supported surfaces、pages/nav/
  route/api bindings、capabilities、action/data/input/output contracts 和安全
  dependency names。
- C08C：action contracts 只显示 disabled declaration，按钮显示 `Execution Provider
  not connected`；execution required action 显示等待 C09 Execution Provider，
  approval required action 显示等待 C12 Approval Gate；不执行 action、不创建任务、
  不写 operation log。
- C08C：frontend proxy 精确 allowlist `GET /module-adapters/registry` 和
  `GET /module-adapters/me`，并在 `frontend/scripts/verify-foundation.mjs` 中检查
  不存在危险 `/module-adapters/*` 宽通配，同时保持 C05/C06/C07 proxy 校验不回退。
- C08C：新增 `tests/frontend/module-adapter.test.mjs`，覆盖 adapter proxy、
  verify-foundation、adapter_pending/disabled/deprecated 不可执行、execution/approval
  action 不可执行、owner/non-owner admin visibility、business locked、missing access
  safe fallback、dependency safe names、K01/P 系列默认不启用，以及 C05/C06/C07
  owner-only 和 route guard 回归。
- C08C：新增 `docs/C08_MODULE_ADAPTER_FRONTEND.md`，归档前端 adapter shell 设计、
  API 调用、provider/hooks、supported surfaces、action/capability/data contract 展示、
  dependency safety，以及不做 Execution Provider/Module Switch/Approval Gate/K01/
  P 系列/live provider 的边界。
- C08B：新增后端 Module Adapter Contract v1 和静态 adapter registry，包含
  `backend/app/schemas/module_adapter.py`、`backend/app/core/module_adapters.py`、
  `backend/app/services/module_adapter_registry.py` 和
  `backend/app/api/routes/module_adapters.py`；采用代码内 registry，不新增数据库表或
  migration。
- C08B：新增 authenticated read-only `GET /module-adapters/registry` 和
  `GET /module-adapters/me`；registry API 返回安全 adapter metadata，me API 基于 C07
  module access state 和 C05/C06 effective permissions 返回当前用户 adapter visibility、
  surfaces、action contracts、available/locked/unavailable actions、required/missing
  permissions、execution provider state 和 approval declaration。
- C08B：初始 adapter registry 只注册 `core.dashboard.adapter`、`admin.users.adapter`、
  `admin.permissions.adapter`、`business.products.placeholder.adapter` 和
  `integration.n8n_test_bridge.adapter`；business products 与 n8n test bridge 均保持
  `adapter_pending`、unavailable、not executable，不接真实业务。
- C08B：adapter validation 覆盖 adapter key/version/status/surface、C07 `module_key`
  绑定、route/API/nav namespace 不越界、permission bindings 可追踪、action_contracts
  必须声明 permission/risk/operation_log_action、execution action C09 前不可执行、
  dependency declarations 仅允许安全依赖名且不含 secret/token/password/env/URL/credential。
- C08B：新增 `tests/backend/test_module_adapters_registry.py`，覆盖 adapter API 鉴权、
  owner/non-owner access state、business locked/show_locked、admin hidden、role defaults
  不自动生效、`super_admin` 不默认全局、adapter_pending/disabled 不可执行、execution
  provider required action unavailable、K01/P 系列不启用、n8n bridge 不 live connected，
  以及 `/modules/registry`、`/modules/me`、`/permissions/me`、C06B assignment API、
  `/users` owner-only 和 `/auth/register` 404 回归。
- C08B：新增 `docs/C08_MODULE_ADAPTER_BACKEND.md`，归档后端 adapter contract/registry/API、
  lifecycle/status、supported surfaces、pages/routes/nav/api bindings、capabilities/actions、
  status/health/data/input/output contracts、permission/scope/operation log bindings、
  dependency/execution/approval declarations 和明确不做 Execution Provider/Module Switch/
  Approval Gate/K01/P 系列/live provider 的边界。
- C08A：新增 `docs/C08_MODULE_ADAPTER_PLAN.md`，完成 Module Adapter 审计与方案设计；确认
  C07 模块隔离体系已封板，C08 可以开始，C08 目标是定义模块如何正规接入控制台的
  adapter contract，而不是执行任务、接真实业务或实现 K01/P 系列 runtime。
- C08A：定义 Module Manifest 与 Module Adapter 分工。Manifest 是模块身份证和边界声明，
  说明模块是谁、在哪里、需要什么权限、状态是什么；Adapter 是模块接入控制台的标准接口，
  说明模块如何交付 pages、routes、nav entries、capabilities、actions、status、health、
  data contracts、permission bindings、operation log bindings 和 dependency declarations。
- C08A：提出 Module Adapter v1 草案字段，包括 `adapter_key`、`adapter_version`、
  `module_key`、`manifest_version`、`adapter_status`、`supported_surfaces`、`pages`、
  `nav_bindings`、`route_bindings`、`api_bindings`、`capabilities`、`actions`、
  `action_contracts`、`status_provider`、`health_provider`、`data_contracts`、
  `permission_bindings`、`scope_bindings`、`operation_log_bindings`、
  `dependency_declarations`、`execution_requirements`、`sandbox_requirements`、
  `approval_requirements`、`secret_requirements`、fallback/unavailable behavior 和
  `test_contracts`。
- C08A：明确 Adapter lifecycle 包含 `draft`、`adapter_pending`、`contract_ready`、
  `test_ready`、`staging_ready`、`production_ready`、`disabled`、`deprecated`、`sealed`；
  `adapter_pending` 和 disabled-by-default 模块不可 executable，不连接 provider，不触发真实
  action。
- C08A：明确 C08 只声明 action contract，C09 才执行；C08 只声明 module switch/feature flag
  bindings，C13 才实现启停；C08 只声明 `scope_bindings` pending，C18 才做正式 scope；C08
  只声明 dependency needs，C14/C15 才处理 secret 和 n8n 接入。
- C08A：明确 K01 是未来业务模块，不是 C08；K01 未来正式接入必须提供 Module Adapter，但
  C08A 不开发 K01、不修改 K01 worktree。P 系列是 n8n workflow，不是 C08；未来应通过
  action/execution capability 或 C15 n8n 规范接入，C08A 不读取或修改 P-series workflow JSON。
- C07G：新增 `docs/C07_MODULE_ISOLATION_SEAL.md`，归档 C07 模块隔离体系最终封板；确认
  C07A 模块隔离方案、C07B 后端 Module Manifest v1 / Module Registry、C07C 前端
  module-aware navigation / route guard、C07D verify/test 体系、C07E staging 验收和
  C07F production 发布归档均已完成。
- C07G：封板结论确认 production 后端 module registry 和 production 前端 module-aware
  navigation / route guard 已上线；`/modules/registry` 与 `/modules/me` 均要求登录且未登录
  401；frontend proxy 仅精确放行 `/api/backend/modules/registry` 与
  `/api/backend/modules/me`，不放开危险 `/modules/*` 宽通配。
- C07G：最终边界确认 business 模块无权限 `show_locked` / `locked`，admin/system 模块无权限
  `hide_when_denied` / `hidden`，`planned` / `adapter_pending` / `unavailable` 不可
  executable，User Management 和 Permission Management 仍 owner-only，`/users` 仍
  owner-only，`/auth/register` 仍 404，C05/C06 未被破坏。
- C07G：明确 C07 未接 K01、P 系列、n8n/WooCommerce/MinIO/Filebrowser 真实业务，未创建真实
  业务任务，未实现 Module Adapter、Execution Provider、模块沙箱、模块开关、审批门、密钥规则
  或 n8n 接入规范；下一步建议 C08 Module Adapter，但不在 C07G 中启动。
- C07F：新增 `docs/C07_MODULE_PRODUCTION_RELEASE.md`，归档 production 模块隔离发布和
  验收；本轮仅执行 production backend/frontend safe release，未执行 Alembic upgrade，
  未操作 production/staging postgres，未直接 psql/SQL，未读取真实 env，未发布 staging，
  未接 K01/P 系列或 n8n/WooCommerce/MinIO/Filebrowser 真实业务。
- C07F：production backend safe release 成功，发布 C07B `/modules/registry` 和
  `/modules/me` runtime；production frontend safe release 成功，发布 C07C
  ModuleAccessProvider、module-aware navigation / route guard 和精确 module proxy
  allowlist。
- C07F：发布后 production backend 未登录 `/modules/registry` 与 `/modules/me` 返回 401；
  frontend proxy 精确放行 `/api/backend/modules/registry` 与
  `/api/backend/modules/me` 并返回 backend auth 401，危险
  `/api/backend/modules/not-allowed` 仍 404；frontend bundle marker 命中 C07C
  module-aware 代码。
- C07F：production Alembic `current` 和 `heads` 均保持 `c05b_permissions_001 (head)`；
  C05/C06 未登录回归保持 `/auth/me`、`/permissions/me`、`/users` 为 401，
  `/auth/register` 为 404；owner/non-owner live login 因无 approved production auth
  material 未执行，相关规则由 C07D tests 和 C07E staging 验收覆盖。
- C07E：新增 `docs/C07_MODULE_STAGING_ACCEPTANCE.md`，归档 staging 模块隔离发布和
  验收；本轮仅执行 staging backend/frontend safe release，未执行 Alembic，未操作
  staging/production postgres，未读取真实 env，未发布 production，未接 K01/P 系列或
  n8n/WooCommerce/MinIO/Filebrowser 真实业务。
- C07E：staging backend safe release 成功，发布 C07B `/modules/registry` 和
  `/modules/me` runtime；staging frontend safe release 成功，发布 C07C module-aware
  navigation / route guard、ModuleAccessProvider 和精确 module proxy allowlist。
- C07E：发布后 staging 未登录 `/modules/registry` 与 `/modules/me` 返回 401；
  frontend proxy 精确放行 `/api/backend/modules/registry` 和
  `/api/backend/modules/me`，危险 `/api/backend/modules/not-allowed` 仍 404；frontend
  bundle marker 命中 module-aware navigation / route guard。
- C07E：修复 frontend Docker verification stage，复制 `tests/frontend/` 到
  `/tests/frontend/`，使 C07D verifier 可在 release image build 中检查
  `tests/frontend/module-isolation.test.mjs`；runtime image 不复制测试目录。
- C07E：记录 owner/non-owner live 登录验收限制。本轮未获得 approved staging owner
  凭据，也未发现 active staging-only non-owner 测试账号；未创建账号、未 grant/update/
  revoke staging assignment，相关 owner/non-owner 行为由 C07D Docker/Node tests 覆盖，
  不伪造 staging 通过。
- C07D：新增 `docs/C07_MODULE_ISOLATION_VERIFICATION.md`，归档模块隔离 verify/test
  体系；明确 C07D 只强化测试和只读 verifier，不实现 Module Adapter、Execution
  Provider、module switch、sandbox、审批门、密钥规则，不新增后端业务 API、前端业务 UI
  或 migration，不接 K01/P 系列/n8n/WooCommerce/MinIO/Filebrowser，不发布 staging 或
  production。
- C07D：强化 `tests/backend/test_modules_registry.py`，覆盖 Module Manifest v1 必填字段、
  `module_key` 唯一和命名、category/status/lifecycle/denied_behavior 合法性、business
  `show_locked`、admin/system `hide_when_denied`、route/API namespace、permission
  manifest 对齐、泛 permission key 禁止、external dependency 安全、K01/P 系列和真实
  provider 值禁止、`integration.n8n_test_bridge` test-only/adapter_pending 边界、
  planned/adapter_pending/unavailable 不可执行，以及 C05/C06 `/users`、`/auth/register`、
  `/permissions/me`、C06B assignment API、`role_default_permissions` 和 `super_admin` 回归。
- C07D：强化 `tests/frontend/module-isolation.test.mjs`，覆盖 C07 proxy 精确 allowlist、
  navigation `module_key` 和 registry 对齐、User Management=`admin.users`、Permission
  Management=`admin.permissions`、non-owner admin/system hidden、business locked、owner
  可见、planned/adapter_pending/unavailable route guard decision、`/modules/me` 失败安全
  降级、external dependency 展示安全、wildcard 不绕过 access state、No Permission /
  Module Unavailable 文案不泄密，以及 C05D/C06C helper 回归。
- C07D：强化 `frontend/scripts/verify-foundation.mjs`，解析并校验 C07 module proxy
  allowlist 只包含 `modules/registry` 和 `modules/me`，拒绝 `/modules/*` 宽通配，继续
  检查 `/permissions/me`、`/permissions/registry` 和 C06B assignment proxy，确认 C07C
  helper/provider/test 文件存在，并阻止默认启用 K01/P 系列菜单或 live
  n8n/WooCommerce/MinIO/Filebrowser action marker。
- C07C：新增前端 module registry 类型、归一化 helper、module access helper 和 API client，
  通过现有 restricted frontend backend proxy 调用 `GET /modules/registry` 与
  `GET /modules/me`；API 失败时返回安全错误摘要并标记 `module_access_unknown`，不打印
  token/password/Authorization header。
- C07C：frontend proxy 精确放行 `GET /modules/registry` 和 `GET /modules/me`，不放开
  `/modules/*` 通配；`frontend/scripts/verify-foundation.mjs` 增加 C07 module registry
  allowlist 防回归检查。
- C07C：前端导航切到 C07B namespaced `module_key`，覆盖 `core.dashboard`、
  `experimental.foundation_demo`、`integration.n8n_test_bridge`、`admin.users`、
  `admin.permissions`、`admin.modules`、`admin.agents`、`admin.workflows`、
  `admin.settings`、`business.products`、`business.jobs`、`business.artifacts`、
  `business.reviews`、`system.errors` 和 `system.memory_events`；Permission Management
  仍作为 `/users` 内部 owner-only panel 记录为 `admin.permissions`，不新增独立菜单。
- C07C：Console Shell 和 route guard 接入 `/modules/me` access state；business denied
  继续 `show_locked`，admin/system denied 继续 `hide_when_denied`，locked/planned/
  adapter_pending/unavailable 在 sidebar 显示安全状态，直接访问 hidden/locked/unavailable
  module 时显示 No Permission 或 Module Unavailable。
- C07C：新增 `tests/frontend/module-isolation.test.mjs`，覆盖 module proxy allowlist、
  verify-foundation 检查、helper access state、navigation registry 对齐、User Management
  / Permission Management owner-only、route guard decision、external dependency 安全过滤、
  C05D/C06C 回归、`role_default_permissions` 不自动生效和 `super_admin` 不默认全局。
- C07C：新增 `docs/C07_MODULE_FRONTEND_ISOLATION.md`，归档前端 module-aware navigation /
  route guard、API 调用、安全降级、business `show_locked`、admin/system
  `hide_when_denied`、planned/adapter_pending/unavailable 展示、C05/C06 owner-only 边界和
  不接真实业务/K01/P 系列/n8n/WooCommerce/MinIO/Filebrowser/Adapter/Execution Provider。
- C07B：新增后端 Module Manifest v1 和只读 Module Registry 基础，包含
  `backend/app/schemas/module.py`、`backend/app/core/modules.py`、
  `backend/app/services/module_registry.py`，采用代码内静态 registry，不新增数据库表或
  migration。
- C07B：新增 authenticated `GET /modules/registry` 和 `GET /modules/me`；
  `/modules/registry` 返回安全的 module manifest metadata，`/modules/me` 基于当前用户
  C05/C06 effective permissions 返回 `available`、`locked`、`hidden`、`planned`、
  `adapter_pending`、`unavailable` 等 access state。
- C07B：初始 registry 覆盖当前控制台已有或平台内置模块，包括 `core.dashboard`、
  `experimental.foundation_demo`、`integration.n8n_test_bridge`、`admin.users`、
  `admin.permissions`、`admin.modules`、`admin.agents`、`admin.workflows`、
  `admin.settings`、`business.products`、`business.jobs`、`business.artifacts`、
  `business.reviews`、`system.errors`、`system.memory_events` 和
  `system.operation_logs`；占位模块标记为 `planned` 或 `adapter_pending`，不可执行。
- C07B：新增 `tests/backend/test_modules_registry.py`，覆盖 `/modules/registry` 和
  `/modules/me` 鉴权、manifest 校验、business `show_locked`、admin/system
  `hide_when_denied`、external dependency 安全声明、K01 未接入、owner/non-owner access
  state、role defaults 不自动生效、`super_admin` 不默认全局、`/users` owner-only、
  `/auth/register` 404、C06B assignment API 和 `/permissions/me` 回归。
- C07B：新增 `docs/C07_MODULE_REGISTRY_BACKEND.md`，归档 C07B 后端 registry 做了什么、
  Module Manifest v1 字段、初始模块列表、API 语义、owner/non-owner 访问规则、
  planned/adapter_pending/unavailable 行为和 C07C 下一步边界。
- C07A：新增 `docs/C07_MODULE_ISOLATION_PLAN.md`，完成模块隔离审计与方案设计；文档确认 C07 可以开始，C01-C06 已完成控制台部署、环境隔离、账号、角色、权限、权限管理闭环，C07 目标是模块隔离，不接真实业务，C07A 只做方案、不实现功能。
- C07A：归纳当前控制台内置板块与核心能力，包括 Dashboard、Foundation Demo、n8n Test Bridge、Products、Modules、Agents、Workflows、Jobs、Artifacts、Reviews、Errors、Memory Events、User Management、Permission Management、Settings、Auth、Health 和 Operation Logs，并明确这些现状还不是正式 Module Manifest v1。
- C07A：提出 Module Manifest v1 草案、`module_key` 命名规则、模块分类、模块状态/lifecycle、权限声明、navigation、route namespace、API namespace、external dependencies、denied/unavailable behavior、K01 adapter_pending 接入边界、C07 与 C08/C09/C10/C13/C15/C18 分工，以及 C07B-C07G 拆分和未来测试验收策略。
- C06F：新增 `docs/C06_PERMISSION_MANAGEMENT_SEAL.md`，归档 C06 用户权限管理系统最终封板；确认 C06A 方案审计、C06B 后端 owner-only assignment API、C06C 前端 User Management 权限 UI、C06D staging 动态验收和 C06E production 发布归档均已完成，C06 已封板。
- C06F：同步 README、backend README、frontend README 和 C06A-E 文档 sealed 引用；最终边界保持 `/permissions/users/{user_id}/assignments` list/grant/update/revoke API 全部 owner-only、权限管理入口仅 owner 可见、`/users` owner-only、`/auth/register` 404、owner 全局全权限、`super_admin` 不默认 grant/revoke、`role_default_permissions` 不自动生效、high-risk 二次确认保留、grant/update/revoke 由后端写 `operation_logs`。
- C06F：封板记录明确 C06 不包含完整 company/factory/department scope 管理，不接 n8n/P 系列/WooCommerce/MinIO/Filebrowser 真实业务，不创建 production 测试账号，不执行 production grant/update/revoke 写入型动态验证；production `permission_registry` 已在 C06E 经批准通过后端 helper 初始化 seed，count=18。
- C06E：新增 `docs/C06_PERMISSION_PRODUCTION_RELEASE.md`，归档 production 权限管理安全发布；本轮仅按 OPS01 safe release 发布 production backend/frontend，未执行 Alembic upgrade，未操作 production postgres 容器，未直接 psql/SQL 操作 production DB，未读取真实 env，未发布 staging，未接真实业务。
- C06E：完成 production owner 权限管理只读验收；owner `/auth/me`、`/permissions/me`、`/permissions/registry`、`/permissions/users/{user_id}/assignments`、`/users` 均返回 200，registry count 为 18，assignment list 对 owner 合理为空，`/users` 未泄漏 `password_hash`，未登录 `/auth/me`、`/permissions/me`、`/users` 仍为 401，`/auth/register` 仍为 404。
- C06E：production `permission_registry` 发布后曾为空；经老板单独批准，仅在 production backend 容器内通过现有应用层 helper `upsert_permission_registry()` 初始化系统权限点 seed，未写 `user_permission_assignments`，未写 `role_default_permissions`，未 grant/update/revoke 任何 production 用户权限，未创建 production 测试账号。
- C06E：完成 production C06C frontend marker 验收；production `/users` 返回 200，linked JS bundle 包含 `C06C permissions` marker，owner frontend proxy 可读取 registry、assignment list 和 `/users`。本机无 Chromium/Playwright，未执行浏览器截图验收。
- C06D：新增 `docs/C06_PERMISSION_STAGING_ACCEPTANCE.md`，归档 staging 用户权限管理联调验收；本轮仅使用 OPS01 safe release 发布 staging backend/frontend，未发布 production，未执行 Alembic upgrade，未操作 staging postgres 容器，未直接操作数据库，未读取真实 env，未接真实业务。
- C06D：发布后发现 staging `permission_registry` 为空；经老板批准，在 staging backend 容器内通过现有应用层 helper `upsert_permission_registry()` 初始化系统权限点 seed，registry count 为 18，未新增 migration、未手写 SQL、未 psql、未操作 postgres 容器。
- C06D：完成 staging 动态验收；owner assignment list、普通 `artifacts.read` grant/update/revoke、`/permissions/me` 生效和移除、high-risk `jobs.manage` reason/confirmation 阻断与成功 grant/revoke、operation_logs、non-owner 越权 403、`/users` owner-only、`/auth/register` 404、role defaults 不自动生效和 `super_admin` 不默认 grant/revoke 均通过。
- C06D：创建 staging-only 临时 viewer 测试账号 `c06d_viewer_test_1781168578`，未输出密码/token/Authorization header；测试结束后已通过 owner-only API disable，普通和 high-risk 测试 assignment 均已 revoke/disabled。
- C06C：新增 User Management 内的前端“用户权限管理”UI；owner 可从用户行“权限”入口打开用户详情权限面板，查看 explicit assignments，给非 owner 用户 grant permission，更新 enabled/expires_at/scope/reason，撤销 assignment，并在 revoke 后刷新列表。
- C06C：新增前端 permission management helper 和 API client，覆盖 `PermissionAssignment`、`PermissionAssignmentListResponse`、`PermissionAssignmentCreateInput`、`PermissionAssignmentUpdateInput`、`PermissionAssignmentActionResponse`、`PermissionRegistryItem`，并通过现有 `/api/backend` proxy 调用 C06B 的 list/grant/update/revoke assignment API 和 `/permissions/registry`。
- C06C：新增 high-risk 前端识别和二次确认 UI；按 C06B 规则识别 high/critical、users/permissions/settings/system/secrets/release/production/billing/admin 类权限，high-risk grant 要求 reason、`confirm_high_risk=true` 和 `confirmation_text="CONFIRM_HIGH_RISK_PERMISSION"`，high-risk re-enable/scope change update 要求确认，high-risk revoke 要求 reason。
- C06C：frontend proxy 精确放行 `GET/POST /permissions/users/{user_id}/assignments` 与 `PATCH/DELETE /permissions/users/{user_id}/assignments/{assignment_id}`，保留 `user_id` 正整数和 `assignment_id` UUID 校验，不开放通用 permissions proxy；frontend verifier 增加 C06B assignment proxy 防回归检查。
- C06C：新增 `tests/frontend/permission-management.test.mjs`，使用 Node 内置 test runner 覆盖 assignment API path、proxy allowlist、high-risk 识别、wildcard grant 阻断、role defaults 不自动生效文案、owner/non-owner 入口、owner full access target、空状态、grant/update/revoke 校验、revoke refresh 和安全错误摘要。
- C06C：新增 `docs/C06_PERMISSION_FRONTEND_UI.md`，归档 C06C 前端 UI、API client、proxy allowlist、high-risk 确认、operation_logs 分工、owner-only 边界、`role_default_permissions` 和 `super_admin` 边界，以及未发布 staging/production、未新增后端 API/migration、未接真实业务的范围。
- C06B：新增 owner-only permission assignment 后端管理 API：
  `GET /permissions/users/{user_id}/assignments`、
  `POST /permissions/users/{user_id}/assignments`、
  `PATCH /permissions/users/{user_id}/assignments/{assignment_id}`、
  `DELETE /permissions/users/{user_id}/assignments/{assignment_id}`；所有新增 route
  都使用 `require_owner()`，不向 `super_admin`、`module_admin` 或拥有
  `permissions.manage` 的非 owner 默认开放。
- C06B：新增/扩展 permission assignment schemas、repository 写入 helper 和
  permission service 管理入口，支持 list/grant/update/revoke、registry key 校验、
  wildcard 拒绝、owner target 拒绝、duplicate active assignment 拒绝、soft revoke、
  scope_type/scope_key 与 scope_id 兼容返回，以及 grant/revoke/update 后
  `/permissions/me` 按最新 assignment 生效。
- C06B：新增 high-risk 权限策略，优先使用 `permission_registry.risk_level`，并覆盖
  users/permissions/settings/system/secrets/release/production/billing/admin 类权限；
  high-risk grant 和 high-risk 重新启用或 scope 变更要求 reason、
  `confirm_high_risk=true` 与
  `confirmation_text="CONFIRM_HIGH_RISK_PERMISSION"`。
- C06B：grant/update/revoke 沿用现有 `operation_logs` 和
  `create_operation_log()`；action 使用 `permission.assignment.grant`、
  `permission.assignment.update`、`permission.assignment.revoke`，details 记录 actor、
  target、permission_key、assignment_id、scope、before/after、reason、risk_level、
  confirmation 和 result。
- C06B：新增 `tests/backend/test_permission_assignments_api.py`，覆盖 owner-only、
  non-owner/super_admin 禁止、普通 grant 后 `/permissions/me` 生效、wildcard/不存在
  permission/owner target/重复 active assignment 拒绝、high-risk 确认、update、
  expired/disabled 不生效、revoke 软撤销、operation_logs、`/users` owner-only、
  `/auth/register` 404、role defaults 不自动生效。
- C06B：新增 `docs/C06_PERMISSION_BACKEND_ACCESS.md`，归档 C06B 后端 API、owner-only
  原因、super_admin 和 role_default_permissions 边界、high-risk 二次确认、
  operation_logs 写入策略、`/users` owner-only 保持不变，以及 C06C/C06D/C06E/C06F
  后续拆分。
- C06A：新增 `docs/C06_PERMISSION_MANAGEMENT_PLAN.md`，完成用户权限管理页面与
  grant/revoke 方案审计；文档确认 C05 已封板且 production 生效，当前
  `permission_registry`、`user_permission_assignments`、`role_default_permissions`、
  `/auth/me.permissions`、`/permissions/me`、`/permissions/registry`、`/users`
  owner-only 和前端 User Management owner-only 的真实状态，并明确 C06A 不实现
  API/UI、不新增 migration、不发布、不接真实业务。
- C06A：提出 C06B owner-only assignment list/grant/revoke/update API 草案、
  operation_logs 记录结构、高风险权限二次确认规则、owner 防自锁规则、non-owner
  防越权规则、scope 第一版策略、User Management 内权限管理 UI 草案、测试计划，以及
  C06B/C06C/C06D/C06E/C06F 后续拆分。
- C05G：新增 `docs/C05_PERMISSION_SYSTEM_SEAL.md`，归档 C05 权限系统最终封板结论；
  明确 C05A-F 已形成完整闭环，staging 和 production 已完成验收，production 已发布并通过
  owner 验收，下一步是 C06 或 C18/业务模块接入前置规划，不进入 P 系列，不接真实业务。
- C05G：封板文档记录最终权限模型：role 只是基础身份，permission assignment 才是实际授权来源，
  owner 全局全权限，`super_admin` 不默认全局权限，`role_default_permissions` 不自动生效，
  scope 仅预留，未来业务模块必须带 Permission Manifest。
- C05G：封板文档记录最终安全边界：`/users` 仍 owner-only，User Management 仍仅 owner full
  access 可见，前端权限只是 UX，后端 `require_permission()` / `require_owner()` 仍是真实安全边界；
  C05 不包含 grant/revoke API、权限分配 UI、完整组织 scope 管理或真实业务接入。
- C05F：新增 `docs/C05_PERMISSION_PRODUCTION_RELEASE.md`，归档权限系统 production
  安全发布和验收；本轮使用 OPS01 safe release 发布 production backend/frontend，在
  production backend 容器内执行 Alembic `upgrade head` 到
  `c05b_permissions_001 (head)`，未操作 production postgres 容器，未直接连接
  production DB，未读取真实 env，未接真实业务。
- C05F：完成 production owner 权限 API 验收；owner `/auth/me` 和
  `/permissions/me` 返回 `is_owner_full_access=true` 且 `permission_keys` 包含
  wildcard，`/permissions/registry` 返回 list response 结构，`/users` 返回 200 且不泄漏
  `password_hash`，未登录 `/auth/me`、`/permissions/me`、`/users` 均返回 401，
  `/auth/register` 仍返回 404。
- C05F：production frontend proxy 最小放行 `GET /permissions/me` 和
  `GET /permissions/registry`，并在 frontend verify 中增加 C05 permissions proxy 防回归检查；
  该修复不新增 grant/revoke API，不新增权限分配 UI，不改变后端权限模型。
- C05F：完成 production frontend 权限 UI 验收；production `/login` 和 `/users` 页面返回
  200，owner 通过 production frontend proxy 可取得 permissions，C05D helper 验证
  User Management 对 owner visible/can_access，non-owner production 因无现成账号且不创建
  生产测试账号而未动态验证。
- C05E：新增 `docs/C05_PERMISSION_STAGING_ACCEPTANCE.md`，归档权限系统 staging
  联调验收；本轮使用 OPS01 safe release 只发布 staging backend/frontend，在 staging
  backend 容器内执行 Alembic `upgrade head` 到 `c05b_permissions_001 (head)`，未发布
  production，未读取真实 env，未操作 production 容器或数据库，未接真实业务。
- C05E：完成 staging owner 和 non-owner 权限 API 验收；owner `/auth/me` 和
  `/permissions/me` 返回 `is_owner_full_access=true`、`permission_keys=["*"]`，
  临时 staging-only `viewer` 测试账号无 wildcard、无 assignment，`/users` 返回 403，
  `/permissions/registry` 返回 403，未登录 `/auth/me`、`/permissions/me`、`/users`
  均返回 401，`/auth/register` 仍返回 404。
- C05E：完成前端权限 UX 决策验收；non-owner 的 User Management 不可见，admin/system
  入口无权限隐藏，business 入口无权限显示 locked，直接访问 `/users` 或 business 无权
  route 会进入“无权访问此板块”提示决策。
- C05D：新增前端权限感知和基础路由保护；`/auth/me.permissions` 在前端归一化为
  `is_owner_full_access`、`permission_keys`、`assignments`、`scope_summary`，
  permissions 缺失或异常时安全降级为无权限且页面不崩溃。
- C05D：新增 `frontend/src/lib/permissions.ts`、无权访问提示组件和 layout 级
  `PermissionRouteGuard`；业务板块无权限时保留导航并显示 locked，点击后显示
  “无权访问此板块”，管理/系统板块无权限时隐藏入口。
- C05D：新增 `tests/frontend/permissions.test.mjs`，用 Node 内置 test runner 覆盖 owner
  full access、普通用户业务 locked、业务权限解锁、直接访问 denied、permissions 缺失安全降级、
  以及 `/users` 仍仅 owner full access 可见。
- C05D：新增 `docs/C05_PERMISSION_FRONTEND_ACCESS.md`，记录前端权限不是安全边界、
  business `show_locked`、admin/system `hide_when_denied`、`/users` 仍 owner-only、
  本轮不做 grant/revoke UI、不接真实业务、不部署 staging/production。
- C05C：新增后端权限 dependency `require_permission(permission_key, scope_type="global",
  scope_key="*")`；owner 在 dependency 层直接通过，非 owner 只通过 enabled、未过期、
  scope 匹配的 `user_permission_assignments` 获权；`super_admin` 不默认全局权限。
- C05C：`GET /auth/me` 保持旧身份字段并追加 `permissions`；owner 返回
  `is_owner_full_access=true` 和 `permission_keys=["*"]`，非 owner 只返回 explicit
  effective assignments；`POST /auth/login` 保持旧 user response 合同。
- C05C：新增只读 `GET /permissions/me` 和 `GET /permissions/registry`；registry route
  对 owner 直接开放，非 owner 需要 `permissions.read`，本轮不新增 grant/revoke API。
- C05C：新增 `docs/C05_PERMISSION_BACKEND_ACCESS.md` 和后端权限 API 测试，覆盖 owner
  wildcard、非 owner 403、assignment 生效、scope 不反向变 global、`super_admin` 无默认全局、
  `/auth/me.permissions`、`/permissions/me`、`/permissions/registry` 和 role defaults 不自动生效。
- C05B：新增后端权限数据模型与 migration `c05b_permissions_001`，创建
  `permission_registry`、`user_permission_assignments`、`role_default_permissions`
  三张表；新增 SQLAlchemy models、Pydantic schemas、permission seed 常量、
  registry upsert、assignment grant/revoke/disable、role default storage、owner
  全局 resolver、非 owner scoped assignment 查询服务和权限测试；本轮不新增公开 API，
  不替换 `require_owner()`，不修改前端 UI，不发布 staging/production，不接真实业务。
- C05B：新增 `docs/C05_PERMISSION_DATA_MODEL.md`，记录 registry 与 assignment 的区别、
  owner 为什么不需要逐条 assignment、`super_admin` 为什么不能默认全局、role defaults
  当前不自动生效、scope 第一版预留和 C05C/C05D 下一步。
- C05A：新增 `docs/C05_PERMISSION_SYSTEM_PLAN.md`，开始权限系统阶段，只做现状审计和设计方案；文档记录当前 owner 判断、`require_owner`、`/users` owner-only、`/auth/me` 返回字段、静态前端菜单、当前没有真实 user permission/scope assignment，并提出 Permission Registry、User Permission Assignment、Role Default Permissions、Permission Scope、Module Permission Manifest、第一批基础权限点、业务/管理菜单策略、migration 判断和 C05B-C05H 后续拆分；本轮不实现功能、不新增 migration、不部署、不修改 production/staging、不接真实业务。
- OPS01E：新增 `docs/OPS01_SAFE_RELEASE_SEAL.md`，归档 Docker Compose v1 `ContainerConfig` 问题治理最终封板结论；本轮只做只读复核和文档封板，确认 safe release plan check 通过、staging/production backend/frontend 四个 dry-run 映射正确、production/staging smoke 和 dual-env status 通过、rollback tag 存在；本轮没有安装或升级工具，没有执行真实 release，没有设置确认变量，没有读取真实 env，没有修改 Nginx/证书，没有接真实业务，没有 git commit。
- OPS01D-3：新增 `docs/OPS01_PRODUCTION_SAFE_RELEASE_ACCEPTANCE.md`，归档 production backend/frontend safe release 真实演练结果；OPS01D-2 已使用 `scripts/safe_compose_release.sh` 先后完成 production backend 和 production frontend 真实发布，两次都使用 `CONFIRM_SAFE_RELEASE=yes`、`CONFIRM_PRODUCTION_RELEASE=yes` 和 `--execute`，均未触发 `docker-compose` v1 `KeyError: 'ContainerConfig'`，已生成 production backend/frontend rollback tag，production smoke、staging smoke 和 dual-env status 均通过；本轮 OPS01D-3 只做只读复核和文档归档，没有重新发布、重建、停止或删除容器，没有读取真实 env，没有修改 Nginx/证书，没有接真实业务。
- OPS01D-1：新增 `docs/OPS01_PRODUCTION_SAFE_RELEASE_DRY_RUN.md`，归档 production backend/frontend safe release dry-run、映射复核和安全门禁检查；本轮确认 production/staging smoke 和 dual-env status 通过，production backend 映射到 `barong-ops-console-prod_console_backend_1` / `http://127.0.0.1:8000/health`，production frontend 映射到 `barong-ops-console-prod_console_frontend_1` / `https://ops.barongyekhna.com/login`；本轮没有真实发布 production，没有 build、up/down、停止、删除、重建容器，没有读取真实 env，没有修改 Nginx/证书，没有接真实业务。
- OPS01C：新增 `docs/OPS01_STAGING_SAFE_RELEASE_ACCEPTANCE.md`，归档 staging safe release 真实演练结果；本轮使用 `scripts/safe_compose_release.sh` 分别发布 staging backend 和 staging frontend，绕开 `docker-compose` v1 `--force-recreate` 的 `ContainerConfig` 风险路径，生成 staging backend/frontend rollback tag，确认 staging smoke、production smoke 和 dual-env status 均通过；本轮未发布 production，未停止/删除/重建 staging postgres，未读取真实 env，未修改 Nginx/证书，未接真实业务。
- OPS01B-alt：新增 `scripts/safe_compose_release.sh`、`scripts/check_safe_release_plan.sh` 和 `docs/OPS01_SAFE_RELEASE_RUNBOOK.md`，准备基于当前 `docker-compose` v1.29.2 的短期安全发布流程；脚本默认 dry-run，真实执行必须显式 `--execute` 和确认变量，只允许 staging/production 的 backend/frontend，禁止 postgres，所有 `docker-compose` 调用必须带 project name 和 compose file。本阶段只做脚本、文档和 dry-run 检查，没有真实发布 staging/production，没有删除、停止、重建容器，没有读取真实 env，没有修改 Nginx/证书，没有接真实业务。
- OPS01A：新增 `docs/OPS01_DOCKER_COMPOSE_GOVERNANCE_PLAN.md`，用大白话归档 Docker / Compose 当前状态、项目脚本 Compose 用法扫描、`docker-compose` v1 `KeyError: 'ContainerConfig'` 根因判断、三种治理方案对比、推荐 staging-first 路线、绝对禁止项和 OPS01B-OPS01E 后续拆分；本轮只做只读审计和文档方案，不安装/升级工具，不重启/删除/重建 production/staging 容器，不读取真实 env，不修改 Nginx/证书，不接真实业务。
- C04F：新增 `docs/C04_ROLE_SYSTEM_SEAL.md`，归档角色体系总封板结论，记录 C04 已完成、标准角色 `owner` / `super_admin` / `module_admin` / `operator` / `reviewer` / `viewer` / `bot_agent` 已统一、当前可创建角色仅 `viewer` / `operator` / `reviewer`、`owner` / `super_admin` / `module_admin` / `bot_agent` 仍为 reserved、C04 不做完整 RBAC、C05 才做权限系统、production `/users` 返回 200、未登录 `/api/backend/users/roles` 和 `/api/backend/users` 返回 401、`/api/backend/auth/register` 仍返回 404，以及本轮未读取真实 env、未创建 production 用户、未重启/删除/重建容器、未修改 Nginx/证书、未接真实业务。
- C04E：新增 `docs/C04_PRODUCTION_RELEASE.md`，归档角色目录 UI production 发布后的只读验收结果，记录 C04B 后端角色目录和 C04C 前端角色目录 UI 已进入 production、`https://ops.barongyekhna.com/users` 可用、未登录 `/api/backend/users/roles` 返回 401、创建用户下拉只允许 `viewer` / `operator` / `reviewer`、`owner` / `super_admin` / `module_admin` / `bot_agent` 仍为 reserved、C04 不做完整 RBAC、C05 才做权限系统，以及本轮未新增 migration、未读取真实 env、未创建 production 用户、未重启/删除/重建容器、未修改 Nginx/证书、未接真实业务。
- C04D：新增 `docs/C04_STAGING_ACCEPTANCE.md`，归档 staging 角色目录 UI/API 验收结果，记录 `/users/roles` owner-only 行为、标准角色和可创建角色目录、reserved roles 拒绝矩阵、staging 页面检查、operation logs 验证、production 仍正常，以及本轮未读取真实 env、未 build/recreate/stop/rm 容器、未执行 `docker-compose up/down`、未修改 Nginx/证书、未接真实业务。
- C04C：前端 User Management 页面新增角色目录说明区，显示 “Current assignable roles” 的 `viewer` / `operator` / `reviewer`，以及 “Reserved roles, not assignable in C04” 的 `owner` / `super_admin` / `module_admin` / `bot_agent`，并明确完整 RBAC 留到 C05。
- C04C：`frontend/src/lib/users-api.ts` 新增 role metadata 类型和 `listUserRoles()`，通过 `/api/backend/users/roles` 调用 C04B 的 owner-only `GET /users/roles`，保留 token 不打印和用户管理错误提示。
- C04B：新增 `backend/app/core/roles.py`，统一定义标准角色 `owner` / `super_admin` / `module_admin` / `operator` / `reviewer` / `viewer` / `bot_agent`、当前 `/users` 可创建角色 `viewer` / `operator` / `reviewer`、不可创建角色 `owner` / `super_admin` / `module_admin` / `bot_agent`、role normalize/validation helper 和角色展示 metadata。
- C04B：新增 owner-only `GET /users/roles`，返回当前用户管理可创建角色和标准角色目录；不可创建角色只展示为 `assignable=false`，不开放选择或放权。
- C04B：新增 `tests/backend/test_roles.py` 并扩展用户管理测试，覆盖标准角色、可创建/不可创建角色、大小写和空格 normalize、创建/PATCH role 拒绝矩阵、非 owner 禁止访问、`/auth/register` 404、API 不返回 `password_hash` 和 operation logs。
- C04A：新增 `docs/C04_ROLE_SYSTEM_PLAN.md`，开始角色体系阶段，记录现有 role 使用方式审计、标准角色 `owner` / `super_admin` / `module_admin` / `operator` / `reviewer` / `viewer` / `bot_agent` 的边界、role 与 job_title/department/permissions/module access 的区别、C04 与 C05 的分工、migration 判断、风险分析和 C04B-C04F 后续任务拆分；本阶段只设计不实现，不接真实业务。
- C03F：新增 `docs/C03_OWNER_ACCOUNT_MANAGEMENT_SEAL.md`，归档 C03 Owner 创建子账户最终封板结论，记录 production `/users` 已可用、未登录 `/api/backend/users` 返回 401、`/auth/register` 仍返回 404、production/staging/dual env check 通过、当前只支持 owner 管理 `viewer`/`operator`/`reviewer` 子账户，并明确 `super_admin`、完整 RBAC、模块权限、邮件邀请、密码找回和真实业务接入留到后续 C04/C05 或单独任务。
- C03E：新增 `docs/C03_PRODUCTION_RELEASE.md`，归档 production 用户管理发布验收结果，记录 C03B 后端 `/users` API 和 C03C 前端 `/users` 页面已进入 production、`https://ops.barongyekhna.com/users` 可用、未登录 `/api/backend/users` 返回 401、`/auth/register` 仍返回 404、production/staging/dual env check 通过，以及本轮未读取真实 env、未创建 production 用户、未重启/删除/重建容器、未修改 Nginx/证书、未接真实业务。
- C03D：新增 `docs/C03_STAGING_ACCEPTANCE.md`，归档 staging 用户管理验收结果，记录测试用户 `c03d_test_<timestamp>` 的创建、登录、停用、启用、重置密码、非 owner 403、`role=owner` 拒绝、`/auth/register` 404、operation logs 验证和 production smoke 仍正常。
- C03C：新增受保护的 `/users` 前端用户管理页面和 System 导航入口，支持用户列表、创建 `viewer`/`operator`/`reviewer`、查看详情、更新基础 role、停用、启用和重置子账户密码；页面明确是内部账号管理，不是公开注册。
- C03C：新增 `frontend/src/lib/users-api.ts` 前端用户管理 API client，接入现有 token 和 `/api/backend` 代理，补充 401/403/409/422 友好错误提示，避免打印 password/token。
- C03C：前端 API proxy 精确放行 owner-only `/users` 相关 GET/POST/PATCH 路径，并继续不暴露通用写代理、不转发危险 headers、不破坏 `/auth`、`/health`、F10/F11/F12 代理。
- C03B：新增 owner-only `/users` 后端用户管理 API，支持列表、创建、详情、更新、停用、启用和重置子账户密码；只允许创建 `viewer`、`operator`、`reviewer` 子账户，不允许创建 `owner`。
- C03B：新增用户管理 schema、repository、service、router 和数据库集成测试，覆盖非 owner 登录、`/auth/me`、`/users` 401/403、重复 username、弱密码、禁用用户、密码重置、禁止 owner 自停用和 operation logs。
- C03A：新增 `docs/C03_OWNER_ACCOUNT_MANAGEMENT_PLAN.md`，用大白话记录现有 users/auth/frontend 鉴权审计、当前 owner-only 限制、C03 账号管理边界、后端 API 草案、前端页面草案、安全规则、migration 判断、staging-first 发布流程和 C03B-C03F 任务拆分；本阶段只设计不实现。
- C02F：新增 `docs/C02_ENVIRONMENT_ISOLATION_SEAL.md`，用大白话归档 C02 最终结论、C02A-C02F 完成清单、production/staging 当前状态、隔离规则、发布原则、n8n/workflow 未来原则、安全禁止项、剩余风险和 C02 封板结论。
- C02E：新增 `docs/C02_ENVIRONMENT_ISOLATION_ACCEPTANCE.md`，归档 production/staging 最终只读验收结果、双环境隔离证据、脚本结果、compose config 安全临时 env 方法、真实业务边界、剩余风险和 C02F 封板下一步。
- C02D：新增 `docs/C02_DUAL_ENV_OPERATIONS.md`，用大白话说明 production/staging 双环境当前运行状态、端口/容器/volume/network/env 隔离、发布原则、数据边界、n8n workflow 未来版本化要求、只读安全命令和危险命令。
- C02D：新增 `scripts/check_dual_env_status.sh`，只读检查 Git 状态、真实 env Git ignore、production/staging 容器状态、端口隔离、console Postgres 暴露面以及 production/staging smoke endpoint，不读取真实 env，不修改服务。
- C02C：记录 staging 已在服务器本机启动，frontend 为 `127.0.0.1:3100`，backend 为 `127.0.0.1:8100`，postgres 为 Docker 内网 `5432/tcp` 且 healthy，staging owner 已初始化并完成后端登录链路测试。
- C02B：新增 `docker-compose.staging.yml`、`.env.staging.example`、staging 静态检查脚本和 staging smoke check 模板，只准备测试服施工图，不启动服务。
- C02B：新增 `docs/C02_STAGING_SETUP.md`，说明 staging 与 production 的端口、命名、env、volume、network 隔离，以及 C02C 才能创建真实 `.env.staging` 和启动 staging。
- C01C：新增 `docs/C01_PRODUCTION_ACCEPTANCE.md`，归档 `https://ops.barongyekhna.com` production 验收证据、证书状态、Nginx/容器暴露面、非集成边界、已知风险和 C01 封板结论。
- C01C：补齐 production smoke check，覆盖 HTTPS login、HTTPS backend health proxy、HTTP 到 HTTPS 跳转和 `docker ps` 状态检查，不读取 `.env.production`，不修改任何服务。
- C01B-1：新增 `docker-compose.production.yml`、`.env.production.example`、Nginx 模板、production 部署文档和静态部署文件检查脚本，准备 `ops.barongyekhna.com` 正式部署文件。
- C01B-1：新增 production smoke check 脚本，用于部署后人工验收登录页/API 可达性，不包含凭证、不触发业务动作。
- F13：新增第一代空地基统一验收脚本与封板报告，覆盖后端、数据库迁移、owner 认证、F10/F11/F12 API、前端 required routes/build、Compose config、diff 和安全边界扫描。
- F13：补齐 foundation/demo 阶段说明、example-only 临时登录预览、安全启动方式、环境变量密钥规则、剩余风险和下一阶段接入边界。
- F12：新增 owner-only `POST /n8n-test/run`、公开但 callback header 鉴权的 `POST /n8n-test/callback`、owner-only `GET /n8n-test/latest`，完成 Console 与 n8n test webhook 闭环。
- F12：新增 `n8n_test_bridge` / `n8n_test_agent` / `n8n_test_webhook_workflow` demo Registry、test Job、callback Job Events、demo Artifact / Review / Memory Event、System Error 与 Operation Logs。
- F12：新增受保护的 `/n8n-test` 页面、Run n8n Test 按钮、waiting callback 自动轮询、latest event / artifact / review / memory / error 展示及 test-only 安全提示。
- F12：新增 webhook 未配置、mock HTTP payload、HTTP failure、callback secret 缺失/错误/正确、demo terminal status、敏感信息隔离和无真实集成测试。
- F11：新增 owner-only `POST /foundation-demo/run` 与 `GET /foundation-demo/latest`，完成 Module / Agent / Workflow / Job / Job Events / Artifact / Review / Memory Event / Operation Logs 演习闭环。
- F11：新增受保护的 Foundation Demo 前端页面、运行按钮、latest 状态展示及明确的 demo-only 外部系统隔离提示。
- F11：新增闭环幂等 Registry、新 Job、多步事件、metadata-only Artifact、pending demo Review、无模型 Memory Event、事务回滚与 failure 审计测试。
- F10：新增 owner-only Registry、Job / Job Event、Artifact、Review、System Error、Memory Event、Context Packet 基础 API，以及只读 Memory Summary / Operation Log API。
- F10：所有基础写入与 `operation_logs` 审计在同一事务提交，并新增 demo 状态、敏感字段、外部 URL、重复键和引用完整性校验。
- F10：Modules、Agents、Workflows、Jobs、Artifacts、Reviews、Errors、Memory Events 前端页面接入真实只读列表，提供 loading、error、empty 和简易卡片状态。
- F10：新增 Registry、Jobs、Artifact / Review / Error、Memory / Operation Log 数据库集成测试及无外部 HTTP 客户端边界检查。
- F09：新增 Next.js / React / TypeScript 前端空壳、`/login`、Dashboard、基础导航和结构化空状态页面。
- F09：新增基于 F08 `login`、`me`、`logout` 认证 API 的前端登录状态、401 清理、受保护路由和退出流程。
- F09：新增 frontend Dockerfile、固定依赖 lockfile、前端 route/safety 验证、TypeScript 检查和 production build 脚本。
- F08：新增 Argon2id 密码哈希、JWT token、owner 幂等初始化 CLI 与 example Docker 脚本。
- F08：新增 `POST /auth/login`、`POST /auth/logout`、`GET /auth/me` 和认证 operation logs。
- F08：新增密码安全、owner bootstrap、登录失败统一响应、停用用户、当前用户和退出审计测试。
- F07：新增 14 张核心空地基表的 SQLAlchemy 模型与单一 Alembic migration。
- F07：新增 schema metadata、字段、主键、稳定业务 ID 唯一约束和 migration 无 seed 测试。
- F07：数据库 Docker 验证脚本新增 migration upgrade、downgrade、再次 upgrade 的完整验证。
- F06：新增 PostgreSQL、SQLAlchemy 与 Alembic 迁移机制骨架，metadata 和 migration versions 保持为空。
- F06：新增 example-only PostgreSQL Compose 服务、数据库配置测试和隔离 Docker 验证脚本。
- F05B：新增后端 Docker 隔离测试脚本和可复现的健康检查验证方式。
- F05：新增 FastAPI / Python 后端空骨架、非敏感应用配置和 `GET /health`。
- F05：新增后端 Dockerfile、示例 Compose 配置和健康检查测试。
- F04：新增架构、模块合同、API 边界、数据库 Schema、认证、n8n 集成、固定任务序列和 Codex 施工规则文档。
- 新增 `docs/FOUNDATION_BLUEPRINT_V1_1.md`，同步 Barong Ops Console 空地基 V1.1 基线。
- 将登录认证、`owner` 初始化账号、受保护页面、用户表和密码哈希存储纳入空地基范围。
- 明确 Registry、Job、Artifact、Review、Memory Event、Operation Log、核心表、技术路线、施工顺序和最终验收标准。

### Changed

- C08A：README、backend README 和 frontend README 更新为 C08 已启动且 C08A 为 Module
  Adapter 方案阶段；继续明确本轮没有 API、UI、migration、staging/production 发布、
  Execution Provider、module switch、approval gate、secret rules、formal scope、K01/P 系列
  runtime 或真实业务接入。下一步建议 C08B 后端 Module Adapter contract / static adapter
  registry。
- C07G：README、backend README、frontend README、C07A-F 文档更新为 C07 模块隔离体系已
  封板；后续边界调整为 C08 Module Adapter，不进入 K01/P 系列或真实业务接入。
- C07B：`backend/app/api/routes/modules.py` 在保留现有 F10 `/modules` foundation registry
  list/detail/demo-create API 的基础上，新增 `/modules/registry` 和 `/modules/me` 两个
  静态只读路径，并确保它们位于动态 `/{module_key}` route 之前。
- C07B：README、backend README 和 C07 module isolation plan 更新为 C07B 后端 registry
  基础已实现；继续明确没有新增 frontend UI、没有新增 migration、没有接 K01/P 系列、
  没有接 n8n/WooCommerce/MinIO/Filebrowser 或真实业务，下一步是 C07C 前端
  module-aware navigation / route guard。
- C07A：README、backend README 和 frontend README 更新为 C07 已启动且 C07A 只是模块隔离方案阶段；继续明确 C07 不实现 API/UI/migration，不发布 staging/production，不接真实 n8n/WooCommerce/MinIO/Filebrowser/P 系列/K01 业务开发，下一步建议 C07B 后端 module manifest / registry 基础。
- C06C：README、frontend README、C06 permission management plan 和 C06 backend access 文档更新为 C06C 前端权限管理 UI 已实现；继续明确 `/users` 后端仍 owner-only，User Management 和权限管理入口仍仅 owner full access 可见，`super_admin` 不默认 grant/revoke，`role_default_permissions` 不自动生效，C06C 不新增后端 API/migration、不发布 staging/production、不接真实业务。
- C06B：README、backend README 和 C06 permission management plan 更新为 C06B 后端
  owner-only assignment API 已实现；继续明确本阶段不新增 migration、不做前端权限分配
  UI、不发布 staging/production、不接真实业务，`/users` 仍 owner-only，
  `super_admin` 不默认 grant/revoke，`role_default_permissions` 不自动生效。
- C06A：README、backend README 和 frontend README 更新为 C06 已启动且 C06A 只是
  权限管理方案阶段；继续明确 `/users` 后端 owner-only、User Management 仅 owner full
  access 可见，`super_admin` 不默认全局授权，`role_default_permissions` 不自动生效，
  本轮没有实现 grant/revoke API 或权限分配 UI。
- C05G：README、C05 权限系统计划、C05 staging 验收、C05 production 发布、C05 后端权限文档和
  C05 前端权限文档更新为 C05 已封板；下一步是 C06 或 C18/业务模块接入前置规划，不是 P 系列，
  不接 WooCommerce、n8n 真实业务流、MinIO、Filebrowser 或产品页业务模块。
- C05F：README、C05 权限系统计划、C05 staging 验收、C05 后端权限文档和 C05 前端权限文档
  更新为 production 发布归档已完成；C05G 下一步是 C05 权限系统封板，不进入 P 系列，不接
  WooCommerce、n8n 真实业务流、MinIO、Filebrowser 或产品页业务模块。
- C05E：README、C05 权限系统计划、C05 后端权限文档和 C05 前端权限文档更新为
  staging 验收已完成；C05F 下一步是 production 发布归档，C05G 下一步是 C05 权限系统
  封板。
- C05D：前端导航从静态显示改为权限元数据驱动；`User Management` 入口和页面挡板改为只认
  `permissions.is_owner_full_access=true`，不向 `super_admin` 或普通 `users.manage`
  非 owner 开放，因为后端 `/users` 仍是 `require_owner()`。
- C05D：README、frontend README、C05 权限系统计划和 C05 后端权限文档补充 C05D 承接说明；
  明确 `/users` 改为 `users.manage` 不是 C05D 范围，必须作为 C06 或独立后端任务处理。
- C05C：README、backend README、C05 权限系统计划和 C05 权限数据模型文档更新为后端权限
  dependency/API 合同已接入；`/users` 仍保持 `require_owner()`，前端 UI、权限管理页面、
  grant/revoke API、staging/production 发布和真实业务接入仍不在本轮范围。
- C05B：README、backend README 和 C05 权限系统计划更新为后端权限数据地基已实现；当前仍不暴露
  `/auth/me.permissions`，不增加 permission API，不修改前端权限菜单，不把 `/users` 从
  `require_owner` 切到 `users.manage`，C05C/C05D 继续处理正式 enforcement 和 UI 接入。
- C05A：README、backend README、frontend README 和 C04 角色体系封板文档更新为 C05 权限系统已开始；说明 C05 目标是权限基础设施而不是业务模块接入，当前仍未接真实业务，`super_admin` 仍不是全局 owner，C05B 如实现 User Permission Assignment 和 Permission Registry 应 staging-first 新增 migration。
- OPS01E：README、OPS01 safe release runbook、OPS01 Docker Compose governance plan、OPS01 production acceptance、OPS01 production dry-run 归档和 OPS01 staging acceptance 归档更新为 OPS01 已封板；文档明确当前仍未安装 Compose v2，后续 backend/frontend 发布默认使用 `scripts/safe_compose_release.sh`，不再默认使用 `docker-compose --force-recreate`，下一阶段回到 C05 权限系统。
- OPS01D-3：README、OPS01 safe release runbook、OPS01 Docker Compose governance plan、OPS01 production dry-run 归档和 OPS01 staging acceptance 归档更新为 production safe release 真实演练已完成；文档明确 backend/frontend 都已在 production 演练成功，`ContainerConfig` 问题未复现，当前仍未安装 Compose v2，仍保留 `docker-compose` v1.29.2，但后续 production backend/frontend 发布应优先使用 `scripts/safe_compose_release.sh`，不要把 `docker-compose --force-recreate` 作为默认发布方式；后来 OPS01E 做安全发布流程封板。
- OPS01D-1：`scripts/safe_compose_release.sh` 的 dry-run 输出现在显式打印 `env=...`、`project=...`、`compose=...`、`container=...`、`health=...` 和安全门禁；`scripts/check_safe_release_plan.sh` 增强为检查默认 dry-run、production double confirmation、staging 单确认、env/service allowlist、postgres 拒绝、禁止 `down`、禁止 `docker stop/restart`、所有 Compose v1 命令带 project name。README、OPS01 runbook、OPS01 governance plan 和 OPS01C staging acceptance 当时同步为 OPS01D-1 已完成 production dry-run、production 尚未真实发布、下一步 OPS01D-2 才做 production safe release 真实演练。
- OPS01C：README、OPS01 safe release runbook 和 OPS01 Docker Compose governance plan 更新为 staging safe release 演练已完成；文档明确 OPS01C 只动 staging backend/frontend，staging postgres 和 production 未被发布或重建，rollback tag 只作为后续人工回滚参考，本阶段不执行 rollback，下一步 OPS01D 再治理 production safe release 演练和发布流程。
- OPS01B-alt：OPS01 Docker Compose 治理说明更新为 Compose v2 安装路线暂因 apt 找不到 `docker-compose-plugin` 暂停，当前采用短期 B-alt 路线准备安全发布脚本；Compose v2 后续可以单独评估，但不打断当前项目。README 同步说明新增 safe release runbook 和 dry-run script，当前还没有真实使用脚本发布 staging/production，下一步 OPS01C 是 staging 演练。
- OPS01A：README 更新为 OPS01 已开始，目标是治理 Docker Compose v1 `ContainerConfig` 发布问题；当前只做审计方案，不改运行环境，后续先 OPS01B 处理 Compose v2 或安全 fallback，再 staging-first 演练发布脚本，最后才进入 production。
- C04F：README、backend README、frontend README、C04 角色计划、C04 staging 验收文档和 C04 production 发布文档更新为 C04 已封板；production 已有角色目录 UI，当前仍不做完整 RBAC，不给 `super_admin` 放权，C05 才做 permissions / RBAC；C04 后先做 OPS01：Docker Compose v1 `ContainerConfig` 问题治理。
- C04E：README、backend README、frontend README、C04 角色计划和 C04 staging 验收文档更新为 production 角色目录发布已完成；production `/users` 页面已经使用角色目录 UI，当前仍不做 `super_admin` 放权、不做完整 RBAC，下一步为 C04F 角色体系封板。
- C04D：README、backend README、frontend README 和 C04 角色计划当时更新为 staging 角色目录 UI/API 已验收通过，C04 仍不做完整 RBAC、不创建 production 用户、不接真实业务。
- C04C：创建用户和详情页 managed role 下拉改为由 `/users/roles` 返回的 `assignable=true` 角色生成，并在前端安全过滤为 `viewer` / `operator` / `reviewer`；`owner`、`super_admin`、`module_admin`、`bot_agent` 不可选择。
- C04C：前端 API proxy 最小放行 `GET /api/backend/users/roles`，不破坏 `/health`、`/auth` 和既有 `/users` list/create/detail/update/disable/enable/reset-password 路径。
- C04C：README、frontend README、C03 封板文档和 C04 角色计划更新为前端已使用后端角色目录；本阶段不做完整 RBAC、不部署 staging/production、不创建真实用户、不接真实业务，下一步为 C04D staging 验收角色目录 UI。
- C04B：`backend/app/schemas/user.py` 和 `backend/app/services/user_management_service.py` 改为调用统一 `validate_assignable_user_role`；创建和更新用户 role 仍只允许 `viewer` / `operator` / `reviewer`，继续拒绝 `owner` / `super_admin` / `module_admin` / `bot_agent`。
- C04B：`backend/app/api/deps.py` 的 owner-only 判断改为 `is_owner_role` helper，不改变 `/users` 权限结果；`super_admin`、`module_admin`、`bot_agent` 只定义不放权，完整权限系统仍留给 C05。
- C04B：README、backend README、C03 封板文档和 C04 角色计划更新为 C04B 后端角色常量与统一校验已落地；本阶段不新增 migration、不部署 staging、不发布 production、不接真实业务。
- C04A：README、backend README、frontend README 和 C03 封板文档更新为 C04 已开始，明确 C04 是角色体系、不是完整权限系统；C05 才做 permissions、module access 和角色权限绑定；当前仍不读取真实 env、不创建真实用户、不操作 production/staging 数据库、不改容器、不改 Nginx/证书、不接真实业务。
- C03F：README、backend README、frontend README、C03 计划文档、C03D staging 验收文档和 C03E production 发布文档更新为 C03 已封板、User Management 已进入 production、C03 不包含 `super_admin` 或完整 RBAC，下一阶段为 C04：角色体系。
- C03E：README、backend README、frontend README、C03 计划文档和 C03D staging 验收文档更新为 production 用户管理发布已完成，`/users` 页面已在 production 可用；当前仍不做 `super_admin`、完整 RBAC 或真实业务接入，后续由 C03F 完成封板。
- C03D：README、backend README、frontend README 和 C03 计划文档当时更新为 C03D staging 已验收通过、production 用户管理发布进入 C03E、真实业务仍未接入；本轮未读取真实 env 文件、未打印 secret、未修改 Nginx/证书、未重启或删除容器。
- C03C：`frontend/scripts/verify-foundation.mjs` 纳入 `/users` route、用户管理 API 连接、PATCH proxy 和无公开注册检查；README/frontend README/C03 文档当时更新为 C03C 代码完成状态，后续 C03D 再更新为 staging 已验收。
- C03B：拆分 `get_current_user` 和 `require_owner`；`get_current_user` 只验证 token、用户存在、active 状态和 token role 与数据库 role 一致，`require_owner` 负责 `/users` owner-only 授权。
- C03B：`/auth/login` 和 `/auth/me` 不再要求用户必须是 `owner`；active 非 owner 子账户可以登录并读取当前用户信息，inactive 用户仍被拒绝。公开注册继续不存在。
- C03B：`scripts/test_backend_db_docker.sh` 纳入 `tests/backend/test_user_management_api.py`，确保 example/test 数据库测试覆盖用户管理 API；本阶段不新增 migration、不做前端页面、不做完整 RBAC、不接真实业务。
- C03A：README 补充 C03 owner 创建子账户阶段说明，明确 C03A 只做审计和设计，不新增 migration、不创建用户、不改 production/staging 容器、不接真实业务。
- C02F：README、backend/frontend README、C02A-C02E 文档和双环境运维文档更新为 C02 已封板，production/staging 双环境隔离体系完成，当前仍未接真实业务，下一阶段为 C03：Owner 创建子账户。
- C02E：README、backend/frontend README、`docs/C02_DUAL_ENV_OPERATIONS.md`、`docs/C02_STAGING_SETUP.md` 和 `docs/C02_ENVIRONMENT_ISOLATION_PLAN.md` 更新为 production/staging 双环境最终验收完成、两套环境均可用、当前仍未接真实业务模块、下一步 C02F 环境隔离封板。
- C02D：README、backend/frontend README、`docs/C02_STAGING_SETUP.md` 和 `docs/C02_ENVIRONMENT_ISOLATION_PLAN.md` 更新为 C02C 已完成 staging 本机启动、C02D 只补双环境只读运维检查、staging 仍不暴露公网、下一步 C02E/C02F 做最终验收与封板。
- C02B：README、backend/frontend README、C02A 隔离方案和 F13 验收脚本补充 staging 施工图说明；`.gitignore` 明确忽略真实 `.env.staging`，但保留 `.env.staging.example` 可提交。
- C01C：README、backend/frontend README 和部署检查脚本更新为 C01 production 已上线封板状态，明确当前仍是 foundation/console 阶段，下一阶段为 C02 生产/测试环境分离。
- C01C：`scripts/check_production_deploy_files.sh` 不再创建、覆盖、读取或要求移动真实 `.env.production`；compose 静态验证改用临时目录中的 `.env.production.example`。
- C01B-1：F13 验收脚本允许仓库存在 `docker-compose.production.yml`，继续禁止未审查的额外 Compose 文件。
- C01B-1：README、backend/frontend README 补充 production 部署文件边界，明确真实 `.env.production`、证书、Nginx 安装和业务接入均不在本阶段执行。
- F13：前端 foundation verifier 现在显式检查根路由、受保护 layout 和 auth guard；修正后端 README 中仅适用于 F08 当时状态的“无前端登录页”表述。
- F13：确认不新增 migration、依赖或真实业务接入，不修改生产 Compose，不创建真实产品任务，并保持 F12 网络能力仅限显式配置的 test/demo webhook。
- F12：example 配置新增 `N8N_TEST_WEBHOOK_URL`、`N8N_TEST_CALLBACK_SECRET`、`N8N_TEST_REQUEST_TIMEOUT_SECONDS`；URL 默认空并安全失败，示例值仅使用 `example.invalid`。
- F12：数据库 Docker 测试纳入 n8n test bridge API/回调鉴权/审计/失败测试；前端验证纳入 `/n8n-test` 路由、精确 API 代理及 test bridge only 文案。
- F11：数据库 Docker 测试纳入 Foundation Demo API/事务/失败回滚/敏感信息/无外部客户端测试，前端验证纳入 demo 页面和精确 API 代理检查。
- F11：README 明确演习闭环不接真实 n8n、WooCommerce、MinIO/Filebrowser、P 系列或真实业务任务，且不新增 migration。
- F10：数据库 Docker 验证脚本纳入全部 F10 API 测试；前端 foundation 校验要求八个只读 API 接线并阻止外部集成引用。
- F10：README 明确基础 API 仅登记 foundation/demo 数据，不触发真实工作流、不调用模型、不上传文件、不创建真实产品或业务任务。
- F09：example Compose 新增仅依赖 backend 的 frontend 服务，绑定 `127.0.0.1:3000`，不依赖外部业务服务。
- F09：README 明确第一版没有公开注册，除 `/login` 外页面受保护，前端仍不接真实业务模块或外部系统。
- F08：数据库 Docker 验证覆盖认证测试和 owner CLI，并继续执行 migration upgrade、downgrade、再次 upgrade 和清理。
- F08：README 明确第一版禁止公开注册，前端登录页留到 F09，example secret/password 不得用于生产。
- F07：Alembic metadata 现在加载全部核心空地基模型；`/health` 仍不声称已检查数据库。
- F07：README 明确认证、owner 初始化、业务 API、前端和真实业务仍未实现，认证基础留到 F08。
- F06：示例后端通过 `DATABASE_URL` 指向示例数据库；`/health` 仍不检查数据库连接，核心业务表留到 F07。
- F05B：固定后端 Python 直接和传递依赖版本，并调整示例镜像以非 root 用户运行后端和 `pytest`，不依赖系统 Python 环境。
- F05B：示例 Compose 继续仅包含 backend，明确不使用生产路径、真实密钥、数据库或外部服务。
- F04：将空地基工程约束拆分为可独立审查和后续实现引用的专题合同，并固定 F04 至 F13 任务代号。
- 明确第一版禁止公开注册，除 `/login` 外的控制台页面默认要求登录。
- 明确 n8n 仅作为通过 Adapter / Webhook 接入的执行引擎。
- 明确“先地基后业务、先注册后运行、先测试后生产、先 artifact 后下游、先审核后高风险动作、先日志后成功”的施工原则。
- 补充生产环境保护、真实系统隔离、禁止 silent success 和禁止自动跨越人工审核的约束。
