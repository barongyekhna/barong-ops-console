# C07 Module Isolation Plan

日期：2026-06-11 UTC

本文件记录 C07A：模块隔离审计与方案设计。

C07A 只做只读审计、方案设计、任务拆分和文档归档。本阶段不实现 Module Adapter，
不实现 Execution Provider，不实现模块沙箱，不实现模块开关，不新增 API，不新增 UI，
不新增 migration，不发布 staging 或 production，不接真实业务模块，不进入 K01 或 P
系列。

## 一、C07A 结论

C07 可以开始。

C01-C06 已完成并封板：

- C01 production deployment 已完成并封板。
- C02 environment isolation 已完成并封板。
- C03 owner child account management 已完成并封板。
- C04 role system 已完成并封板。
- C05 permission system 已完成并封板，封板提交为 `6bc8fed docs: seal C05 permission system`。
- C06 permission management 已完成并封板，当前 HEAD 为
  `2b786bc docs: seal C06 permission management`。

C01-C06 已完成控制台部署、环境隔离、账号、角色、权限、权限管理闭环。C05/C06
形成的关键基础是：

- owner 仍是全局全权限。
- `super_admin` 不默认全局，不默认 grant/revoke。
- `role_default_permissions` 不自动生效。
- 非 owner 的实际授权来自 explicit `user_permission_assignments`。
- `/users` 仍是 backend `require_owner()`。
- User Management 和权限管理入口仍只对 owner full access 可见。
- 前端权限只是 UX，真实边界仍是后端 `require_owner()` 和 `require_permission()`。
- business navigation denied 默认 `show_locked`。
- admin/system navigation denied 默认 `hide_when_denied`。
- frontend proxy 仍是精确 allowlist，不是通用 backend proxy。

C07 的目标是模块隔离，不接真实业务。C07A 只做方案，不实现功能。

当前控制台已经存在若干“内置模块/核心板块”形态，但它们还不是正式 Module
Manifest v1。现状审计如下：

| 当前入口或能力 | 当前路径/API | 当前 module_key | 建议 C07 归类 | C07 后建议 key |
| --- | --- | --- | --- | --- |
| Dashboard | `/dashboard` | `dashboard` | core | `core.dashboard` |
| Foundation Demo | `/foundation-demo`, `/foundation-demo/*` | `foundation_demo` | experimental/core demo | `experimental.foundation_demo` |
| n8n Test Bridge | `/n8n-test`, `/n8n-test/*` | `n8n_test` | experimental integration | `integration.n8n_test_bridge` |
| Products empty state | `/products` | `products` | planned business placeholder | `business.products` |
| Modules registry page | `/modules`, `/modules/*` | `modules` | admin/system registry | `admin.modules` |
| Agents registry page | `/agents`, `/agents/*` | `agents` | admin/integration metadata | `admin.agents` |
| Workflows registry page | `/workflows`, `/workflows/*` | `workflows` | admin/integration metadata | `admin.workflows` |
| Jobs | `/jobs`, `/jobs/*` | `jobs` | business foundation | `business.jobs` |
| Artifacts | `/artifacts`, `/artifacts/*` | `artifacts` | business foundation | `business.artifacts` |
| Reviews | `/reviews`, `/reviews/*` | `reviews` | business governance | `business.reviews` |
| Errors | `/errors` | `errors` | system | `system.errors` |
| Memory Events | `/memory-events` | `memory_events` | system | `system.memory_events` |
| User Management | `/users`, `/users/*` | `users` | admin/system management | `admin.users` |
| Permission Management | embedded in `/users` | `permissions` in registry/API | admin/system security management | `admin.permissions` |
| Settings empty state | `/settings` | `settings` | admin/system | `admin.settings` |
| Auth | `/auth/*` | none | core internal | `core.auth` |
| Health | `/health` | none | core internal | `core.health` |
| Operation Logs API | `/operation-logs/*` | `operation_logs` in permission seed | system audit | `system.operation_logs` |

审计结论：

- `frontend/src/lib/navigation.ts` 已经有 `module_key`、`category`、
  `denied_behavior` 和 `required_permission` 字段，但仍是硬编码导航，不是 manifest。
- `frontend/src/lib/permissions.ts` 当前只支持 `business`、`admin`、`system` 三类和
  `show_locked`、`hide_when_denied` 两种 denied 行为。
- `PermissionRouteGuard` 只按精确 pathname 找导航项，不是 route namespace guard。
- `/users` owner-only 同时由导航、页面和后端保护。
- C06B 权限管理 API 全部 owner-only。
- 当前 `/modules` 是 F10 foundation registry，不是 C07 Module Manifest registry。
- 当前许多 foundation/demo 后端路由只要求登录，还没有全部接入
  `require_permission()`。C07A 不改代码，后续 C07B/C07C/C07D 必须把模块 API、
  route 和 permission 绑定纳入验收。
