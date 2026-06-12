# C08 Module Adapter Plan

日期：2026-06-12 UTC

本文件记录 C08A：Module Adapter 审计与方案设计。

C08A 是只读审计和文档设计任务，不是功能实现任务。本轮不修改 backend runtime
代码，不修改 frontend runtime 代码，不新增 API，不新增 UI，不新增 migration，不发布
staging 或 production，不执行 safe release，不接真实业务，不进入 K01，不进入 P 系列。

2026-06-12 C08B 补充：后端 Module Adapter contract / static adapter registry 已完成，
归档在 `docs/C08_MODULE_ADAPTER_BACKEND.md`。C08B 新增 `ModuleAdapterContractV1`
schema、代码内静态 adapter registry、集中 validation/access-state service，以及
authenticated read-only `GET /module-adapters/registry` 和 `GET /module-adapters/me`。
C08B 只返回安全 adapter metadata，不执行 action，不连接 live provider，不新增 migration，
不新增前端 UI，不接 K01/P 系列或真实业务。

2026-06-12 C08C 补充：前端 adapter rendering shell / adapter surface placeholders
已完成，归档在 `docs/C08_MODULE_ADAPTER_FRONTEND.md`。C08C 新增前端
Module Adapter 类型/helper/API client、`AdapterAccessProvider` 和通用
`AdapterSurfaceShell`，通过现有 frontend backend proxy 读取
`GET /module-adapters/registry` 与 `GET /module-adapters/me`，只展示 adapter
status、supported surfaces、bindings、capabilities、action/data contracts 和安全
dependency names。所有 action 仍不可执行，execution action 显示等待 C09，approval
action 显示等待 C12；C08C 不新增后端 API，不新增 migration，不接 K01/P 系列或 live
provider。

## 一、C08A 结论

C08 可以开始。

C07 模块隔离体系已完成并封板，当前 HEAD 为
`462a720 docs: seal C07 module isolation`，提交链包含：

- `f5925ed docs: add C07A module isolation plan`
- `32f1454 feat: add C07B module registry backend`
- `f59ae65 feat: add C07C module-aware frontend isolation`
- `f8c8c88 test: add C07D module isolation verification`
- `0ae9c43 docs: add C07E module staging acceptance`
- `ace9112 docs: add C07F module production release`
- `462a720 docs: seal C07 module isolation`

C07 已经完成：

- 后端静态 Module Manifest v1 registry。
- authenticated `GET /modules/registry`。
- authenticated `GET /modules/me`。
- module access state 计算。
- 前端 module-aware navigation。
- 前端 route namespace guard。
- Module Unavailable / No Permission 提示。
- frontend proxy 对 `/modules/registry` 和 `/modules/me` 的精确 allowlist。
- C07D verify/test 体系。
- staging 验收。
- production 发布归档。
- C07G 最终封板。

C08 的目标是 Module Adapter 标准。C08 解决“模块如何正规接入控制台”的问题，不解决“模块如何执行任务”的问题。

C08A 只做方案，不实现功能。C08A 不接真实业务。

本轮不接 K01，不接 P 系列，不接 WooCommerce，不接 n8n 真实业务流，不接 MinIO，不接
Filebrowser，不创建真实任务，不实现 Execution Provider，不实现模块沙箱，不实现模块开关，
不实现审批门，不实现密钥规则，不实现正式 scope。

## 二、为什么需要 Module Adapter

C07 解决模块身份、边界、导航、路由、API namespace 和权限隔离。

C07 已经定义了模块至少应声明：

- `module_key`
- `display_name`
- `category`
- `status`
- `lifecycle`
- `route_namespace`
- `api_namespace`
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
- `docs_path`

但 C07 没有定义模块如何正式向控制台交付页面、动作、状态、能力、输入输出和健康信息。

C07 的 registry 能回答“模块是谁、状态是什么、路由边界在哪里、需要什么权限、当前用户能不能看到”。它不能回答：

- 模块给控制台提供哪些页面 surface。
- 模块如何声明 page、detail page、action panel、settings panel。
- 模块如何声明用户可触发动作。
- 模块如何声明 action 输入输出。
- 模块如何声明状态 provider 和健康 provider。
- 模块如何声明 capability 到 permission 的绑定。
- 模块如何声明 operation log action。
- 模块如何声明外部依赖需求但不连接 live provider。
- 模块如何为 C09 Execution Provider 预留执行接口。
- 模块如何为 C13 Module Switch 预留启停接口。
- 模块如何为 C18 正式组织 scope 预留接口。

C08 用于建立模块接入控制台的标准 adapter contract。

没有 adapter，未来 K01、SEO、GEO、P 系列等模块会各自乱接页面、动作、状态、日志、外部依赖：

