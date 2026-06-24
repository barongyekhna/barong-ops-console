# C-SERIES V1 Full System Documentation

本文件是基于当前仓库真实源代码导出的 C-SERIES V1 完整技术文档。它面向技术交接、生产运维排查、未来 K 系列接入和审计复盘使用。

导出范围：

- 后端：`backend/app/**`、`backend/Dockerfile`、数据库模型与 Alembic 运行安全代码。
- 前端：`frontend/src/**`、`frontend/Dockerfile`、Next.js API proxy、SaaS UI shell。
- 测试与部署：`tests/**`、`scripts/**`、`docker-compose.*.yml`、`deploy/nginx/**`、环境变量示例文件。

说明：

- 本文档只描述代码中存在的系统，不虚构未实现模块。
- 敏感环境文件未作为文档来源；部署配置以 `.env.production.example`、`.env.staging.example` 和 compose/nginx 模板为准。
- 当前系统保留部分历史表与测试兼容逻辑，但部分运行路由已经在 `backend/app/main.py` 中显式移除。

## 1. 系统架构总览

### 1.1 总体拓扑

C-SERIES V1 是一个面向运营控制台的 SaaS 系统，由四层组成：

| 层级 | 技术 | 关键代码 | 责任 |
| --- | --- | --- | --- |
| 前端控制台 | Next.js 16、React 19、TypeScript | `frontend/src/app`、`frontend/src/components`、`frontend/src/lib` | 登录态、控制台 Shell、模块中心、权限 UI、API proxy |
| 后端 API | FastAPI、SQLAlchemy | `backend/app/main.py`、`backend/app/api/routes` | 业务 API、控制平面、权限、模块、执行 gate、n8n/webhook 集成 |
| 数据库 | PostgreSQL、Alembic | `backend/app/models`、`backend/app/db`、`backend/alembic` | 用户、组织、权限、模块、执行、审计、回调和运行状态 |
| 部署运行 | Docker Compose、Gunicorn/Uvicorn、Nginx 模板 | `docker-compose.production.yml`、`backend/Dockerfile`、`frontend/Dockerfile`、`deploy/nginx` | 生产/预发服务编排、2 worker 后端、前端 standalone 服务、反向代理 |

生产后端镜像通过 Gunicorn 启动 FastAPI：

```text
gunicorn backend.app.main:app
  --bind 0.0.0.0:8000
  --workers ${GUNICORN_WORKERS:-2}
  --worker-class uvicorn.workers.UvicornWorker
```

生产 compose 明确设置 `GUNICORN_WORKERS=2`，因此当前架构是双进程 worker 模型，每个 worker 维护自己的数据库连接池、内存缓存和后台轻量线程。

### 1.2 API 分层

后端入口为 `backend/app/main.py`。系统将 API 分为三组：

| 前缀 | 语义 | 典型路由 |
| --- | --- | --- |
| `/api/public` | 公开能力 | health、security headers、auth login/logout/me |
| `/api/app` | 控制台业务应用 API | users、organizations、permissions、approval、reviews、messages、module visibility |
| `/api/control-plane` | 控制平面 API | modules、module-control、api-key-orchestration、execution providers、workflow registry、webhook gateway、live gate |

前端不会直接暴露任意后端地址，而是通过 Next.js API proxy：

- proxy 入口：`frontend/src/app/api/backend/[...path]/route.ts`
- 前端请求基准：`/api/backend`
- 后端内部地址：由 `BACKEND_API_URL` 提供，例如生产 compose 中的 `http://console_backend:8000`

proxy 对路径做白名单和阻断：

- 阻断 `webhook`、`n8n` 一类直接路径。
- 阻断 `/webhook-gateway/ingress` 直接从前端进入。
- 阻断 URL-like path segment，例如 `http:`、`https:`、`n8n-webhook-ref:`。
- 阻断指向 n8n/webhook 的后端 API base URL。

### 1.3 生产安全行为

生产或 production-like 环境由 `backend/app/core/config.py` 和 `backend/app/main.py` 控制：

- `APP_ENV=production` 时默认关闭 FastAPI docs。
- 只有设置 `APP_DOCS_ENABLED=true` 才打开 OpenAPI 文档。
- control-plane stealth mode 会把部分未授权/不存在的控制平面访问伪装成 404。
- 全局异常处理会输出经过清洗的错误响应，避免泄露内部细节。
- `backend/app/db/migration_safety.py` 在 production-like 启动时检查 Alembic head/current revision，避免错误版本运行。

### 1.4 中间件和请求生命周期

核心请求链由以下组件共同组成：

| 组件 | 关键代码 | 责任 |
| --- | --- | --- |
| 会话认证 | `backend/app/api/deps.py`、`backend/app/services/session_service.py` | 校验 cookie/session token，加载当前用户和 session |
| 权限中间件 | `backend/app/middleware/permission.py` | 根据 path/query/header 推导 module/action/org 上下文并调用统一权限引擎 |
| 数据隔离中间件 | `backend/app/middleware/data_isolation.py` | 为 `/api/app` 请求解析 org context，阻止跨组织读写 |
| 数据隔离 SQLAlchemy hook | `backend/app/services/data_isolation.py` | 对 org-scoped 模型加 `with_loader_criteria`，保护 insert/update/delete |
| API request guard | `backend/app/core/api_request_guard.py` | 控制高频和重复请求 |
| 热路径缓存 | `backend/app/main.py` | 对部分 GET 热路径做 5 秒进程内响应缓存 |

`backend/app/main.py` 的热路径包括：

- `/api/app/organizations`
- `/api/app/permissions/me`
- `/api/control-plane/module-control/center`
- `/api/control-plane/modules/registry`

### 1.5 已移除运行路由

代码中仍有部分历史表和测试兼容对象，但以下运行路由在 `backend/app/main.py` 中已经被显式短路为 404：

- `/api/app/artifacts`
- `/api/app/jobs`
- `/api/control-plane/workflows`

这些不能作为当前 C-SERIES V1 的对外业务 API 继续依赖。

## 2. 模块系统设计（module-control）

### 2.1 模块系统组成

模块系统由静态 manifest、动态 registry、组织绑定、模块控制状态和前端能力图共同组成：