- 当前 navigation 中 `products.read` 没有出现在 C05/C06 registry seed 中。C07 后
  要求导航权限必须来自模块 Permission Manifest 并可注册到 `permission_registry`，
  避免这类漂移。

## 二、为什么需要模块隔离

后续会有 SEO、GEO、K01 产品知识库、产品页自动化、图片资产、文章生成、审核、发布等功能。
这些功能会逐步接触真实业务数据、外部 provider、执行队列、审批、发布和审计。

如果没有模块隔离，以下内容会混乱：

- 导航项会继续散落在 `navigation.ts`。
- 权限 key 可能和 UI 文案、route、API 不一致。
- API 可能继续挂在全局路径，难以审计归属。
- 执行动作可能绕过统一 Execution Provider。
- 外部依赖可能在模块内部直接连接 n8n、WooCommerce、MinIO、Filebrowser 或 AI
  provider。
- denied 行为会在业务模块和系统模块之间混用。
- 未安装、未启用、未接入 provider 的模块可能触发真实动作。
- staging / production 验收缺少统一依据。

C07 用于防止模块越权、乱接、互相污染。C07 是 C08/C09/C10/C13/C15 的前置基础：

- C08 需要 C07 的 manifest 和 registry 规则，才能定义 Module Adapter 如何接入控制台。
- C09 需要 C07 的 external dependency 和 execution requirement，才能定义 Execution
  Provider。
- C10 需要 C07 的 isolation policy 和 data boundary，才能定义模块沙箱。
- C13 需要 C07 的 status、lifecycle 和 feature flag 字段，才能定义模块开关。
- C15 需要 C07 的 integration dependency 声明，才能定义 n8n 接入规范。

## 三、模块定义

模块不是一个按钮，不是一个 helper，也不是一段可复用代码。

模块是有独立页面入口、权限、路由、API namespace、状态、可能外部依赖的功能板块。一个
模块至少要能回答：

- 它叫什么，稳定 `module_key` 是什么。
- 它属于 core、admin、system、business、integration 或 experimental 中哪一类。
- 它是否 planned、adapter_pending、installed、enabled、disabled、unavailable、
  deprecated 或 sealed。
- 它需要哪些 permission keys。
- 它的 route namespace 在哪里。
- 它的 API namespace 在哪里。
- 它的导航如何展示。
- 无权限、未安装、未启用、依赖不可用时如何展示。
- 是否依赖外部 provider。
- 是否需要 Module Adapter、Execution Provider、sandbox、feature flag、staging/
  production 验收。

示例模块：

- `seo`
- `geo`
- `k01.product_knowledge`
- `product_page_automation`
- `image_assets`
- `article_generation`
- `audit_logs`
- `release_management`
- `user_management`
- `permission_management`

C07 后建议使用稳定 namespaced key，而不是 UI 文案或短泛名：

- `business.seo`
- `business.geo`
- `k01.product_knowledge`
- `business.product_page_automation`
- `business.image_assets`
- `business.article_generation`
- `system.audit_logs`
- `system.release_management`
- `admin.users`
- `admin.permissions`

## 四、模块分类

C07 建议 Module Manifest v1 支持以下 `category`：

- `core`：控制台基础能力。包括 auth、dashboard、health、console shell 等。core 不应随便由业务模块覆盖。
- `admin`：管理控制台对象、用户、权限、模块 registry、agent/workflow metadata、settings 等。
- `system`：审计、错误、release、安全、operation logs、内部状态等系统治理能力。
- `business`：面向业务目标的功能模块，例如 SEO、GEO、产品知识库、产品页自动化、图片资产、文章生成、审核、发布。
- `integration`：对外部系统的桥接或 provider 接入封装，例如未来 n8n bridge、WooCommerce bridge、asset storage bridge。
- `experimental`：foundation/demo/test-only 能力或未成熟试验模块，例如现有 Foundation Demo、n8n Test Bridge。
- `planned`：不建议长期作为 category 使用，优先用 `status="planned"`。如确需展示路线图，可用 category `planned` 但不得触发 route/API/action。

User Management 属于 admin/system 管理类模块。C07 建议主 category 为 `admin`，
安全等级按 system/high-risk 处理，未来 key 为 `admin.users`。

Permission Management 属于 admin/system 管理类模块。C07 建议主 category 为
`admin`，风险等级按 system/critical 处理，未来 key 为 `admin.permissions`。

未来 SEO/GEO/K01 属于 business 或 integration，取决于具体依赖：

- 只处理控制台内业务数据和审核流时，属于 `business`。
- 直接依赖外部 provider、workflow 或第三方平台时，业务模块仍可归为 `business`，
  但外部桥接部分必须拆为 `integration` dependency，不允许业务模块直接连接真实服务。