- 页面可能直接硬编码进 `navigation.ts`。
- 动作可能绕过统一 permission/action contract。
- 状态可能混同执行结果。
- 外部依赖可能直接保存 URL、token 或 provider 配置。
- operation logs action 名称可能不可追踪。
- K01/P 系列可能在 C09/C15 前误接 live runtime。
- 模块可能绕过 C07 route namespace 或 C05/C06 permission system。

C08 是 C09 Execution Provider、C13 Module Switch、C15 n8n 接入规范的前置标准之一。

## 三、Module Manifest 与 Module Adapter 的区别

Module Manifest 是模块身份证和边界声明。

Module Adapter 是模块接入控制台的标准接口。

Manifest 说明“模块是谁、在哪里、需要什么权限、状态是什么”。

Adapter 说明“模块怎么把页面、动作、状态、能力、数据契约交给控制台”。

区别如下：

| 项目 | Module Manifest | Module Adapter |
| --- | --- | --- |
| 主要问题 | 模块是谁 | 模块如何接入控制台 |
| 所属阶段 | C07 已完成基础 | C08 设计 contract |
| 关注对象 | 身份、边界、状态、权限声明 | 页面、路由绑定、导航绑定、动作、状态、健康、数据契约 |
| 控制重点 | 不越界、不乱挂、不泄露依赖 | 不乱接、不乱执行、不绕过统一入口 |
| 当前实现 | C07B 后端静态 registry + C07C 前端消费 | C08A 只设计，C08B 以后才实现 |
| 与执行关系 | 声明是否需要 execution provider | 声明 action contract，但不执行 |
| 与开关关系 | 声明 status / feature flag key | 声明 feature_flag_bindings 和 disabled fallback |

C07 已完成 Manifest / Registry 基础。C08 设计 Adapter Contract。

Manifest 和 Adapter 必须一一对齐：每个正式 adapter 必须绑定一个已有 `module_key`，不得创建未注册模块，不得用 adapter 绕过 C07 registry。

## 四、Module Adapter v1 草案

Module Adapter v1 是声明式 contract。C08A 只定义字段，不实现 loader、registry、渲染或执行。

建议字段如下：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `adapter_key` | 是 | 稳定 adapter key，建议 `{module_key}.adapter` 或 `{module_key}.console_adapter`。 |
| `adapter_version` | 是 | adapter contract version，例如 `1.0.0`。必须可验证、可升级。 |
| `module_key` | 是 | 必须绑定 C07 registry 中已存在的 `module_key`。 |
| `manifest_version` | 是 | 对齐的 Module Manifest version，例如 `v1`。 |
| `display_name` | 是 | adapter 展示名，应与 manifest display name 可追踪。 |
| `adapter_status` | 是 | `draft`、`adapter_pending`、`contract_ready`、`test_ready`、`staging_ready`、`production_ready`、`disabled`、`deprecated`、`sealed`。 |
| `supported_surfaces` | 是 | adapter 支持的控制台 surface 清单。 |
| `pages` | 是 | 模块 page 声明，不等于直接创建 UI。 |
| `nav_bindings` | 是 | 导航绑定声明，必须绑定 C07 `module_key`。 |
| `route_bindings` | 是 | route namespace 内的 route 声明。 |
| `api_bindings` | 是 | future module API 声明。C08A 不新增 API。 |
| `capabilities` | 是 | 模块能力清单，例如 `read_profile`、`create_product`。 |
| `actions` | 是 | 用户可触发动作清单。C08 只声明，不执行。 |
| `action_contracts` | 是 | 每个 action 的输入、输出、权限、风险和执行要求。 |
| `status_provider` | 是 | 模块 status provider contract，不连接 live provider。 |
| `health_provider` | 是 | 模块 health provider contract，不读取 secret。 |
| `data_contracts` | 是 | 模块数据对象、版本、读写边界声明。 |
| `input_contracts` | 是 | action / page / import 的输入 schema 声明。 |
| `output_contracts` | 是 | action / page / export 的输出 schema 声明。 |
| `permission_bindings` | 是 | adapter 使用的 permission keys，必须来自 registry 或待注册清单。 |
| `scope_bindings` | 是 | scope 绑定声明；C18 前只能 `adapter_pending`。 |
| `operation_log_bindings` | 是 | action 到 operation log action 的绑定。 |
| `audit_events` | 是 | future audit event 清单，C17 前只声明。 |
| `feature_flag_bindings` | 是 | future C13 module switch / feature flag 绑定。 |
| `dependency_declarations` | 是 | 外部依赖需求，只能声明安全依赖名。 |
| `execution_requirements` | 是 | future C09 execution provider 需求，只声明。 |
| `sandbox_requirements` | 是 | future C10 sandbox 需求，只声明。 |
| `approval_requirements` | 是 | future C12 approval gate 需求，只声明。 |
| `secret_requirements` | 是 | future C14 secret/provider credential 需求，只声明需求类型，不声明 secret。 |
| `fallback_behavior` | 是 | adapter 缺失、provider 缺失、scope 未完成时的安全降级。 |
| `unavailable_behavior` | 是 | 模块不可用、disabled、adapter_pending、execution_not_connected 的展示策略。 |
| `test_contracts` | 是 | C08D 需要验证的 contract 测试声明。 |
| `docs_path` | 是 | adapter 设计、验收、封板文档路径。 |