| 子系统 | 关键代码 | 说明 |
| --- | --- | --- |
| 静态 manifest | `backend/app/core/modules.py` | 内置模块定义、分类、路由、状态、RBAC action |
| 动态 registry | `backend/app/models/module_registry.py`、`backend/app/services/module_registry.py` | 数据库存储的动态模块、agent、workflow registry |
| 组织模块绑定 | `backend/app/models/module_binding.py` | 组织是否拥有某模块 |
| 模块控制中心 | `backend/app/api/routes/module_control.py`、`backend/app/services/module_control_center.py` | owner 控制组织内模块 enabled/runtime_status |
| 模块控制缓存 | `backend/app/services/module_control_cache_service.py` | 5 秒 TTL 的模块中心快照 |
| 前端模块中心 | `frontend/src/components/module-registry-product-view.tsx` | 非 owner 只读，owner 可切换模块和管理 API key 绑定 |

### 2.2 静态模块清单

当前 `backend/app/core/modules.py` 中存在的静态模块如下：

| module_key | 分类 | 说明 |
| --- | --- | --- |
| `core.dashboard` | core | 控制台 dashboard |
| `experimental.foundation_demo` | experimental | foundation demo |
| `integration.n8n_test_bridge` | integration | n8n mock test bridge |
| `integration.n8n_webhook_test_bridge` | integration | n8n webhook test bridge |
| `admin.users` | admin | 用户管理 |
| `admin.organizations` | admin | 组织管理 |
| `admin.permissions` | admin | 权限管理 |
| `admin.modules` | admin | 模块管理 |
| `admin.agents` | admin | agent 管理 |
| `admin.settings` | admin | 设置，当前为 planned 类型能力 |
| `business.products` | business | 产品/业务对象能力 |
| `business.approvals` | business | 审批 |
| `business.reviews` | business | 复核 |
| `system.errors` | system | 系统错误 |
| `system.memory_events` | system | memory events |
| `system.operation_logs` | system | operation logs |

### 2.3 动态模块注册

动态模块由 `module_registry` 表提供，服务层在 `backend/app/services/module_registry.py` 中实现。

注册规则：

- `module_key` 必须是 lowercase dot segments。
- module category、status、denied behavior 会被校验。
- external dependency 名称不得包含敏感标记，例如 `secret`、`token`、`password`、`credential`、`authorization`、`api_key`、URL 标记等。
- 动态模块会被转换为 `ModuleManifestV1`，与静态 manifest 合并返回。
- 动态模块前端路由默认为 `/modules/{module_id}`。

动态模块状态映射：

| registry status | manifest status |
| --- | --- |
| `foundation` | `installed` |
| `demo` | `enabled` |
| `draft_demo` | `planned` |
| `inactive_demo` | `disabled` |

### 2.4 模块访问 API

模块相关控制平面路由在 `backend/app/api/routes/modules.py`：

| 路由 | 权限 | 说明 |
| --- | --- | --- |
| `GET /api/control-plane/modules` | `REGISTRY.admin` | 模块列表 |
| `GET /api/control-plane/modules/registry` | `REGISTRY.admin` | 模块 registry |
| `GET /api/control-plane/modules/me` | cached/lightweight control-plane admin | 当前用户可见模块 |
| `GET /api/control-plane/modules/{module_key}` | `REGISTRY.admin` | 单模块详情 |
| `POST /api/control-plane/modules` | control-plane admin | 创建动态模块 |

`/modules/me`、`/modules/registry` 和 `/module-control/center` 是控制台首屏热路径，代码中提供轻量 RBAC 和进程缓存优化。

### 2.5 module-control center

module-control center 的读取路由：

```text
GET /api/control-plane/module-control/center
```

关键实现：

- API：`backend/app/api/routes/module_control.py`
- 构建服务：`backend/app/services/module_control_center.py`
- 缓存服务：`backend/app/services/module_control_cache_service.py`
- 模型：`backend/app/models/module_control.py`

返回内容来自：

- active organizations：`organizations.status != deleted`
- static + dynamic module manifests
- `module_control_states`
- execution state snapshot
- API key binding summary

读取 center 时，如果某组织某模块没有 `module_control_states` 记录，响应会把它表现为默认 active/enabled；读取本身不会自动写入缺失状态。

### 2.6 模块状态写入

模块状态修改路由：

```text
PATCH /api/control-plane/module-control/organizations/{org_id}/registry-entries/{module_id}
```

权限要求：

- 必须通过 `require_owner()`
- 使用 owner 全局上下文，并绕过普通 org 数据隔离

状态规则：

- missing state 会在更新时创建。
- `enabled=true` 时 runtime_status 默认 `active`。
- `enabled=false` 时 runtime_status 为 `disabled`，除非记录 runtime error。
- runtime error 可由 `record_module_runtime_error()` 写入，包含 error_code、error_message、last_error_at。
- 更新后会 patch 当前进程缓存，并触发异步强制刷新。

### 2.7 module_control_states 表

`module_control_states` 表核心字段：

| 字段 | 说明 |
| --- | --- |
| `org_id` | 组织 ID |
| `module_id` | 模块 ID/module_key |
| `enabled` | 是否启用 |
| `runtime_status` | `active`、`disabled`、`error` |
| `last_error_code` | 最近错误码 |
| `last_error_message` | 最近错误描述 |
| `last_error_at` | 最近错误时间 |
| `updated_by_user_id` | 最近修改人 |
| `metadata` | 扩展元数据 |

约束：

- `(org_id, module_id)` 唯一。
- 对 `(org_id, runtime_status)`、`module_id` 建索引。

### 2.8 前端模块中心行为

前端模块中心位于 `frontend/src/components/module-registry-product-view.tsx`：

- 非 owner/super admin 用户看到只读模块 registry/status。
- owner 进入 `OwnerModuleControlCenter`。
- owner 可以：
  - 查看组织与模块状态矩阵。
  - 启用/停用组织内模块。
  - 创建、更新、删除 API key。
  - 创建、删除模块 API key 绑定。
  - 触发 n8n webhook test。

## 3. API Key 管理系统

### 3.1 目标

API Key 管理系统为组织内模块提供外部调用凭据编排能力。它不把明文 key 暴露给前端，而是由后端在执行 gate 中解析并注入到外部请求。

关键代码：

- 模型：`backend/app/models/api_keys.py`
- Schema：`backend/app/schemas/api_key_orchestration.py`
- 服务：`backend/app/services/api_key_orchestration.py`
- 路由：`backend/app/api/routes/api_key_orchestration.py`
- 前端 API：`frontend/src/lib/api-key-orchestration-api.ts`

### 3.2 数据模型

`api_key_records`：

| 字段 | 说明 |
| --- | --- |
| `key_id` | 对外唯一 key id |
| `org_id` | 所属组织 |
| `name` | key 名称 |
| `url` | provider URL，限制 HTTP/HTTPS、无 userinfo、无 query/fragment |
| `encrypted_key_value` | 加密后的 key 值 |
| `key_fingerprint` | 指纹，用于后端比对 |
| `key_hash_prefix` | 可返回前端的 hash prefix |
| `status` | `active`、`disabled`、`deleted` |
| `last_used_at` | 最近注入使用时间 |
| `metadata` | 扩展信息 |