默认 denied 行为：

- `business` 默认 `show_locked`。
- `admin` / `system` 默认 `hide_when_denied`。
- `core` 默认不由普通业务权限覆盖，除非 manifest 明确声明可授权入口。
- `integration` 默认 `hide_when_denied`，若是面向业务用户的可购买能力，可在业务壳层
  `show_locked`，但真实 integration 控制台仍隐藏。
- `experimental` 默认只对 owner 或明确授权用户可见。

## 五、Module Manifest v1 草案

Module Manifest v1 是未来模块进入控制台前必须提交的声明文件或等价结构。C07A 只定义草案，
C07B 才能实现 registry 基础。

建议字段如下：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `module_key` | 是 | 稳定模块 key，一旦发布不得随 UI 文案变化。 |
| `display_name` | 是 | UI 展示名称。 |
| `description` | 是 | 模块用途、边界和非目标。 |
| `category` | 是 | `core`、`admin`、`system`、`business`、`integration`、`experimental`。 |
| `status` | 是 | `planned`、`adapter_pending`、`installed`、`enabled`、`disabled`、`unavailable`、`deprecated`、`sealed`。 |
| `lifecycle` | 是 | `proposal`、`designed`、`adapter_ready`、`staging_pending`、`staging_accepted`、`production_pending`、`production_released`、`sealed`。 |
| `owner_team` 或 `owner_area` | 是 | 负责区域，例如 `console_core`、`ops_admin`、`seo_ops`。 |
| `route_namespace` | 是 | 模块页面 namespace，例如 `/modules/k01.product_knowledge` 或明确 admin/core route。 |
| `api_namespace` | 是 | 模块 API namespace，例如 `/module-api/k01.product_knowledge`。C07 不实现该 API。 |
| `navigation` | 是 | 导航 group、label、icon、order、默认展示策略、是否 owner-only。 |
| `required_permissions` | 是 | 进入模块最小权限，例如 `k01.product_knowledge.access`。 |
| `permission_manifest` | 是 | 模块声明的全部 permission keys、action、risk、menu policy、scope 支持。 |
| `denied_behavior` | 是 | `show_locked` 或 `hide_when_denied`，可按 category 默认。 |
| `unavailable_behavior` | 是 | 未安装、未启用、provider 未接入、adapter 缺失时的展示方式。 |
| `external_dependencies` | 是 | n8n、WooCommerce、MinIO、Filebrowser、AI provider 等依赖声明。可为空数组。 |
| `execution_provider_required` | 是 | 是否需要 C09 Execution Provider。C07 只声明，不连接。 |
| `module_adapter_required` | 是 | 是否需要 C08 Module Adapter。 |
| `sandbox_required` | 是 | 是否需要 C10 模块沙箱。 |
| `feature_flag_key` | 否 | 未来 C13 模块开关或 feature flag key。 |
| `audit_log_actions` | 是 | 该模块会产生的 operation log action 名称清单。 |
| `operation_log_policy` | 是 | 哪些 read/write/approve/release 行为必须写审计。 |
| `allowed_scope_types` | 是 | 支持 `global`、`module`、`company`、`factory`、`department`、`organization` 中哪些 scope。 |
| `isolation_policy` | 是 | 模块的路由、API、数据、执行、外部依赖和跨模块访问隔离规则。 |
| `data_boundary` | 是 | 数据读写边界、不得读取的对象、不得跨模块写入的对象。 |
| `release_requirements` | 是 | 本地、staging、production 验收前置要求。 |
| `staging_acceptance_required` | 是 | 是否必须 C07E 或后续 staging acceptance。业务模块应为 true。 |
| `production_release_required` | 是 | 是否必须 production release archive。业务模块应为 true。 |
| `docs_path` | 是 | 模块设计、验收、封板文档路径。 |

建议草案示例：

```yaml
module_key: k01.product_knowledge
display_name: Product Knowledge
description: Product knowledge module shell; no real business execution in C07.
category: business
status: adapter_pending
lifecycle: designed
owner_area: knowledge_ops
route_namespace: /modules/k01.product_knowledge
api_namespace: /module-api/k01.product_knowledge
navigation:
  group: Business
  label: Product Knowledge
  icon: Database
  order: 100
  default_visible: false
required_permissions:
  - k01.product_knowledge.access
permission_manifest:
  - permission_key: k01.product_knowledge.access
    action: access
    risk_level: low
    menu_policy: show_locked
denied_behavior: show_locked
unavailable_behavior: adapter_pending
external_dependencies: []
execution_provider_required: true
module_adapter_required: true
sandbox_required: true
feature_flag_key: modules.k01.product_knowledge
audit_log_actions:
  - k01.product_knowledge.view
operation_log_policy:
  read: optional
  write: required
  approve: required
allowed_scope_types:
  - global
  - module
isolation_policy:
  route: module_namespace_only
  api: module_namespace_only
  data: no_cross_module_write
  execution: provider_required
data_boundary:
  reads: []
  writes: []
release_requirements:
  local_verify: true
  staging_acceptance: true
  production_archive: true
staging_acceptance_required: true
production_release_required: true
docs_path: docs/K01_PRODUCT_KNOWLEDGE_MODULE.md
```