草案示例：

```yaml
adapter_key: k01.product_knowledge.console_adapter
adapter_version: 1.0.0
module_key: k01.product_knowledge
manifest_version: v1
display_name: Product Knowledge Console Adapter
adapter_status: adapter_pending
supported_surfaces:
  - navigation
  - module_page
  - detail_page
  - action_panel
  - status_widget
pages:
  - page_key: k01.product_knowledge.index
    surface: module_page
    route: /modules/k01.product_knowledge
    required_permission: k01.product_knowledge.access
nav_bindings:
  - nav_key: k01.product_knowledge.main
    module_key: k01.product_knowledge
    route: /modules/k01.product_knowledge
    denied_behavior: show_locked
route_bindings:
  - route_key: k01.product_knowledge.index
    path: /modules/k01.product_knowledge
    route_namespace: /modules/k01.product_knowledge
api_bindings: []
capabilities:
  - capability_key: read_profile
    required_permission: k01.product_knowledge.read
actions:
  - action_key: k01.product_knowledge.keyword_research.run
    capability_key: run_keyword_research
    required_permission: k01.product_knowledge.keyword_research.run
    risk_level: medium
    requires_approval: false
    requires_execution_provider: true
    operation_log_action: k01.product_knowledge.keyword_research.run
action_contracts:
  - action_key: k01.product_knowledge.keyword_research.run
    input_contract: k01.product_knowledge.keyword_research.input.v1
    output_contract: k01.product_knowledge.keyword_research.output.v1
    executable_before_c09: false
status_provider:
  provider_key: k01.product_knowledge.status
  status_contract: status.v1
  live_provider_connected: false
health_provider:
  provider_key: k01.product_knowledge.health
  health_contract: health.v1
  secret_read_allowed: false
data_contracts:
  - contract_key: k01.product_knowledge.profile.v1
input_contracts:
  - contract_key: k01.product_knowledge.keyword_research.input.v1
output_contracts:
  - contract_key: k01.product_knowledge.keyword_research.output.v1
permission_bindings:
  - k01.product_knowledge.access
  - k01.product_knowledge.read
scope_bindings:
  status: adapter_pending
operation_log_bindings:
  - action_key: k01.product_knowledge.keyword_research.run
    operation_log_action: k01.product_knowledge.keyword_research.run
audit_events: []
feature_flag_bindings:
  - modules.k01.product_knowledge
dependency_declarations:
  - dependency_key: ai_provider
execution_requirements:
  requires_execution_provider: true
  executable_before_c09: false
sandbox_requirements:
  sandbox_required: true
approval_requirements:
  high_risk_action_policy: future_c12
secret_requirements:
  - requirement_key: ai_provider_credential
    secret_value_declared: false
fallback_behavior:
  adapter_missing: module_unavailable
  provider_missing: provider_not_connected
  execution_missing: execution_not_connected
unavailable_behavior: adapter_pending
test_contracts:
  - c08.adapter.contract
docs_path: docs/C08_MODULE_ADAPTER_PLAN.md
```

上面只是文档示例。C08A 不开发 K01，不注册 K01 runtime，不修改 K01 worktree。

## 五、Adapter Status / Lifecycle

Adapter status 用于描述 adapter contract 的接入成熟度，不等同于 C07 module status，也不等同于执行状态。