`api_key_module_bindings`：

| 字段 | 说明 |
| --- | --- |
| `binding_id` | 对外唯一 binding id |
| `org_id` | 所属组织 |
| `module_id` | 绑定模块 |
| `key_id` | 绑定 API key |
| `key_alias` | key alias，例如 `default`、`n8n` |
| `status` | `active`、`disabled` |

约束：

- `api_key_records.key_id` 唯一。
- `(org_id, module_id, key_id)` 唯一。
- 绑定 key 必须属于同一个 `org_id`。

### 3.3 加密与返回策略

服务层使用加密 envelope：

```text
akv1.<base64(nonce + mac + ciphertext)>
```

实现位于 `backend/app/services/api_key_orchestration.py`：

- nonce 长度 16 bytes。
- MAC 为 HMAC-SHA256，32 bytes。
- ciphertext 由 HMAC-SHA256 keystream XOR 生成。
- key material 来源优先级：
  1. `API_KEY_ENCRYPTION_SECRET`
  2. `OWNER_PASSWORD`
  3. `DATABASE_URL`

返回前端时只返回 hash prefix、状态、URL 等元信息，不返回：

- 明文 key
- encrypted key value
- fingerprint

### 3.4 API 路由

所有 API key orchestration 路由都在：

```text
/api/control-plane/api-key-orchestration
```

并且全部要求 `require_owner()`。

| 方法与路径 | 说明 |
| --- | --- |
| `GET /keys` | 列出 key |
| `POST /organizations/{org_id}/keys` | 为组织创建 key |
| `PATCH /keys/{key_id}` | 更新 key 元数据或密钥值 |
| `DELETE /keys/{key_id}` | 软删除 key，并禁用相关 binding |
| `GET /bindings` | 列出绑定 |
| `POST /organizations/{org_id}/bindings` | 创建模块 key 绑定 |
| `DELETE /bindings/{binding_id}` | 禁用绑定 |

创建绑定时会检查：

- 组织存在且 active。
- 模块存在于静态或动态 registry。
- key 存在且 active。
- key 的 `org_id` 与目标组织一致。
- alias 被规范化为小写下划线格式。

### 3.5 执行时注入

执行时由：

```text
resolve_module_api_key_for_injection(db, org_id, module_id, key_alias="default")
```

解析 active binding 和 active key，并返回：

- provider URL
- header name：`Authorization`
- header value：`Bearer {secret}`
- key metadata

解析成功会更新 `last_used_at`。

`n8n-webhook-test` 使用该机制将 API key 注入 HTTP 请求头。

## 4. RBAC 权限模型（owner / super_admin / viewer）

### 4.1 角色定义

角色定义位于：

- `backend/app/core/roles.py`
- `backend/app/core/rbac.py`

标准角色：

| 角色 | 说明 |
| --- | --- |
| `owner` | 系统拥有者，最高控制权限，不能通过普通用户管理 API 分配 |
| `admin` | 管理员角色，可执行 read/write/execute/admin |
| `super_admin` | 兼容/保留角色，代码中归一化并作为 admin alias 参与 RBAC |
| `module_admin` | 模块管理员兼容角色，归一化为 admin alias |
| `operator` | 操作员，可 read/write |
| `reviewer` | 审核兼容角色，归一化为 operator alias |
| `viewer` | 只读角色 |
| `system` | 内部系统角色 |
| `bot_agent` | bot agent 兼容角色，归一化为 system alias |

可由普通用户管理流程分配的用户角色：

- `admin`
- `viewer`
- `operator`
- `reviewer`

不可普通分配的角色：

- `owner`
- `super_admin`
- `module_admin`
- `system`
- `bot_agent`

### 4.2 owner

`owner` 是控制平面最高权限角色。

关键行为：

- `require_owner()` 先通过 permission engine 检查 `ADMIN.admin`，再硬检查 `is_owner_role()`。
- API key orchestration 全部要求 owner。
- module-control 状态写入要求 owner。
- owner 路由通常使用 `without_org_data_isolation()` 执行全局读写。
- owner 可以访问前端模块控制中心的写操作。

注意：统一权限引擎中，owner 并非在所有组织数据路径上无条件绕过。对于 organization scope 的业务权限仍需要上下文和组织关系，除非代码显式进入 owner/global bypass。

### 4.3 super_admin

`super_admin` 在代码中存在于标准角色列表，但属于不可普通分配角色。

当前语义：

- `backend/app/core/rbac.py` 将 `super_admin` 作为 legacy alias 映射为 `admin`。
- 前端 `PermissionRouteGuard` 对 owner 或 super_admin 视为权限管理页面的特权用户。
- 控制平面轻量 admin 判断最终仍依赖统一权限决策。

因此，`super_admin` 是保留兼容角色，而不是常规可创建角色。未来接入若要使用它，应先明确是否要把它升级为正式可分配角色。

### 4.4 viewer

`viewer` 是只读角色。

当前行为：

- 在 RBAC action 中只允许 `read`。
- 不能执行 `write`、`execute`、`admin`。
- 不能访问 owner-only API key orchestration。
- 不能修改 module-control 状态。
- 前端通常只能看到可访问模块和只读状态。

### 4.5 统一权限引擎

核心实现：`backend/app/services/unified_permission_engine.py`

三类决策：

| 决策入口 | 说明 |
| --- | --- |
| `decide_platform_metadata()` | 面向 legacy/platform module metadata，例如 ADMIN、REGISTRY、GOVERNANCE、C 系列模块 |
| `decide_permission_key()` | 基于 `permission_registry` 与 `user_permission_assignments` 的显式权限 |
| `decide_org_module()` | 面向组织上下文和模块绑定的权限决策 |

组织模块决策要求：

- 用户 active。
- 组织 membership active。
- 组织绑定了目标模块。
- 用户角色 action 允许。
- 模块 action 允许。

### 4.6 权限数据表

| 表 | 说明 |
| --- | --- |
| `permission_registry` | 权限定义，包含 permission_key、module_key、category、action、risk、menu_policy |
| `user_permission_assignments` | 用户显式权限分配，支持 scope_type/scope_key 和过期时间 |
| `role_default_permissions` | 角色默认权限 |
| `org_memberships` | 用户在组织内的角色，角色值为 owner/admin/member |
| `module_bindings` | 组织与模块的绑定关系 |