上面只是 future example。C07A 不创建 K01 文档，不进入 K01 开发。

## 六、module_key 命名规则

`module_key` 必须稳定、可审计、可用于 route/API/permission 关联。

规则：

- 使用小写 `snake_case` 或 dot namespace。
- `core`、`admin`、`system` 可用明确前缀。
- K01 推荐使用 `k01.product_knowledge` 或 `k_series.product_knowledge`。
- 禁止随意使用泛名，例如 `product`、`task`、`automation`、`content`、`data`。
- 禁止用 UI 文案、临时项目名、客户名、环境名作为 key。
- 禁止同一业务能力同时出现多个 key。
- `module_key` 一旦发布后应稳定，不随 UI 文案变化。
- module key 改名必须走 migration/compatibility 方案，不能直接替换。

future examples：

- `core.dashboard`
- `admin.users`
- `admin.permissions`
- `business.seo`
- `business.geo`
- `k01.product_knowledge`
- `integration.n8n_bridge`

当前短 key 到未来 key 的建议映射：

- `dashboard` -> `core.dashboard`
- `users` -> `admin.users`
- `permissions` -> `admin.permissions`
- `modules` -> `admin.modules`
- `jobs` -> `business.jobs`
- `reviews` -> `business.reviews`
- `artifacts` -> `business.artifacts`
- `operation_logs` -> `system.operation_logs`
- `settings` -> `admin.settings`

## 七、权限声明规则

每个模块必须声明 Permission Manifest。

权限声明规则：

- 每个模块必须声明自己的 permission keys。
- 权限 key 必须可注册到 `permission_registry`。
- 权限不能只靠 role。
- 权限不能只靠前端隐藏按钮。
- 权限不能只靠 local cache 或 token 内静态声明。
- owner full access 仍全局可见。
- `super_admin` 不默认全局。
- `role_default_permissions` 不自动生效。
- 模块权限必须能被 C06 或后续授权流程授予、更新、撤销和审计。
- high-risk 权限必须标记。
- admin/system/release/secrets/provider/production 类权限默认 high 或 critical。
- 模块 navigation 使用的 `required_permission` 必须出现在该模块 Permission Manifest
  或明确引用系统模块 permission。

模块权限命名建议：

- `{module_key}.access`
- `{module_key}.read`
- `{module_key}.create`
- `{module_key}.update`
- `{module_key}.delete`
- `{module_key}.approve`
- `{module_key}.settings.manage`

示例：

- `business.seo.access`
- `business.seo.read`
- `business.seo.create`
- `business.seo.approve`
- `k01.product_knowledge.access`
- `k01.product_knowledge.read`
- `k01.product_knowledge.update`
- `admin.permissions.read`
- `admin.permissions.manage`

Permission Manifest 建议包含：

- `permission_key`
- `module_key`
- `category`
- `action`
- `label`
- `description`
- `risk_level`
- `menu_policy`
- `default_scope_type`
- `allowed_scope_types`
- `high_risk_confirmation_required`
- `operation_log_required`

User Management 和 Permission Management 的规则：

- User Management 继续 owner-only，直到独立阶段正式调整 `/users` 后端授权边界。
- Permission Management 继续 owner-only，C06B assignment API 不因
  `permissions.manage` 对非 owner 开放。
- 如果未来要开放 delegated permission admin，必须先完成 C18 scope 和单独授权策略。

## 八、导航隔离规则

导航不能随便硬编码业务模块。

C07 后导航项应来自 module metadata，或至少映射到 module metadata。当前
`frontend/src/lib/navigation.ts` 的硬编码字段可作为过渡材料，但 C07C 应改为
module-aware navigation，不应让新业务模块直接手写散落导航。

导航声明必须包含：

- `module_key`
- `label`
- `group`
- `icon`
- `order`
- `route_namespace`
- `category`
- `required_permission`
- `denied_behavior`
- `unavailable_behavior`
- `default_visible`
- `owner_only`
- `status`

规则：

- business 模块无权限默认 `show_locked`。
- admin/system 模块无权限默认 `hide_when_denied`。
- 未注册模块不能进入导航。
- 未安装模块可对 owner/admin 显示 `planned` 或 `unavailable` 状态，但不能触发真实动作。
- 未启用模块不能出现在普通用户导航。
- `disabled` 模块不能出现在普通用户导航。
- `adapter_pending` 模块默认 hidden navigation，除非 owner/admin 查看 module registry。
- `execution_not_connected` 模块可以显示 unavailable/readiness 状态，但按钮必须 disabled。
- User Management / Permission Management 继续 owner-only 可见。
- core 模块不允许被业务模块用同名 key 覆盖。