| adapter_status | 允许 | 禁止 |
| --- | --- | --- |
| `draft` | 文档草稿、字段讨论、离线示例。 | 不得进入 runtime registry，不得显示给普通用户，不得执行 action。 |
| `adapter_pending` | 已知道模块需要 adapter，可在 owner/admin registry 中显示 pending 状态。 | 不得进入真实工作台，不得触发 live action，不得连接 provider。 |
| `contract_ready` | 字段完整，可进入 C08B 静态 registry 或 contract fixture。 | 不得执行 action，不得默认启用普通用户导航。 |
| `test_ready` | 可进入 C08D contract tests，允许 mock-only status/health validation。 | 不得连接 live provider，不得写真实业务数据。 |
| `staging_ready` | 通过本地 contract tests，可准备 C08E staging 验收。 | 不得跳过 staging 验收，不得发布 production。 |
| `production_ready` | 通过 staging 验收和发布前检查，可准备 C08F 归档。 | 不得表示 sealed，不得绕过 C13/C09/C14 后续 gate。 |
| `disabled` | owner/admin 可看到 disabled 原因；普通用户隐藏或 unavailable。 | 不得渲染可执行 action，不得初始化 provider。 |
| `deprecated` | 可显示迁移/替代说明，可保留只读兼容 contract。 | 不得创建新 action，不得新增 provider dependency。 |
| `sealed` | contract 稳定，变更必须走后续阶段和封板记录。 | 不得在无新任务编号的情况下修改 contract 语义。 |

`adapter_pending` 模块表现：

- 普通用户默认不进入真实工作台。
- owner/admin 可在 module registry 或 future adapter registry 中看到 pending。
- route guard 应显示 Module Unavailable 或 equivalent safe notice。
- sidebar 可显示安全 badge，但不得触发真实动作。
- actions 全部 `executable=false`。
- status 可显示 `adapter_pending`、`provider_not_connected`、`execution_not_connected`。
- 不连接 live provider。

disabled-by-default 模块表现：

- manifest / adapter 可存在，但 feature flag 或 C13 switch 未开启。
- 普通用户默认 hidden 或 unavailable。
- owner/admin 可看到 disabled reason。
- direct route 只能显示 Module Unavailable。
- action panel 中所有动作禁用或不渲染。
- provider、execution、sandbox 都不得初始化。
- C13 完成前只能在文档和 future binding 中声明，不能实现启停 runtime。

## 六、Supported Surfaces

Module Adapter v1 应定义控制台 surface，C08A 只定义，不实现 UI。

建议 surface：

- `navigation`：侧边栏或导航入口绑定。
- `dashboard_card`：Dashboard 摘要卡片。
- `module_page`：模块首页或工作台。
- `detail_page`：模块对象详情页。
- `action_panel`：动作触发面板。
- `settings_panel`：模块设置面板。
- `audit_log_view`：模块审计/operation log 视图。
- `status_widget`：模块 status / readiness widget。
- `future_approval_panel`：未来 C12 approval panel 预留。

规则：

- surface 只是 adapter 声明，不代表 C08A 新增 UI。
- surface 必须绑定 `module_key`。
- surface 必须绑定 permission。
- surface 必须声明不可用行为。
- action surface 在 C09 前只能展示 disabled/pending 状态。

## 七、Pages / Routes / Navigation Adapter

Adapter 可以声明模块页面，但不得绕过 C07 route namespace。

规则：

- `pages` 声明模块提供哪些控制台页面。
- `route_bindings` 必须落在 C07 `route_namespace` 内。
- `nav_bindings` 必须绑定 C07 `module_key`。
- adapter 不允许直接把页面挂到全局任意路径。
- adapter 不允许覆盖 core route。
- adapter 不允许新增未注册 route namespace。
- adapter 不允许绕过 business `show_locked`。
- adapter 不允许绕过 admin/system `hide_when_denied`。
- adapter 不允许绕过 `PermissionRouteGuard` 或 future module route guard。
- 未启用、`adapter_pending` 或 disabled-by-default 模块不得触发真实动作。

`pages` 建议字段：

- `page_key`
- `module_key`
- `surface`
- `route`
- `route_namespace`
- `required_permission`
- `status`
- `unavailable_behavior`
- `component_ref` 或 future rendering token
- `data_contract_refs`
- `action_refs`

`nav_bindings` 建议字段：

- `nav_key`
- `module_key`
- `label`
- `group`
- `icon`
- `order`
- `route`
- `required_permission`
- `denied_behavior`
- `unavailable_behavior`
- `default_visible`
- `owner_only`

`route_bindings` 建议字段：

- `route_key`
- `module_key`
- `path`
- `route_namespace`
- `surface`
- `required_permission`
- `guard_policy`
- `status`

C08A 不新增 UI，不修改 `frontend/src/lib/navigation.ts`，不新增 route。

## 八、Capabilities / Actions Adapter

Capability 是模块支持的能力，例如：

- `read_profile`
- `create_product`
- `run_keyword_research`
- `generate_article_outline`
- `sync_asset_metadata`
- `review_item`
- `publish_item`

Action 是用户可触发的动作，例如：

- `k01.product_knowledge.keyword_research.run`
- `business.seo.keyword_cluster.create`
- `business.product_page_automation.page.generate`
- `business.reviews.item.approve`

C08 只声明 action contract。C08 不执行 action。

C09 才把 action 交给 Execution Provider。