### 4.7 权限中间件

`backend/app/middleware/permission.py` 会基于请求自动推导：

- org id
- module id
- action
- request path marker

C15 路径标记，例如：

- `/workflow-registry/decision`
- `/webhook-gateway`
- `/callback-handler`
- `/payload-standardization/normalize`
- `/module-workflow-bindings/decision`

会映射为 execute 类操作。

C14 路径标记，例如：

- `/execution-prompts`
- `/ai-execution-bindings`

也会映射为 execute 类操作。

如果 C18 权限表不存在，middleware 会进入兼容放行模式，便于旧数据库迁移；正常环境不应依赖该兼容路径。

## 5. Execution Gate 机制

### 5.1 两层 gate

当前代码中存在两类 execution gate：

| Gate | 关键代码 | 用途 |
| --- | --- | --- |
| C13E Execution Flow Gate | `backend/app/services/execution_flow_gate.py` | 描述完整 C08/C12/C14/C09/C10 执行链路与 live/mock/staging 模式约束 |
| Module Execution Gate | `backend/app/services/module_execution_gate.py` | 实际用于 n8n-test、n8n-webhook-test 的模块执行前检查和 API key 解析 |

### 5.2 C13E Execution Flow Gate

完整链路定义：

```text
C08 Module Adapter
  -> C13E Execution Flow Gate
  -> C12 Approval Gate
  -> C14 External Dependency Gate
  -> C09 Execution Provider
  -> C10 Sandbox
```

该 gate 检查：

- emergency kill switch。
- 用户身份是否存在、有效。
- module switch runtime gate。
- 下游 switch。
- sandbox envelope source/target/contract。
- C08 adapter/action contract 是否安全。
- C12 approval gate。
- C14 external dependency gate。
- C09 provider contract readiness、executable、external endpoint、callback。
- C10 runtime status 和 secret binding。
- live/mock/staging 模式是否被允许。

`ExecutionFlowGateDecision` 明确记录：

- `c08_allowed`
- `c12_allowed`
- `c14_allowed`
- `c09_allowed`
- `c10_allowed`
- `c13_allowed`
- `runtime_execution_allowed`
- `external_provider_call_allowed`
- `production_impact_allowed`
- bypass blocked 状态

### 5.3 Module Execution Gate

`backend/app/services/module_execution_gate.py` 是当前实际执行路径中最直接的 gate。

它负责：

- 解析 org context。
- 兼容 legacy module id：
  - `foundation_demo` -> `experimental.foundation_demo`
  - `n8n_test_bridge` -> `integration.n8n_test_bridge`
- 检查模块是否存在于 registry。
- 若模块状态缺失，首次执行时创建默认 active control state。
- 阻断 disabled 或 runtime_status disabled/error 的模块。
- 按模块所需 alias 解析 API key binding。
- 生成 redacted key map，避免泄露 key。
- 写入 `module.execution_gate` 事件。

API key 缺失或不可用会转换为：

```text
API_KEY_BINDING_MISSING
```

### 5.4 Live Gate

Live gate API 位于：

```text
/api/control-plane/live-gate
```

权限：`GOVERNANCE.admin`

关键代码：

- `backend/app/api/routes/live_gate.py`
- `backend/app/services/live_gating.py`
- `backend/app/services/pre_live_validation.py`

行为：

- mock/staging 模式不要求 live enablement。
- live 模式要求：
  - valid mode
  - C12 unlock
  - canary routed live
  - pre-live validation passed
  - global live switch enabled
  - org policy active/enabled
  - module policy active/enabled
  - org/module 均非 staging_only

Pre-live validation 检查：

- Alembic migration head/current。
- health。
- permission seed 唯一性。
- C17 tables/trace columns。
- C08/C09 contracts。
- ops live tables org-scoped。

### 5.5 与 n8n 的关系

- `n8n-test` 是 mock-only 路径，不执行真实外部 webhook。
- `n8n-webhook-test` 会经过 module execution gate，并通过 API key binding 获取 Authorization header 后发起 HTTP POST。
- C15B Webhook Gateway 本身不直接 dispatch n8n，而是负责签名、payload、workflow binding 和 hidden webhook reference 的判定。

## 6. Webhook / n8n 集成

### 6.1 C15B Webhook Gateway

关键代码：

- 路由：`backend/app/api/routes/webhook_gateway.py`
- 服务：`backend/app/services/webhook_gateway.py`
- 配置：`WEBHOOK_GATEWAY_SIGNING_SECRET`、`WEBHOOK_GATEWAY_SIGNATURE_TOLERANCE_SECONDS`、`WEBHOOK_REPLAY_NONCE_TTL_SECONDS`

入口：

```text
POST /api/control-plane/webhook-gateway/ingress
```

权限：

- `require_internal_rbac("C15B")`

签名模型：

- Header：`X-Barong-Gateway-Signature`
- 格式：`sha256=<hex>`
- 算法：HMAC-SHA256
- 输入：canonical JSON，`sort_keys`、`exclude_none`、紧凑 separators
- 时间窗口默认 300 秒
- replay nonce 写入 `security_replay_nonces`，默认 TTL 900 秒

payload 安全规则：

- 禁止敏感字段名：secret、token、password、credential、authorization、api_key 等。
- 禁止直连 runtime 地址和值：`http://`、`https://`、`n8n-webhook-ref://`、`bearer`、`authorization`。
- gateway 不直接向 n8n dispatch。

返回 decision 内容包含：

- signature valid/invalid
- workflow registry decision
- module-workflow binding decision
- hidden webhook reference
- `n8n_dispatch_performed=false`
- `runtime_execution_allowed=false`

### 6.2 Callback Handler

关键代码：

- `backend/app/api/routes/callback_handler.py`
- callback/execution 相关模型位于 `backend/app/models`

核心路由：

| 路由 | 说明 |
| --- | --- |
| `POST /api/control-plane/callback-handler/receiver` | 接收 signed callback |
| `POST /api/control-plane/callback-handler/context-bindings` | 绑定 context，需要 org context 与 `C15D.execute` |
| `GET /api/control-plane/callback-handler/results/{context_id}` | 查询结果 |

receiver 同样使用 gateway signature header/secret，并使用 replay nonce 和 idempotency key。结果持久化到：

- `callback_state`
- `callback_state_transitions`
- `execution_callbacks`
- `execution_results`

### 6.3 n8n-test bridge

关键代码：

- 路由：`backend/app/api/routes/n8n_test.py`
- 服务：相关 n8n test service/model 代码

特征：