business module 为什么应 `show_locked`：

- 业务模块通常代表用户可申请或未来可开通的工作能力。
- locked 可让普通用户知道有该业务板块，但不能读取数据或执行动作。
- locked 可减少“页面消失就是 bug”的误解。
- locked 有利于后续申请权限、订阅、培训和 onboarding。
- locked 只能展示安全描述，不得泄漏敏感数据、配置、真实任务、外部 provider 状态或客户信息。

admin/system module 为什么应 `hide_when_denied`：

- 管理和系统入口本身可能暴露安全边界、内部结构、审计能力、发布能力或用户治理能力。
- 对无权限用户隐藏可以降低误触、钓鱼、社工和越权探索面。
- admin/system 的存在感不应作为普通用户体验的一部分。
- 直接访问 admin/system route 时仍必须由 route guard 和后端返回 No Permission/403。

未安装、未启用、未接入 execution provider 的模块展示规则：

- `planned`：普通用户默认隐藏；owner/admin 可在 module registry 看到 planned。
- `adapter_pending`：普通用户默认隐藏；owner/admin 可看到“Adapter pending”，不能进入真实工作台。
- `installed` 但未 `enabled`：普通用户隐藏；owner/admin 可看到 installed disabled。
- `disabled`：普通用户隐藏；直接访问显示 Module Unavailable。
- `unavailable`：若 business 且已授权，可显示 unavailable notice；admin/system 默认隐藏。
- `execution_provider_required=true` 且 provider 未接入：显示
  `execution_not_connected`，所有 create/run/publish 按钮禁用。

## 九、路由隔离规则

每个模块必须有 `route_namespace`。

规则：

- 模块页面不得乱挂在全局根路径，除非是 core/admin 明确路径。
- 未来业务模块建议使用 `/modules/{module_key}` 或统一命名空间。
- dot namespace 可直接 URL encode，或由 manifest 显式声明 route slug。
- admin/system 允许保留明确路径，例如 `/users`、`/settings`，但必须映射到
  module metadata。
- route guard 应按 route namespace 判断，而不是只按精确 pathname 判断。
- 直接访问未授权模块时显示 No Permission 或 Module Unavailable。
- 直接访问未启用模块时不得触发真实操作。
- route loader 不得在权限确认前执行真实写入、外部调用或 provider 初始化。
- core route 不得被业务 module route 覆盖。

建议：

- `core.dashboard` -> `/dashboard`
- `admin.users` -> `/users`
- `admin.permissions` -> `/users` 内 permission panel，或未来 `/permissions`
- `business.seo` -> `/modules/business.seo`
- `k01.product_knowledge` -> `/modules/k01.product_knowledge`
- `integration.n8n_bridge` -> `/modules/integration.n8n_bridge`

C07 不实现真实业务路由，只制定规则。

## 十、API namespace 隔离规则

每个模块必须有 `api_namespace`。

规则：

- 未来业务模块 API 不应散落在全局 route。
- 模块 API 必须经过权限依赖。
- 模块 API 必须绑定 manifest 中的 `module_key` 和 Permission Manifest。
- 模块 API 不得直接调用外部服务，除非后续 C09/C15 明确接入。
- 模块 API 不得在 provider 未连接时创建真实任务。
- frontend proxy allowlist 不得为了模块放开任意通配。
- frontend proxy 只能精确放行已注册、已启用、已验收的 module API 路径。
- API namespace 不能和 core/admin/system 现有路径冲突。

建议 future namespace：

- backend module API：`/module-api/{module_key}/...`
- frontend proxy：`/api/backend/module-api/{module_key}/...`
- module registry/admin API：单独由 C07B 设计，不复用业务 module API。

现状边界：

- 当前 `/modules` 是 foundation registry route，不是 C07 module manifest API。
- 当前 `/permissions/*` 是 C05/C06 权限管理 API，不是业务模块 API。
- 当前 `/n8n-test/*` 是 test bridge，不是 C15 真实 n8n 接入。

C07 不实现模块 API，只定义规则。

## 十一、外部依赖隔离规则

模块如依赖 n8n、WooCommerce、MinIO、Filebrowser、AI provider，必须在 manifest
声明。

`external_dependencies` 建议字段：

- `dependency_key`
- `dependency_type`
- `required`
- `provider_key`
- `provider_status`
- `readiness_status`
- `allowed_actions`
- `disallowed_actions`
- `secret_ref_required`
- `docs_path`

规则：