每个 action 必须声明：

- `action_key`
- `module_key`
- `capability_key`
- `display_name`
- `description`
- `required_permission`
- `risk_level`
- `requires_approval`
- `requires_execution_provider`
- `execution_requirement_ref`
- `input_contract`
- `output_contract`
- `operation_log_action`
- `audit_event_refs`
- `idempotency_policy`
- `timeout_policy`
- `fallback_behavior`
- `executable_before_c09=false`

高风险 action 必须为 C12 approval gate 预留字段：

- `requires_approval=true`
- `approval_policy_ref`
- `approval_reason_required`
- `approval_risk_note`
- `approval_expiry_policy`
- `approval_operation_log_action`

风险等级建议：

- `low`：只读、安全 metadata。
- `medium`：生成草稿、创建内部待审核对象。
- `high`：发布、批量写入、权限影响、外部系统写入。
- `critical`：生产发布、密钥、权限管理、跨系统批量变更。

C08A 不实现 action panel，不新增执行 API，不创建真实任务。

## 九、Status / Health Adapter

模块必须能向控制台提供 status / health contract。

Status 不等于执行结果。Status 表示模块接入和 readiness 状态，例如：

- `adapter_pending`
- `contract_ready`
- `provider_not_connected`
- `execution_not_connected`
- `scope_pending`
- `disabled`
- `available`
- `degraded`

Health 不得读取 secret，不得输出 token，不得输出 provider URL，不得连接 live provider。

`status_provider` 建议字段：

- `provider_key`
- `module_key`
- `status_contract`
- `allowed_statuses`
- `source`
- `live_provider_connected=false`
- `last_checked_at_policy`
- `safe_message_policy`
- `secret_read_allowed=false`

`health_provider` 建议字段：

- `provider_key`
- `module_key`
- `health_contract`
- `checks`
- `mock_only`
- `live_check_allowed=false`
- `secret_read_allowed=false`
- `safe_failure_behavior`

`adapter_pending`、`provider_not_connected`、`execution_not_connected` 应可显示。

C08A 只定义 contract，不实现 live check。

## 十、Data Contract Adapter

模块必须声明输入输出数据结构。

数据契约用于保证模块页面、动作、状态和后续 execution provider 有可测试、可版本化的接口。

`data_contracts` 建议字段：

- `contract_key`
- `contract_version`
- `module_key`
- `object_type`
- `schema_ref`
- `read_boundary`
- `write_boundary`
- `owner_module`
- `version_policy`
- `test_fixture_path`
- `breaking_change_policy`

`input_contracts` 建议字段：

- `contract_key`
- `action_key`
- `schema`
- `required_fields`
- `optional_fields`
- `validation_rules`
- `sensitive_fields`
- `redaction_policy`

`output_contracts` 建议字段：

- `contract_key`
- `action_key`
- `schema`
- `safe_summary_fields`
- `sensitive_fields`
- `redaction_policy`
- `operation_log_projection`

K01 示例可以是 product profile input/output，但只作为文档示例，不接 K01：

- input：product handle、language、market、keyword seed。
- output：product profile summary、keyword candidates、source notes、readiness status。

P 系列未来要声明 workflow input/output，但不在 C08 接入：

- input：workflow run request、source object id、approved payload。
- output：run id、status、safe summary、operation log ref。

数据契约必须可测试、可版本化。

不允许模块自由写任意全局状态。不允许跨模块写入，除非 future C10/C18 明确允许并有 contract。

## 十一、Permission / Scope Adapter

adapter 必须绑定 C05/C06 permission keys。

规则：

- `permission_bindings` 必须来自 `permission_registry` 或待注册清单。
- 每个 page、nav、action、status detail、settings surface 都必须声明 required permission 或 owner-only policy。
- owner full access 全局通过。
- `super_admin` 不默认全局。
- `role_default_permissions` 不自动生效。
- `permissions.manage` 不自动开放 C06B owner-only assignment API。
- 前端 permission 判断仍只是 UX。
- 后端 `require_permission()` / `require_owner()` 仍是真实安全边界。

`permission_bindings` 建议字段：

- `permission_key`
- `module_key`
- `used_by`
- `surface`
- `action_key`
- `risk_level`
- `required`
- `registry_status`
- `pending_registration_reason`

Scope 规则：

- C18 未完成前，`scope_bindings` 只能声明 `adapter_pending`。
- 允许记录 future intent，例如 `global`、`module`、`company`、`factory`、`department`、`organization`。
- 不允许模块自己发明正式 company/factory/department scope。
- 不允许 adapter 自己解释 company/factory/department 归属。
- 不允许用 scope 文案替代 C05/C06 effective permission 结果。