- 模块：`integration.n8n_test_bridge`
- mock-only。
- 不向真实外部 n8n webhook dispatch。
- run 路由要求 `C15.execute`。
- 经过 module execution gate，并要求 `dispatch` alias 的 key binding。
- 运行时会创建 demo job/artifact/review/memory/error/operation logs 等兼容数据。
- callback 路径需要 `X-Barong-Callback-Secret` 和内部 RBAC `C15D`。

### 6.4 n8n-webhook-test bridge

关键代码：

- 路由：`backend/app/api/routes/n8n_webhook_test.py`
- 服务：`backend/app/services/n8n_webhook_test_service.py`

特征：

- 模块：`integration.n8n_webhook_test_bridge`
- 配置：`N8N_TEST_WEBHOOK_URL`、`N8N_TEST_CALLBACK_SECRET`、timeout。
- request 支持 `org_id`、`key_alias`、`correlation_id`、`payload`。
- 默认 key alias：`n8n`。
- payload 禁止敏感数据和 runtime 地址。
- 经过 module execution gate，key requirement 为 `webhook:{key_alias}`。
- HTTP POST 使用 `httpx`。
- retry max 2。
- retryable status：408、429、500、502、503、504。
- backoff：0.2 秒。
- headers 包含：
  - `Authorization: Bearer {secret}`
  - `X-Barong-Module-Id`
  - `X-Barong-Run-Id`
  - `X-Barong-Org-Id`
- response body 会清洗后返回/记录。

## 7. 前端 UI 架构（SaaS design system）

### 7.1 技术栈

前端位于 `frontend/`：

- Next.js 16.2.7
- React 19.2.7
- TypeScript
- lucide-react icons
- Node >= 24
- Playwright 作为开发测试依赖

### 7.2 应用布局

根布局：

- `frontend/src/app/layout.tsx`
- 包裹 `AuthProvider`
- 导入 `globals.css`

控制台布局：

- `frontend/src/app/(console)/layout.tsx`

控制台 layout 组合：

```text
AuthGuard
  -> CapabilityStateProvider
  -> ModuleAccessProvider
  -> AdapterAccessProvider
  -> ConsoleShell
  -> PermissionRouteGuard
```

### 7.3 AuthProvider 与会话模型

关键代码：

- `frontend/src/components/auth-provider.tsx`
- `frontend/src/lib/api.ts`

行为：

- 同时支持 localStorage session token 与 HttpOnly cookie。
- 后台 `/auth/me` 检查 timeout 1500ms。
- login 通过 `loginInFlightRef` 去重。
- route change 时 abort active API requests/session checks。
- 401 会触发 `barong-auth-unauthorized` 事件。
- force password reset 状态由 `AuthGuard` 重定向到 `/force-password-reset`。

### 7.4 API client

`frontend/src/lib/api.ts` 提供统一请求函数：

- base path：`/api/backend`
- 默认 timeout：15 秒
- capability bootstrap timeout：30 秒
- module-control timeout：60 秒
- GET/HEAD/OPTIONS 遇到 5xx、429 或 TypeError 时 retry once。
- 所有请求带 `credentials: "include"`。
- 从 localStorage 读取 `barong-auth-session` 并发送 `X-Session-Token`。
- route change 会 abort 仍在飞行的请求。

### 7.5 SaaS shell

关键代码：

- `frontend/src/components/console-shell.tsx`
- `frontend/src/components/saas-shell.tsx`
- `frontend/src/lib/navigation.ts`
- `frontend/src/app/globals.css`

Shell 包含：

- 侧边栏 navigation。
- 顶部 header。
- release badge。
- search。
- refresh。
- 用户菜单与 logout。
- capability fallback/degraded banner。

### 7.6 导航与模块映射

`frontend/src/lib/navigation.ts` 定义静态导航组：

| 分组 | 路由 | 模块 |
| --- | --- | --- |
| 账号与组织 | `/users` | `admin.users` |
| 账号与组织 | `/organizations` | `admin.organizations` |
| 账号与组织 | `/permissions` | `admin.permissions` |
| 业务处理 | `/approvals` | `business.approvals` |
| 业务处理 | `/reviews` | `business.reviews` |
| 系统管理 | `/dashboard` | `core.dashboard` |
| 系统管理 | `/modules` | `admin.modules` |
| 系统管理 | `/settings` | `admin.settings` |
| 系统管理 | `/errors` | `system.errors` |
| 系统管理 | `/memory-events` | `system.memory_events` |
| 系统管理 | `/operation-logs` | `system.operation_logs` |
| 扩展能力 | `/agents` | `admin.agents` |

### 7.7 Capability Bootstrap

后端路由：

- `backend/app/api/routes/capability_bootstrap.py`

前端状态：

- `frontend/src/components/capability-state-provider.tsx`
- `frontend/src/lib/capability-bootstrap-api.ts`

bootstrap 聚合：

- modules registry/me
- module adapters registry/me
- live gate policies

当前 deferred：

- execution providers
- readiness / production-readiness

前端策略：

- 先请求 `/capability/bootstrap`。
- 整体失败时 fallback 到多个单项 API。
- 保留上一次成功数据，局部失败时进入 degraded/fallback 而不是直接空白。

### 7.8 PermissionRouteGuard

关键代码：

- `frontend/src/components/permission-route-guard.tsx`

行为：

- `/users`、`/organizations`、`/permissions` 对 authenticated owner/super_admin 有显式 passthrough。
- 其他路由根据 capability graph 和 module access 决策。
- unknown/loading 状态不立即阻断，避免首屏闪断。

### 7.9 CSS design system

全局样式文件：

- `frontend/src/app/globals.css`

包含：

- light theme token：canvas、surface、line、text、muted、primary、success、warning、error、info。
- space/radius/shadow token。
- sidebar/topbar/page-content 布局。
- record-card、ops-panel、module-control-card、api-key-form。
- permissions 面板、表格、status pill。
- responsive media rules。

设计特征：

- 控制台型 SaaS UI，不是营销页。
- 信息密度高，侧重扫描、操作和状态对比。
- 图标主要来自 lucide-react。
- module-control 与 API key 管理使用表单、状态 pill、矩阵和操作按钮组合。

## 8. 数据库结构说明

数据库模型集中在 `backend/app/models`，命名约定在 `backend/app/db/base.py`。会话管理在 `backend/app/db/session.py`：

- 同时创建 sync/async engine。
- 使用 pool pre_ping、pool_recycle。
- PostgreSQL 设置 statement timeout 和 idle transaction timeout。
- `ManagedSession.close()` 会 rollback 未结束事务。
- `get_db()` 成功 commit，异常 rollback。
- `managed_read_session()` 总是 rollback。