- C07 只声明 `external_dependencies`，不连接。
- C09 才定义 Execution Provider。
- C14 才定义密钥规则。
- C15 才定义 n8n 接入规范。
- 未接入 provider 的模块必须显示 `unavailable`、`adapter_pending` 或
  `execution_not_connected`。
- manifest 不应保存真实 secret、token、password、Authorization header。
- manifest 不应保存真实生产 webhook URL，除非后续密钥/配置规则明确允许，并且不得打印。
- 外部依赖状态不能由普通前端任意伪造。
- provider 缺失时，后端不得发起外部 HTTP、不得创建真实任务、不得写真实业务状态。

模块是否允许直接接 n8n/WooCommerce/MinIO/Filebrowser？答案必须是：C07 不允许。

模块是否允许直接创建真实业务任务？答案必须是：C07 不允许。

C07 不允许直接接真实服务。

## 十二、模块状态 / lifecycle

C07 建议区分 `status` 和 `lifecycle`：

- `status` 决定当前运行展示和 API 行为。
- `lifecycle` 决定设计、验收、发布和封板进度。

### status

| status | 前端行为 | 后端行为 |
| --- | --- | --- |
| `planned` | 普通用户隐藏；owner/admin 可在 module registry 看到 planned。 | 不注册业务 API，不执行动作。 |
| `adapter_pending` | 默认隐藏；owner/admin 可看到 adapter pending；业务入口不得可用。 | 不接 adapter，不执行动作，可返回 module metadata。 |
| `installed` | owner/admin 可见 installed；普通用户按 enabled 前隐藏。 | manifest 可注册，API 默认不可写。 |
| `enabled` | 按 category、permission、denied_behavior 展示。 | API 必须经过权限依赖，允许已验收动作。 |
| `disabled` | 普通用户隐藏；直接访问显示 Module Unavailable。 | API 返回 disabled/unavailable，不执行动作。 |
| `unavailable` | 已授权用户可看到 unavailable notice；按钮 disabled。 | 不调用 provider，不创建任务，可返回 readiness。 |
| `deprecated` | 仅 owner/admin 或已有授权用户看到迁移提示。 | 禁止新任务，只允许必要只读或迁移 API。 |
| `sealed` | core/admin/system 稳定能力可见；不得被业务模块覆盖。 | 行为稳定，变更必须走独立阶段和封板记录。 |

### lifecycle

建议 lifecycle：

- `proposal`：仅有想法，不可注册运行。
- `designed`：已有设计文档，不可执行真实业务。
- `adapter_ready`：C08 adapter 已完成。
- `execution_ready`：C09 provider 已完成。
- `sandbox_ready`：C10 sandbox 已完成。
- `staging_pending`：准备 staging 验收。
- `staging_accepted`：staging 验收通过。
- `production_pending`：准备 production 发布。
- `production_released`：production 发布归档完成。
- `sealed`：阶段最终封板。

status 和 lifecycle 的组合示例：

- K01 在 C07 完成前：`status=adapter_pending`，`lifecycle=designed`，
  `navigation.default_visible=false`。
- 已安装但 feature flag 关闭的业务模块：`status=disabled`，
  `lifecycle=adapter_ready`。
- provider 缺失的业务模块：`status=unavailable`，
  `unavailable_behavior=execution_not_connected`。
- C05/C06 已封板管理能力：`status=sealed`，`lifecycle=sealed`。

## 十三、K01 与 C07 的关系

K01 是未来业务模块，不是 C07。

规则：

- K01 可在独立 worktree 做 scope-adapter-pending 规划。
- C07 不开发 K01。
- C07 不创建或修改 K01 文档。
- C07 为 K01 未来接入定义规则。
- K01 在 C07 未完成前应保持 `adapter_pending`、disabled-by-default、hidden
  navigation。
- K01 不占 C 系列编号。
- K01 不应直接接 n8n、WooCommerce、MinIO、Filebrowser、AI provider 或真实业务任务。
- K01 的建议 module key 是 `k01.product_knowledge` 或
  `k_series.product_knowledge`。
- K01 未来接入时必须提供 Module Manifest v1、Permission Manifest、route
  namespace、API namespace、external dependencies、denied behavior、readiness
  和 staging/production 验收规则。

未来 K01 如何作为 adapter_pending 模块接入 C07 规则：

- 先提交 manifest，`status=adapter_pending`。
- `module_adapter_required=true`。
- `execution_provider_required=true`，但 provider 未接入前保持
  `execution_not_connected`。
- `sandbox_required=true`。
- `navigation.default_visible=false`，普通用户不可见。
- owner/admin 可在 module registry 中看到 K01 readiness。
- 所有真实读写、任务创建、外部连接都必须等 C08/C09/C10/C13/C15 对应阶段完成。

## 十四、C07 与后续阶段边界

C07 与 C08 Module Adapter：