`scope_bindings` 建议字段：

- `status: adapter_pending`
- `declared_scope_types`
- `requires_c18_scope_adapter`
- `default_scope_policy`
- `scope_validation_ref`
- `fallback_before_c18`

## 十二、Operation Logs / Audit Adapter

adapter actions 必须声明 `operation_log_action`。

后续动作执行、审批、失败、回滚都应写 `operation_logs`。

C08 只定义 bindings。

C17 才做审计日志页面。

不允许模块绕过 `operation_logs`。

`operation_log_bindings` 建议字段：

- `action_key`
- `operation_log_action`
- `target_type`
- `target_id_policy`
- `details_projection`
- `redaction_policy`
- `result_values`
- `failure_values`
- `rollback_action`

`audit_events` 建议字段：

- `event_key`
- `module_key`
- `source_action`
- `severity`
- `operation_log_action`
- `retention_policy`
- `view_surface`

示例：

- `permission.assignment.grant`
- `k01.product_knowledge.keyword_research.run`
- `business.seo.keyword_cluster.create`
- `business.reviews.item.approve`

C08A 不新增 operation log API，不新增 audit log UI。

## 十三、External Dependency Adapter

adapter 可以声明 `dependency_declarations`。

允许声明依赖名：

- `n8n`
- `woocommerce`
- `minio`
- `filebrowser`
- `ai_provider`
- `serp`
- `wecom`
- `google_sheets`

规则：

- 只允许声明依赖名、类型、是否必需、future provider capability。
- 不允许声明 secret。
- 不允许声明 token。
- 不允许声明 URL。
- 不允许声明 credential。
- 不允许声明 Authorization header。
- 不允许声明真实 webhook。
- 不允许读取 `.env.production`。
- 不允许读取 `.env.staging`。
- C14 才做密钥规则。
- C15 才做 n8n 接入规范。
- C08 不连接 live provider。

`dependency_declarations` 建议字段：

- `dependency_key`
- `dependency_type`
- `required`
- `provider_status`
- `provider_contract_ref`
- `secret_requirement_ref`
- `live_connection_allowed=false`
- `safe_unavailable_message`

当前 C07 runtime 只允许安全依赖名子集。C08A 文档可以规划扩展依赖名，但 C08A 不修改 C07 runtime allowlist。

## 十四、K01 与 C08 的关系

K01 是未来业务模块，不是 C08。

规则：

- K01 可以在独立 worktree 做 `adapter_pending` 规划。
- K01 未来正式接入必须提供 Module Adapter。
- K01 adapter 必须声明 product knowledge pages、capabilities、actions、permissions、scope_bindings、provider dependencies。
- K01 adapter 必须绑定 C07 `module_key`，例如未来 `k01.product_knowledge`。
- K01 adapter 必须绑定 C05/C06 permission keys。
- K01 adapter 必须声明 C18 前 scope 为 `adapter_pending`。
- K01 adapter 必须声明 provider dependencies，但不能连接 live provider。
- K01 action 必须保持 `requires_execution_provider=true`，C09 前不可执行。
- K01 不占 C 系列编号。

C08A 不开发 K01。

C08A 不修改 K01 worktree。

C08A 不读取或修改 `/opt/barong-ops-console-worktrees/k-series-product-knowledge`。

## 十五、P 系列与 C08 的关系

P 系列是 n8n workflow，不是 C08。

P 系列未来进入控制台时，应作为模块 action/execution capability 接入。

可能路径：

- 作为某个业务模块的 action，例如 `business.product_page_automation.page.publish`。
- 作为 execution capability，由 C09 Execution Provider 接管执行。
- 作为 n8n provider dependency，由 C15 n8n 接入规范定义连接方式。

C08 只定义 adapter contract。

C09/C15 才处理执行和 n8n。

C08A 不读取或修改 P-series workflow JSON。

C08A 不接 P 系列 runtime。

C08A 不创建 P 系列任务，不连接 P01/P02/P03/P04/P05/P06/P07/P08。

## 十六、C08 与后续阶段边界

C08 与后续阶段边界：

- C09 Execution Provider：执行 action，不在 C08A 做。
- C10 模块沙箱：运行隔离，不在 C08A 做。
- C11 模块验收标准：正式验收标准，不在 C08A 完整实现。
- C12 审批门：审批动作，不在 C08A 做。
- C13 模块开关：启停模块，不在 C08A 做。
- C14 密钥规则：secrets/provider credentials，不在 C08A 做。
- C15 n8n 接入规范：不在 C08A 做。
- C17 审计日志页面：不在 C08A 做。
- C18 组织结构：正式 scope，不在 C08A 做。

C08 为这些阶段预留字段：