### 8.1 Identity / Auth

| 表 | 说明 |
| --- | --- |
| `users` | 用户，包含 username、password_hash、role、job_title、organization_id、must_change_password、is_active、failed_login_count、locked_until、last_login_at |
| `auth_sessions` | 登录 session，包含 session_id_hash、user_id、issued/expires/invalidated/last_seen、ip、user_agent |
| `security_rate_limit_buckets` | 安全限流 bucket |
| `security_replay_nonces` | webhook/callback replay nonce |

### 8.2 Organization / Tenant

| 表 | 说明 |
| --- | --- |
| `organizations` | 组织，主键 `org_id`，要求 `org_` 前缀与长度约束，含 name/org_type/owner_user_id/status/metadata |
| `org_memberships` | 用户组织成员关系，角色为 owner/admin/member，状态 active/suspended，`(user_id, org_id)` 唯一 |
| `module_bindings` | 组织模块绑定 |
| `shared_modules` | shared module 可见性/共享 |
| `contact_identities` | 联系人身份数据 |
| `messages` | 消息数据 |
| conversation/contact/attachment 相关表 | 控制台沟通域模型 |

### 8.3 Permission

| 表 | 说明 |
| --- | --- |
| `permission_registry` | 权限定义 |
| `user_permission_assignments` | 用户权限分配，支持 scope 与 expires_at |
| `role_default_permissions` | 角色默认权限 |

### 8.4 Module / Registry / API Key

| 表 | 说明 |
| --- | --- |
| `module_registry` | 动态模块注册 |
| `agent_registry` | agent registry |
| `workflow_registry` | workflow registry |
| `module_control_states` | 组织模块 runtime 状态 |
| `api_key_records` | API key 密文记录 |
| `api_key_module_bindings` | API key 与模块 alias 绑定 |

### 8.5 Execution / Approval / Callback

| 表 | 说明 |
| --- | --- |
| `approval_requests` | 审批请求 |
| `approval_workflows` | 审批 workflow |
| `approval_decisions` | 审批决策 |
| `execution_callbacks` | callback 入站记录 |
| `execution_results` | 执行结果 |
| `callback_state` | callback 状态 |
| `callback_state_transitions` | callback 状态变更 |
| `execution_dlq` | execution dead letter queue |
| `dlq_state` | DLQ 状态 |

### 8.6 Observability / Ops

| 表 | 说明 |
| --- | --- |
| `operation_logs` | 操作日志 |
| `event_streams` | 事件流 |
| `audit_logs` | 审计日志 |
| `replay_jobs` | replay job |
| `anomaly_events` | 异常事件 |
| `storage_events` | storage event |
| `ops_alerts` | 运维告警 |
| `ops_alert_deliveries` | 告警投递 |
| `ops_live_gate_policies` | live gate policy |
| `ops_execution_unlock_tokens` | execution unlock token |
| `ops_canary_rollouts` | canary rollout |
| `ops_rollback_guards` | rollback guard |

### 8.7 Legacy / Compatibility

以下表仍存在于模型或测试兼容路径，但部分外部路由已经被移除：

| 表 | 说明 |
| --- | --- |
| `automation_jobs` | 历史 job/automation 兼容表 |
| `job_events` | job event 兼容表 |
| `artifacts` | artifact 兼容表，`/api/app/artifacts` 当前 404 |
| `memory_events` | memory event |
| `memory_summaries` | memory summary |
| `agent_memory_access_logs` | agent memory access log |
| `system_errors` | 系统错误 |
| `review_items` | review item |
| `context_packets` | context packet |

### 8.8 数据隔离

组织数据隔离由 `backend/app/services/data_isolation.py` 和 `backend/app/middleware/data_isolation.py` 实现：

- `/api/app` 路径默认要求 org context，除白名单外。
- mutation JSON payload 中的 `org_id` 会被限制，特殊路径 `/api/app/module/bind` 例外。
- SQLAlchemy event 对 org-scoped model 自动加 `with_loader_criteria`。
- insert/update/delete 会校验 org context。
- 手写 SQL 默认受保护，除非显式使用 skip option。
- owner/global 读写必须显式使用 `without_org_data_isolation()`。

## 9. worker / concurrency 架构（2 workers）

### 9.1 后端 worker 模型

生产后端运行参数来自 `backend/Dockerfile` 与 `docker-compose.production.yml`：

| 参数 | 生产值 |
| --- | --- |
| `GUNICORN_WORKERS` | `2` |
| worker class | `uvicorn.workers.UvicornWorker` |
| `GUNICORN_TIMEOUT` | `120` |
| `GUNICORN_GRACEFUL_TIMEOUT` | `30` |
| `DB_POOL_SIZE` | `10` |
| `DB_MAX_OVERFLOW` | `20` |
| `DB_POOL_RECYCLE` | `600` |
| `DB_STATEMENT_TIMEOUT_MS` | `8000` |
| `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS` | `8000` |

最大理论 app DB 连接数：

```text
workers * (pool_size + max_overflow)
= 2 * (10 + 20)
= 60
```

### 9.2 每个 worker 内部后台线程

FastAPI startup 在 `backend/app/main.py` 启动以下后台工作：

| 线程 | 关键代码 | 说明 |
| --- | --- | --- |
| `barong-session-last-seen-flush` | session seen worker | 批量刷新 session last_seen |
| `barong-login-side-effects` | login side effect worker | 异步写 last login、失败计数、lockout、operation log |
| `barong-module-control-cache` | module control cache service | 每 5 秒刷新 module-control center 快照 |

shutdown 时会停止这些线程。

### 9.3 session last_seen worker

行为：

- flush interval：60 秒。
- batch size：500。
- 最大 tracked sessions：8192。
- 请求中只 queue last_seen，降低热路径写压力。

### 9.4 login side effects worker

行为：

- queue size：10000。
- poll timeout：0.5 秒。
- max attempts：3。
- 负责登录成功/失败的副作用写入和 operation log。

### 9.5 module-control cache worker

行为：

- TTL：5 秒。
- refresh interval：5 秒。
- wait timeout：0.5 秒。
- 返回 fresh/stale/partial JSON。
- PATCH module-control 状态后会 patch 当前 snapshot 并异步 force refresh。

注意：缓存是每个 Gunicorn worker 进程内独立的，不是跨 worker 共享缓存。

### 9.6 其他并发控制