- C07 定义模块必须声明什么，以及 route/API/navigation/permission/status 如何隔离。
- C08 定义模块如何真正接入控制台、如何加载 adapter、adapter interface 是什么。
- C07 不实现 Module Adapter。

C07 与 C09 Execution Provider：

- C07 定义模块是否需要 `execution_provider_required` 和 external dependency。
- C09 定义模块如何执行任务、如何调用 provider、如何记录执行状态。
- C07 不实现 Execution Provider。

C07 与 C10 模块沙箱：

- C07 定义 `sandbox_required`、`isolation_policy` 和 `data_boundary`。
- C10 定义模块运行隔离、资源边界、跨模块访问控制和沙箱 enforcement。
- C07 不实现模块沙箱。

C07 与 C11 模块验收标准：

- C07 定义 staging / production 验收字段和基础策略。
- C11 定义完整模块上线验收标准、模板和自动化 gate。
- C07 不做完整 C11 实现。

C07 与 C12 审批门：

- C07 可声明 high-risk permissions 和 `audit_log_actions`。
- C12 定义模块动作审批、审批流、审批状态和审批 API/UI。
- C07 不实现审批门。

C07 与 C13 模块开关：

- C07 定义 `status`、`feature_flag_key` 和 disabled/unavailable 展示。
- C13 定义启停模块、feature flag、模块开关 API/UI 和运行时 enforcement。
- C07 不做完整模块开关实现。

C07 与 C14 密钥规则：

- C07 声明 external dependency 是否需要 secret。
- C14 定义 provider secrets 的存储、读取、轮换、审计和禁止打印规则。
- C07 不实现密钥规则。

C07 与 C15 n8n 接入规范：

- C07 声明某模块依赖 n8n 或 integration bridge。
- C15 才定义真实 n8n 接入规范、webhook、callback、安全、验收和禁止项。
- C07 不接 n8n。

C07 与 C18 组织结构 / scope：

- C07 使用现有 `global`、`module`、`company`、`factory`、`department`、
  `organization` scope 字段声明模块支持范围。
- C18 才定义完整 company/factory/department organization model、scope admin 和组织权限。
- C07 不实现完整 organization scope。

## 十五、C07 建议拆分

### C07A：模块隔离审计与方案设计

目标：

- 审计 C05/C06 权限基础、当前导航、route、backend router、proxy 和测试。
- 产出 `docs/C07_MODULE_ISOLATION_PLAN.md`。
- 更新 README / CHANGELOG / 前后端 README 引用。

允许：

- 只读审计。
- 写文档。
- 跑现有 verify/build/test/smoke/status。

禁止：

- 不新增 API/UI/migration。
- 不改 backend/frontend runtime 代码。
- 不接真实业务。
- 不发布 staging/production。
- 不 git commit。

验收产物：

- C07A 方案文档。
- README/CHANGELOG 引用。
- 检查命令记录。

### C07B：后端模块 manifest / registry 基础

目标：

- 定义后端 Module Manifest v1 schema。
- 建立模块 registry 基础或 manifest source。
- 校验 `module_key`、category、status、permission manifest、route/API namespace。

允许：

- 新增后端 manifest/registry 基础代码。
- 如确需持久化，单独评估 migration。
- 增加后端测试。

禁止：

- 不接真实业务。
- 不实现 Module Adapter。
- 不实现 Execution Provider。
- 不接 n8n/WooCommerce/MinIO/Filebrowser。
- 不发布 production。

验收产物：

- 后端 manifest/registry 规则。
- permission registry 映射校验。
- 不放宽现有 `/users` 和 C06B owner-only 边界。

### C07C：前端 module-aware navigation / route guard

目标：

- 将导航与 module metadata 绑定。
- 支持 category/status/denied/unavailable 行为。
- route guard 支持 namespace。

允许：

- 修改前端 navigation、permissions helper、route guard。
- 增加前端测试。

禁止：

- 不新增真实业务 UI。
- 不接真实 provider。
- 不放开 proxy 通配。

验收产物：

- business denied `show_locked`。
- admin/system denied `hide_when_denied`。
- User Management / Permission Management 仍 owner-only。
- 未注册/未启用模块不可触发动作。

### C07D：模块隔离 verify/test 体系

目标：

- 增加自动检查，确保模块必须有 manifest，navigation 绑定 module key，permissions 可追踪，
  proxy 不放宽。

允许：

- 增加 frontend/backend 测试和 verify 脚本。

禁止：

- 不接真实业务。
- 不发布。

验收产物：

- 模块 manifest 校验测试。
- navigation/module mapping 测试。
- route/API/proxy 隔离测试。
- C05/C06 回归测试。

### C07E：staging 模块隔离验收

目标：

- 将 C07B-D 发布到 staging 并做只读/安全验收。

允许：

- 按 OPS01 safe release 发布 staging backend/frontend。
- 在 staging 验证 module-aware navigation、route guard、proxy allowlist。