- C09：`actions`、`action_contracts`、`execution_requirements`。
- C10：`sandbox_requirements`、`data_contracts`、`data_boundary`。
- C12：`approval_requirements`、high-risk action fields。
- C13：`feature_flag_bindings`、`disabled` lifecycle behavior。
- C14：`secret_requirements`。
- C15：`dependency_declarations`。
- C17：`operation_log_bindings`、`audit_events`。
- C18：`scope_bindings`。

预留字段不是实现许可。C08A 只写 contract。

## 十七、C08 建议拆分

### C08A：Module Adapter 审计与方案设计

目标：

- 只读审计 C07 module registry、frontend module-aware navigation、route guard 和 verify/test 体系。
- 设计 Module Adapter contract v1。
- 产出 `docs/C08_MODULE_ADAPTER_PLAN.md`。
- 更新 README / CHANGELOG / 前后端 README 引用。

允许：

- 只读审计。
- 写文档。
- 跑现有 verify/build/test/smoke/status。

禁止：

- 不新增 API/UI/migration。
- 不改 backend/frontend runtime 代码。
- 不接真实业务。
- 不进入 K01/P 系列。
- 不发布 staging/production。
- 不 git commit。

验收产物：

- C08A 方案文档。
- README/CHANGELOG 引用。
- 检查命令记录。

### C08B：后端 Module Adapter contract / static adapter registry

目标：

- 新增后端 adapter contract schema。
- 新增静态 adapter registry 或 fixture。
- 校验 adapter 绑定 existing `module_key`。
- 不执行 action。

状态：已完成。实现记录见 `docs/C08_MODULE_ADAPTER_BACKEND.md`。

已实现：

- `backend/app/schemas/module_adapter.py`
- `backend/app/core/module_adapters.py`
- `backend/app/services/module_adapter_registry.py`
- `backend/app/api/routes/module_adapters.py`
- `GET /module-adapters/registry`
- `GET /module-adapters/me`
- `tests/backend/test_module_adapters_registry.py`

允许：

- 新增后端 contract/schema/validation 代码。
- 新增后端 contract tests。
- 只读 adapter registry API 是否需要应单独评估；如新增 API 必须明确 C08B 范围。

禁止：

- 不实现 Execution Provider。
- 不接 live provider。
- 不新增真实业务 API。
- 不新增 migration，除非老板另行批准并 staging-first。
- 不接 K01/P 系列 runtime。

验收产物：

- 后端 adapter contract。
- static adapter registry。
- adapter validation tests。
- C05/C06/C07 回归。

### C08C：前端 adapter rendering shell / adapter surface placeholders

目标：

- 前端识别 adapter surfaces。
- 建立安全 placeholder 渲染壳。
- 显示 adapter_pending / unavailable / disabled 状态。
- 不渲染真实业务 UI。

状态：已完成。实现记录见 `docs/C08_MODULE_ADAPTER_FRONTEND.md`。

已实现：

- `frontend/src/lib/module-adapter.ts`
- `frontend/src/lib/module-adapter-api.ts`
- `frontend/src/components/adapter-access-provider.tsx`
- `frontend/src/components/module-adapter-shell.tsx`
- console layout 挂载 `AdapterAccessProvider`
- console shell 展示 `AdapterSurfaceShell`
- frontend proxy 精确 allowlist `GET /module-adapters/registry` 和
  `GET /module-adapters/me`
- `tests/frontend/module-adapter.test.mjs`

允许：

- 修改前端 adapter helper、placeholder shell、tests。
- 显示安全状态和 contract metadata。

禁止：

- 不新增 K01/P 系列真实页面。
- 不接 live actions。
- 不放宽 proxy。
- 不绕过 C07 route guard。

验收产物：

- adapter surface placeholder。
- no-action 状态。
- frontend tests。
- C08C 前端归档文档。

### C08D：Adapter contract verify/test 体系

目标：

- 固化 adapter contract 校验。
- 验证 adapter 与 C07/C05/C06 对齐。
- 阻止 secret/live provider/action execute。

允许：

- 新增后端 tests。
- 新增前端 Node tests。
- 增强 verify script。

禁止：

- 不新增 runtime feature。
- 不发布。
- 不连接 provider。

验收产物：

- adapter_key 唯一测试。
- route/nav/permission/action/dependency contract tests。
- C05/C06/C07 回归。

### C08E：staging Module Adapter 验收

目标：

- 将 C08B/C08C/C08D 的 adapter contract runtime 发布到 staging。
- 做只读 staging 验收。

允许：

- 按 OPS01 safe release 发布 staging backend/frontend。
- 验证 adapter registry、placeholder、proxy、tests。

禁止：