| 机制 | 位置 | 说明 |
| --- | --- | --- |
| request session cache | `backend/app/core/request_session_cache.py` | 每请求缓存认证 session |
| permission request cache | `PermissionDecisionEngine` | 缓存本请求权限决策 |
| API request guard | `backend/app/core/api_request_guard.py` | heavy request throttling 与重复 in-flight guard |
| frontend proxy cache | `frontend/src/app/api/backend/[...path]/route.ts` | capability bootstrap 60 秒 TTL、in-flight dedupe、fallback 并发限制 6 |

事件队列 backend 存在 `barong-audit-event-queue` 能力，但默认 emitter 为 `EventQueueBackend(auto_drain=False)`，主入口当前没有启动该 drain worker；高频 success 事件会被降噪，不应假设所有成功事件都落库。

## 10. E2E 测试体系说明

### 10.1 后端测试

配置：

- `backend/pytest.ini`
- test paths：`tests/backend`
- markers：`unit`、`integration`、`system`、`slow`

`tests/backend/conftest.py` 负责：

- 根据文件名和源码信号自动打 unit/integration marker。
- 集成测试要求 `BARONG_TEST_DB_READY=1`。
- 拒绝危险 DATABASE_URL。
- 提供 `clear_auth_tables()` 清理表。
- 重置 session seen worker 和 module-control cache。
- `owner_client` fixture 创建 owner 用户、组织、membership 并登录。

后端测试脚本：

```text
scripts/run_backend_tests.sh
```

模式：

- `unit`：运行 `pytest -m unit`
- `integration` / `all`：
  - 启动临时 `postgres:17.5-alpine`
  - 映射随机本地端口
  - 设置 `DATABASE_URL`
  - 设置 `BARONG_TEST_DB_READY=1`
  - 执行 Alembic upgrade head
  - 运行 pytest

安全限制：

- 拒绝 production/prod/ops domain database URL。
- 要求测试 DB 是 isolated `barong_test` 或 localhost/127.0.0.1。

### 10.2 前端测试

前端脚本：

- `frontend/package.json`
- `scripts/run_frontend_tests.sh`

主要命令：

| 命令 | 说明 |
| --- | --- |
| `npm run test` | `node --test tests/frontend/*.test.mjs` |
| `npm run typecheck` | 清理 Next dev types 后执行 `tsc --noEmit` |
| `npm run verify` | `node scripts/verify-foundation.mjs` |

前端 Dockerfile verification stage 会执行：

- `npm run test`
- `npm run verify`
- `npm run typecheck`

前端测试覆盖方向包括：

- auth flow
- permissions
- permission management
- module-control state
- module isolation
- request dedup
- control-plane isolation
- module-workflow binding
- API execution binding

### 10.3 Strict E2E Audit

脚本：

```text
scripts/strict_e2e_audit.py
```

行为：

- 启动隔离 PostgreSQL docker。
- 运行 Alembic。
- 创建 owner/viewer/org/API key 测试数据。
- 使用 TestClient 和可选 Playwright/browser fallback。
- 验证：
  - owner login
  - auth/me
  - module-control center
  - API key list/create/binding/injection
  - org list
  - non-owner 403
  - secret 不泄露

输出报告：

- `system_e2e_test_report.json`
- `api_key_integration_validation_report.json`
- `module_execution_chain_report.json`
- `ui_user_flow_validation_report.json`
- `permission_isolation_report.json`
- `critical_failure_report.json`
- `broken_chain_analysis.json`
- `system_integrity_risk_report.json`

## 11. 部署结构说明（docker / production）

### 11.1 后端镜像

文件：

- `backend/Dockerfile`

特征：

- base image：`python:3.12.13-slim`
- 安装 `backend/requirements.txt`
- 创建非 root 用户 `app`
- expose 8000
- 默认 Gunicorn 2 workers
- Uvicorn worker class

### 11.2 前端镜像

文件：

- `frontend/Dockerfile`

特征：

- build image：`node:24.15.0-alpine`
- `npm ci`
- verification stage 执行 test/verify/typecheck
- Next standalone build
- runtime 非 root `nextjs`
- expose 3000
- 运行 `node server.js`

### 11.3 Production Compose

文件：

- `docker-compose.production.yml`

服务：

| 服务 | 说明 |
| --- | --- |
| `console_postgres` | PostgreSQL 17.5 alpine，volume `console_postgres_data`，healthcheck |
| `console_backend` | FastAPI backend，依赖 postgres healthy，绑定 `127.0.0.1:8000` |
| `console_frontend` | Next.js frontend，依赖 backend，绑定 `127.0.0.1:3000` |

网络：

- `barong-ops-console-prod`

生产 backend 环境覆盖：

- `GUNICORN_WORKERS=2`
- `DB_POOL_SIZE=10`
- `DB_MAX_OVERFLOW=20`
- `DB_POOL_RECYCLE=600`
- statement/idle transaction timeout 8000ms

### 11.4 Staging Compose

文件：

- `docker-compose.staging.yml`

特征：

- 独立 service name、volume、network。
- 使用 `.env.staging`。
- backend 绑定 `127.0.0.1:8100`。
- frontend 绑定 `127.0.0.1:3100`。

### 11.5 环境变量示例

生产示例：

- `.env.production.example`

关键值：

- `APP_ENV=production`
- `APP_DOCS_ENABLED=false`
- `BACKEND_API_URL=http://console_backend:8000`
- `NEXT_PUBLIC_API_BASE_URL=https://ops.barongyekhna.com`
- `GUNICORN_WORKERS=2`
- cookie secure true、SameSite none、path `/api/backend`
- n8n test webhook/callback 默认为空
- `WEBHOOK_GATEWAY_SIGNING_SECRET` 示例值必须上线替换
- `CONTROL_PLANE_STEALTH_MODE=true`
- owner password 只用于首次 bootstrap，之后应清空/轮换

预发示例：

- `.env.staging.example`

关键值：

- `APP_ENV=staging`
- `BACKEND_API_URL=http://console_staging_backend:8000`
- `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:3100`
- cookie secure false、SameSite lax
- n8n 默认为空
- `CONTROL_PLANE_STEALTH_MODE=true`

### 11.6 Nginx

模板：

- `deploy/nginx/ops.barongyekhna.com.conf.template`

行为：

- 80 redirect 到 HTTPS。
- 443 proxy 到 frontend `127.0.0.1:3000`。
- 设置 HSTS、CSP、X-Frame-Options、nosniff、referrer policy、permissions policy。
- stealth deny：
  - `/webhook`
  - `/n8n`
  - `/api/backend/(webhook|n8n)`
  - `/api/backend/webhook-gateway/ingress`

### 11.7 安全部署脚本

安全发布：