禁止：

- 不发布 production。
- 不接真实业务。
- 不操作 production 数据库或容器。
- 不读取真实 env。

验收产物：

- staging acceptance 文档。
- staging smoke/status 记录。
- C05/C06 权限管理回归通过。

### C07F：production 模块隔离发布归档

目标：

- 将已验收的模块隔离基础发布到 production 并归档。

允许：

- 按 OPS01 safe release 发布 production backend/frontend。
- 做 owner 只读验收。

禁止：

- 不创建 production 测试账号。
- 不执行真实业务任务。
- 不操作 production postgres。
- 不读取真实 env。
- 不接真实 n8n/WooCommerce/MinIO/Filebrowser。

验收产物：

- production release 文档。
- owner 只读验收。
- smoke/status 记录。

### C07G：C07 模块隔离封板

目标：

- 归档 C07A-F 完成范围、最终规则、验收证据和后续边界。

允许：

- 文档封板。

禁止：

- 不新增功能。
- 不发布。
- 不接真实业务。

验收产物：

- C07 final seal 文档。
- 下一阶段进入 C08，而不是 K01/P 系列真实业务开发。

## 十六、测试与验收策略

未来 C07D/C07E/C07F 必须验证：

- 模块必须有 manifest。
- navigation item 必须绑定 `module_key`。
- navigation item 的 `required_permission` 必须来自 Permission Manifest 或明确的系统权限。
- business/admin/system denied_behavior 正确。
- business denied 显示 locked。
- admin/system denied 隐藏入口。
- 未注册模块不能进导航。
- 未启用模块不能触发真实动作。
- `planned`、`adapter_pending`、`unavailable`、`execution_not_connected` 状态不能触发
  create/run/publish。
- route namespace 不能被未注册模块占用。
- direct route access 必须走 No Permission 或 Module Unavailable。
- api namespace 必须经过后端权限依赖。
- frontend proxy allowlist 不放宽，不允许任意通配。
- permission keys 可追踪到 manifest 和 `permission_registry`。
- high-risk 权限必须标记。
- operation log action 必须在 manifest 中声明。
- C05/C06 功能不被破坏。
- `/users` 仍 owner-only。
- Permission Management 仍 owner-only。
- owner full access 仍全局可见。
- `super_admin` 不默认全局。
- `role_default_permissions` 不自动生效。
- 未读取或打印 secret/token/password/Authorization header。
- 未接真实 n8n/WooCommerce/MinIO/Filebrowser。

建议测试拆分：

- 后端 unit：manifest schema、module key、status、permission manifest、namespace
  校验。
- 后端 API：module registry 只读、权限绑定、disabled/unavailable 行为。
- 前端 unit：module-aware navigation、denied/unavailable、owner-only、route namespace。
- proxy test：只允许明确 module API path，不允许 wildcard。
- regression：继续运行 C05/C06 frontend tests 和 C06B backend tests。
- staging：owner 和 non-owner 验证，但 production 不创建测试账号。
- production：owner 只读验收，不执行写入型真实业务动作。

## 十七、风险和暂缓项

明确暂缓：

- 不接真实业务。
- 不接 n8n。
- 不接 WooCommerce。
- 不接 MinIO/Filebrowser。
- 不实现完整 Module Adapter。
- 不实现 Execution Provider。
- 不实现 module switch。
- 不实现 organization scope。
- 不实现审批门。
- 不实现密钥规则。
- K01 只能 `adapter_pending`。

风险：

- 当前导航已有 `module_key`，但不是 namespaced key，未来迁移要保持兼容。
- 当前 route guard 只支持精确 pathname，后续 namespace route 需要补。
- 当前 `/modules` 是 foundation registry，容易和 C07 Module Manifest registry 混淆。
- 当前部分 foundation/demo 后端路由只要求登录，后续模块 API 必须统一接入权限依赖。
- 当前 `products.read` 在 navigation 中存在，但未出现在 C05/C06 registry seed，说明
  navigation permission 和 registry 可能漂移。C07 必须用 manifest 校验防止继续扩大。
- 如果 C07B 过早实现 adapter/provider，会越界进入 C08/C09。
- 如果 C07C 为了模块 API 放开 frontend proxy 通配，会破坏 C05/C06 的安全边界。
- 如果 business locked 页面展示太多 readiness/provider 信息，可能泄漏内部系统状态。

C07A 最终结论：

- C07 可以开始。
- C07A 只完成模块隔离方案。
- 没有实现 API。
- 没有实现 UI。
- 没有新增 migration。
- 没有发布 staging。
- 没有发布 production。
- 没有读取真实 env。
- 没有接真实业务。
- 完成 C07A 后应等待审核，下一步建议 C07B：后端模块 manifest / registry 基础。