- 不发布 production。
- 不接真实业务。
- 不读 env。
- 不操作 postgres。
- 不创建真实任务。

验收产物：

- staging acceptance 文档。
- smoke/status 记录。
- adapter contract staging evidence。

### C08F：production Module Adapter 发布归档

目标：

- 将已验收的 C08 adapter contract runtime 安全发布到 production。
- 归档 production evidence。

允许：

- 按 OPS01 safe release 发布 production backend/frontend。
- 做只读 production 验收。

禁止：

- 不创建 production 测试账号。
- 不执行真实 action。
- 不操作 production postgres。
- 不读 env。
- 不接 provider。

验收产物：

- production release 文档。
- smoke/status 记录。
- no-action / no-provider evidence。

### C08G：C08 Module Adapter 封板

目标：

- 归档 C08A-F 完成范围、最终 contract、验收证据和后续边界。

允许：

- 文档封板。

禁止：

- 不新增功能。
- 不发布。
- 不接真实业务。

验收产物：

- C08 final seal 文档。
- 下一阶段进入 C09 Execution Provider，而不是 K01/P 系列 runtime。

## 十八、测试与验收策略

未来 C08D/C08E/C08F 必须验证：

- 每个 adapter 必须绑定 existing `module_key`。
- `adapter_key` 唯一。
- `adapter_version` 合法。
- `adapter_status` 合法。
- `manifest_version` 合法。
- `module_key` 必须存在于 C07 registry。
- pages 不越过 module route namespace。
- `route_bindings` 不覆盖 core route。
- `nav_bindings` 不绕过 C07 navigation rules。
- `nav_bindings` 必须绑定 `module_key`。
- business adapter 不得绕过 `show_locked`。
- admin/system adapter 不得绕过 `hide_when_denied`。
- actions 必须声明 permission/risk/operation_log。
- actions 必须声明 input/output contract。
- high-risk actions 必须声明 future C12 approval fields。
- execution actions 只能声明，不能执行，直到 C09。
- `requires_execution_provider=true` 的 action 在 C09 前必须 `executable=false`。
- dependency declarations 不包含 secret/token/env/url/credential/Authorization header。
- dependency declarations 只能使用安全依赖名。
- `status_provider` 和 `health_provider` 不读取 secret。
- `adapter_pending` 模块不可 executable。
- disabled-by-default 模块不可 executable。
- K01/P 系列不能默认启用。
- P 系列 workflow JSON 不被读取或修改。
- K01 worktree 不被修改。
- C05 owner full access 仍全局通过。
- `super_admin` 不默认全局。
- `role_default_permissions` 不自动生效。
- `/users` 仍 owner-only。
- C06B assignment API 仍 owner-only。
- C07 `/modules/registry` 和 `/modules/me` 不被破坏。
- frontend proxy 不放开 `/modules/*`、`/module-api/*` 或 provider 通配。
- C05/C06/C07 不被破坏。

C08A 本轮建议运行：

- `git status --short --untracked-files=all`
- `git diff --check`
- frontend `npm run verify`
- frontend `npm run typecheck`
- frontend `npm run build`
- frontend Node tests
- backend C07/C05/C06 Docker tests，如环境允许
- production/staging smoke/status 只读脚本

任何因环境原因不可运行的检查必须如实记录，不伪造通过。

## 十九、风险与暂缓项

C08A 明确暂缓：

- 不接真实业务。
- 不接 K01。
- 不接 P 系列。
- 不接 n8n。
- 不接 WooCommerce。
- 不接 MinIO/Filebrowser。
- 不执行 actions。
- 不实现 Execution Provider。
- 不实现 module switch。
- 不实现 module sandbox。
- 不实现 approval gate。
- 不实现 formal scope。
- 不实现 secret/provider credential rules。
- 不新增 API。
- 不新增 UI。
- 不新增 migration。
- 不读取 env。
- 不创建真实任务。
- 不修改 K01 worktree。
- 不读取或修改 P-series workflow JSON。
- 不发布 staging。
- 不发布 production。

主要风险：

- Adapter contract 过早执行化，会抢 C09。
- Adapter contract 过早开关化，会抢 C13。
- Adapter contract 过早 scope 化，会抢 C18。
- Adapter dependency 字段若允许 URL/secret，会抢 C14/C15 并造成泄密风险。
- K01/P 系列如果在 adapter contract 未封板前接 runtime，会绕过 C07/C08/C09/C13/C15。

控制策略：

- C08A 只做文档。
- C08B 只做 static adapter registry / contract validation。
- C08C 只做 placeholder shell。
- C08D 固化 no-execute/no-provider/no-secret tests。
- C08E/C08F 只做 contract runtime 验收，不接业务。
- C08G 封板后再进入 C09 Execution Provider。