- `scripts/safe_compose_release.sh`

约束：

- 仅允许 service：backend/frontend。
- 禁止 postgres release。
- 禁止 down/restart。
- execute 需要 `CONFIRM_SAFE_RELEASE=yes`。
- production 还需要 `CONFIRM_PRODUCTION_RELEASE=yes`。
- 支持 dry-run。
- pre/post smoke。
- build target image。
- tag rollback。
- 仅移除目标 container 后 `compose up --no-deps --no-build`。

生产文件检查：

- `scripts/check_production_deploy_files.sh`

检查：

- production compose/env example/nginx template/.gitignore。
- `.env.production` 被忽略。
- production example 中 n8n 默认为空。
- docker compose config 有效。

生产 smoke：

- `scripts/production_smoke_check.sh`

检查：

- 必须 HTTPS URL。
- `/login` 200。
- `/api/backend/health` 返回 ok/service。
- HTTP -> HTTPS 301。
- docker ps 中 console 容器存在。
- postgres 不应 host-exposed。

## 12. 未来 K 系列接入参考

K 系列接入应复用 C-SERIES V1 的模块与权限边界，不应绕过现有 gate。

### 12.1 推荐接入步骤

1. 定义模块 manifest。
   - 静态模块放入 `backend/app/core/modules.py`，或通过 `module_registry` 动态注册。
   - `module_key` 使用 lowercase dot segments。
   - 明确 category、status、route、required actions。

2. 定义权限。
   - 写入 `permission_registry` seed 或显式分配。
   - 明确 read/write/execute/admin action。
   - 不要假设 owner 对所有 org-scoped 数据天然绕过。

3. 定义组织绑定。
   - 使用 `module_bindings` 控制组织是否拥有该模块。
   - module-control center 会按组织展示模块 runtime 状态。

4. 接入 module-control。
   - 若模块有运行能力，执行前必须检查 `module_control_states`。
   - disabled/error 状态必须阻断执行。

5. 接入 API key orchestration。
   - 外部 provider 凭据不要放在 payload。
   - 使用 `api_key_records` 与 `api_key_module_bindings`。
   - 执行时由后端解析并注入。

6. 接入 execution gate。
   - mock/staging/live 模式走 `ExecutionModeAwareGate` 或等价路径。
   - 实际模块执行前至少走 `module_execution_gate`。

7. 接入 webhook/callback。
   - 入站 webhook 使用 C15B gateway 签名和 replay nonce。
   - callback 使用 C15D callback handler。
   - 不允许前端直接暴露 n8n/webhook runtime URL。

8. 接入前端 capability graph。
   - 更新 navigation/module route 映射。
   - 确保 `CapabilityStateProvider` 能降级显示。
   - owner 写能力与普通用户只读能力要分离。

9. 增加测试。
   - 后端 unit/integration 覆盖权限、组织隔离、module-control、API key injection、gate deny/allow。
   - 前端测试覆盖 route guard、能力降级、owner/non-owner UI。
   - strict E2E audit 增加核心链路。

10. 更新部署与安全检查。
    - 新环境变量加入 `.env.*.example`。
    - 生产默认不得包含真实外部 secret。
    - Nginx/proxy 不得开放 runtime webhook/n8n 直连路径。

### 12.2 不应绕过的系统边界

- 不要从前端直接调用外部 n8n webhook。
- 不要把 API key 明文返回前端。
- 不要让 payload 携带 secret/token/authorization 字段。
- 不要绕过 org membership 与 module binding。
- 不要在 production-like 环境绕过 Alembic migration safety。
- 不要依赖已移除的 `/api/app/jobs`、`/api/app/artifacts`、`/api/control-plane/workflows` 运行路由。

## 13. 核心源码索引

| 领域 | 文件 |
| --- | --- |
| FastAPI 入口 | `backend/app/main.py` |
| 配置 | `backend/app/core/config.py` |
| DB session | `backend/app/db/session.py` |
| 角色/RBAC | `backend/app/core/roles.py`、`backend/app/core/rbac.py` |
| 依赖与鉴权 | `backend/app/api/deps.py` |
| 权限引擎 | `backend/app/services/unified_permission_engine.py` |
| 权限中间件 | `backend/app/middleware/permission.py` |
| 数据隔离 | `backend/app/middleware/data_isolation.py`、`backend/app/services/data_isolation.py` |
| 模块 manifest | `backend/app/core/modules.py` |
| 模块 registry | `backend/app/services/module_registry.py` |
| module-control | `backend/app/api/routes/module_control.py`、`backend/app/services/module_control_center.py`、`backend/app/services/module_control_cache_service.py` |
| API key orchestration | `backend/app/api/routes/api_key_orchestration.py`、`backend/app/services/api_key_orchestration.py` |
| Execution gate | `backend/app/services/execution_flow_gate.py`、`backend/app/services/module_execution_gate.py` |
| Live gate | `backend/app/api/routes/live_gate.py`、`backend/app/services/live_gating.py`、`backend/app/services/pre_live_validation.py` |
| Webhook gateway | `backend/app/api/routes/webhook_gateway.py`、`backend/app/services/webhook_gateway.py` |
| Callback handler | `backend/app/api/routes/callback_handler.py` |
| n8n test | `backend/app/api/routes/n8n_test.py` |
| n8n webhook test | `backend/app/api/routes/n8n_webhook_test.py`、`backend/app/services/n8n_webhook_test_service.py` |
| 前端 API client | `frontend/src/lib/api.ts` |
| 前端 proxy | `frontend/src/app/api/backend/[...path]/route.ts` |
| 前端 auth | `frontend/src/components/auth-provider.tsx`、`frontend/src/components/auth-guard.tsx` |
| 前端 shell | `frontend/src/components/console-shell.tsx`、`frontend/src/components/saas-shell.tsx` |
| 前端 capability | `frontend/src/components/capability-state-provider.tsx`、`frontend/src/lib/capability-bootstrap-api.ts` |
| 前端 module center | `frontend/src/components/module-registry-product-view.tsx` |
| 前端 design system | `frontend/src/app/globals.css` |
| 后端 Docker | `backend/Dockerfile` |
| 前端 Docker | `frontend/Dockerfile` |
| 生产 compose | `docker-compose.production.yml` |
| 预发 compose | `docker-compose.staging.yml` |
| Nginx template | `deploy/nginx/ops.barongyekhna.com.conf.template` |
| 后端测试脚本 | `scripts/run_backend_tests.sh` |
| 前端测试脚本 | `scripts/run_frontend_tests.sh` |
| Strict E2E audit | `scripts/strict_e2e_audit.py` |
