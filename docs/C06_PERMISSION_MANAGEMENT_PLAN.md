# C06 Permission Management Plan

日期：2026-06-11 UTC

本文件记录 C06A：用户权限管理页面与 grant/revoke 方案审计。

C06A 只做只读审计、方案设计、任务拆分和文档归档。本阶段不实现
grant/revoke API，不实现权限分配 UI，不新增 migration，不发布 staging 或
production，不接真实业务模块。

## 一、C06A 结论

- C06 可以开始。
- C05 已封板，并已在 production 生效。封板记录为
  `docs/C05_PERMISSION_SYSTEM_SEAL.md`。
- C06 只做用户权限管理能力，不接 WooCommerce、n8n 真实业务流、MinIO、
  Filebrowser、产品页业务模块或 P 系列。
- C06A 不实现 API/UI，只做方案。
- 当前代码已经有权限表、权限判断服务、`/auth/me.permissions`、
  `/permissions/me` 和 `/permissions/registry`。
- 当前代码没有公开的 owner-only grant/revoke/list assignment API。
- 当前代码没有权限分配 UI。
- 当前服务层已有 `grant_permission()`、`revoke_permission()` 和
  `disable_assignment()` helper，但这些 helper 没有 route 暴露，也没有写入
  `operation_logs`。C06B 不能把这些 helper 直接视为完整管理能力。

## 二、C06 总目标

- owner 能查看用户权限。
- owner 能给用户 grant permission。
- owner 能 revoke permission。
- owner 能查看 assignment 的 `scope_type`、`scope_key`、`is_enabled`、
  `expires_at`、`granted_by_user_id`、`reason`、`created_at` 和 `updated_at`
  等状态。
- 所有权限变更必须写 `operation_logs`。
- 高风险权限必须二次确认。
- 非 owner 不能越权授权。
- owner 不能通过 UI/API 把自己锁死。
- C06 不自动应用 `role_default_permissions`。
- C06 不让 `super_admin` 默认拥有全局授权能力。
- C06 不改变 `/users` 当前 owner-only 后端安全边界，除非后续独立任务明确批准。

## 三、当前 C05 基础能力

### permission_registry

当前 `permission_registry` 是系统权限目录，回答“系统承认哪些权限点”，不是用户授权事实。

模型位置：`backend/app/models/permission.py`。

字段：

- `id`：UUID 主键。
- `permission_key`：稳定权限 key，唯一，例如 `users.manage`。
- `module_key`：权限所属模块。
- `category`：`business`、`admin`、`system` 等类别。
- `action`：动作，例如 `read`、`create`、`manage`、`approve`、`release`。
- `label`：可读名称。
- `description`：说明。
- `risk_level`：`low`、`medium`、`high`、`critical`。
- `menu_policy`：`show_locked` 或 `hide_when_denied`。
- `is_system`：系统内置权限标记。
- `is_enabled`：目录项是否启用。
- `created_at` / `updated_at`：时间戳。

当前 registry seed source 在 `backend/app/core/permissions.py` 的
`BASE_PERMISSION_REGISTRY_SEED`。当前包含 `users.read`、`users.manage`、
`roles.read`、`permissions.read`、`permissions.manage`、`jobs.read`、
`jobs.create`、`jobs.manage`、`reviews.read`、`reviews.approve`、
`artifacts.read`、`operation_logs.read`、`modules.read`、`modules.manage`、
`settings.read`、`settings.manage`、`production.release`、`system.admin`。

当前 registry 读取方式：

- repository `list_enabled_permissions()` 查询 `is_enabled=true` 的目录项。
- service `list_enabled_permissions()` 直接包装 repository 查询。
- `GET /permissions/registry` 返回 enabled registry，使用 `ListResponse` 包装。
- C05C 不在 app startup 自动 seed，也不在 registry route 隐式 seed。

### user_permission_assignments

当前 `user_permission_assignments` 是非 owner 用户的授权事实。

模型位置：`backend/app/models/permission.py`。

字段：

- `id`：UUID 主键。
- `user_id`：目标用户 ID，外键到 `users.id`。
- `permission_key`：权限 key，外键到 `permission_registry.permission_key`。
- `scope_type`：`global`、`company`、`factory`、`department`、`organization`、
  `module`。
- `scope_key`：scope 内稳定 key；`global` 必须使用 `*`。
- `granted_by_user_id`：授权人用户 ID，可为空。
- `reason`：授权原因。
- `is_enabled`：assignment 是否启用。
- `expires_at`：可选过期时间。
- `created_at` / `updated_at`：时间戳。

唯一约束：

- `user_id + permission_key + scope_type + scope_key`

当前查询和判断方式：

- `list_user_assignments(db, user_id)` 返回该用户所有 assignment，不只返回生效项。
- `list_enabled_user_assignments(db, user_id, now=...)` join
  `permission_registry`，只返回用户匹配、assignment enabled、registry enabled、
  未过期的 assignment。
- `user_has_permission()` 先标准化 permission key 和 scope，再判断：
  - owner 直接返回 true。
  - permission 不存在或 disabled 返回 false。
  - 非 owner 只检查 enabled、未过期、registry enabled 的 assignment。
  - `global:*` assignment 能匹配任意 scope 请求。
  - scoped assignment 不能反向提升为 global permission。
  - 同 scope 下 `scope_key="*"` 可以匹配该 scope type 的任意 key。
- `resolve_effective_permissions()` 和 `resolve_current_user_permission_info()`
  复用上述规则，构造当前用户的 effective permissions。

### role_default_permissions

当前 `role_default_permissions` 是角色建议模板，不是授权事实。

字段：

- `id`：UUID 主键。
- `role`：标准 role。
- `permission_key`：权限 key。
- `scope_type` / `scope_key`：建议 scope。
- `is_enabled`：模板是否启用。
- `created_at` / `updated_at`：时间戳。

唯一约束：

- `role + permission_key + scope_type + scope_key`

当前结论必须明确：

- `role_default_permissions` 不自动生效。
- resolver 不读取 role defaults 来给用户放权。
- `super_admin` 不会因为 role default 获得全局权限。
- 普通用户也不会因为 role default 自动获得权限。

### require_permission

`require_permission()` 在 `backend/app/api/deps.py`。

当前行为：

- 未登录仍由 `get_current_user()` 返回 401。
- owner 在 dependency 层直接通过。
- 非 owner 调用 `PermissionService.user_has_permission()`。
- 无权限返回 403，detail 为 `Missing permission: <permission_key>`。
- `super_admin` 没有特殊通道，不默认全局权限。

### /auth/me.permissions

`GET /auth/me` 在 `backend/app/api/routes/auth.py`。

当前响应保留身份字段：

- `id`
- `username`
- `role`
- `is_active`
- `last_login_at`

并追加：

- `permissions.is_owner_full_access`
- `permissions.permission_keys`
- `permissions.assignments`
- `permissions.scope_summary`

owner 返回：

```json
{
  "is_owner_full_access": true,
  "permission_keys": ["*"],
  "assignments": [],
  "scope_summary": []
}
```

非 owner 只返回 explicit assignment 生效后的权限。`role_default_permissions`
不进入 `/auth/me.permissions`。

### /permissions/me

`GET /permissions/me` 在 `backend/app/api/routes/permissions.py`。

当前登录用户可访问，用于查看自己的 effective permissions：

- owner 返回 wildcard full access。
- 非 owner 返回 enabled、未过期、registry enabled、scope 生效的 assignment。
- 响应包含 `user_id`、`role` 和 `permissions`。

grant/revoke 后，下一次请求 `/permissions/me` 应立即反映 DB 中的 assignment
变化，因为当前权限不是写入 token，而是每次从数据库解析。

### /permissions/registry

`GET /permissions/registry` 是只读权限目录 API。

当前访问规则：

- owner 可访问。
- 非 owner 必须拥有 `permissions.read`。
- 无 `permissions.read` 返回 403。

它可用于 C06C 前端权限选择，因为响应包含 permission key、module、category、
action、label、description、risk level、menu policy 和 enabled 状态。

它不能替代用户 assignment API，因为它只回答“有哪些权限点”，不回答“某个用户被授予了什么”。

### owner full access

owner 拥有全局全权限，不需要 assignment。

当前实现：

- `require_permission()` 中 owner 直接通过。
- `user_has_permission()` 中 owner 直接返回 true。
- `/auth/me` 和 `/permissions/me` 对 owner 返回
  `permission_keys=["*"]`。

C06 不允许通过给 owner 创建普通 assignment 来模拟 owner 权限。

### /users owner-only

当前 `/users` 仍 owner-only。答案必须是：是。

`backend/app/api/routes/users.py` 的所有用户管理 route 都依赖
`require_owner()`：

- `GET /users`
- `POST /users`
- `GET /users/roles`
- `GET /users/{user_id}`
- `PATCH /users/{user_id}`
- `POST /users/{user_id}/reset-password`
- `POST /users/{user_id}/disable`
- `POST /users/{user_id}/enable`

C06A 不改变这个边界。C06B/C06C 也不应顺手把 `/users` 改成
`users.manage`，除非后续独立任务明确批准。

### 前端 show_locked / hide_when_denied

前端权限 helper 在 `frontend/src/lib/permissions.ts`。

当前策略：

- business 模块无权限时 `show_locked`，入口可见但 locked，点击后进入无权提示。
- admin/system 模块无权限时 `hide_when_denied`，入口隐藏。
- `owner_only` 模块只认 `is_owner_full_access=true`。
- 前端权限只是 UX，不是安全边界。

### No Permission 组件

`frontend/src/components/no-permission-notice.tsx` 显示“无权访问此板块”。

`frontend/src/components/permission-route-guard.tsx` 在 console layout 中根据
当前 route 的权限决策拦截直接访问。

### User Management owner-only 可见

当前前端 User Management 入口仍仅 owner full access 可见。答案必须是：是。

证据：

- `frontend/src/lib/navigation.ts` 中 `/users` 配置了 `owner_only: true`。
- `canAccessModule()` 对 `owner_only` 只检查 `isOwnerFullAccess()`。
- `tests/frontend/permissions.test.mjs` 覆盖了普通 `users.manage` 非 owner 仍
  看不到 `/users`。
- `frontend/src/components/user-management-panel.tsx` 内部也用
  `isOwnerFullAccess(currentUser?.permissions)` 做 owner-only 挡板。

## 四、C06 后端 API 设计草案

C06B 第一版建议所有 assignment 管理 API 都 owner-only，只允许当前登录用户为
`role=owner`。不要在 C06B 第一版开放 `super_admin` scoped grant/revoke。

### GET /permissions/users/{user_id}/assignments

用途：owner 查看某个用户的权限 assignment 状态。

调用者：

- C06B 第一版只允许 owner。
- 非 owner 返回 403。
- `super_admin` 默认不能调用。

请求：

- path：`user_id`
- query 可选：
  - `include_disabled=true|false`，默认 true，方便审计历史状态。
  - `include_expired=true|false`，默认 true，方便解释为什么权限不生效。

响应建议：

```json
{
  "user_id": 12,
  "username": "managed_viewer",
  "role": "viewer",
  "is_owner_full_access": false,
  "assignments": [
    {
      "id": "uuid",
      "user_id": 12,
      "permission_key": "jobs.read",
      "scope_type": "global",
      "scope_key": "*",
      "granted_by_user_id": 1,
      "reason": "Needs job visibility.",
      "is_enabled": true,
      "expires_at": null,
      "created_at": "2026-06-11T00:00:00Z",
      "updated_at": "2026-06-11T00:00:00Z",
      "effective": true,
      "registry_risk_level": "low",
      "registry_label": "Read jobs"
    }
  ]
}
```

错误码：

- 401：未登录。
- 403：非 owner。
- 404：目标用户不存在。

安全校验：

- 只能读取 assignment，不做写入。
- 响应不返回 password/password_hash/token/secret。
- 如果目标用户是 owner，返回 `is_owner_full_access=true`、`assignments=[]`，并提示
  owner 不由 assignment 管理。

operation_logs：

- C06B 可以不记录普通 list 读取。
- 如果后续需要审计敏感读取，可以记录 `permission.assignment.list`，但第一版重点应放在
  grant/revoke/update 写操作。

### POST /permissions/users/{user_id}/assignments

用途：owner 给目标用户 grant permission。

调用者：

- C06B 第一版只允许 owner。
- 非 owner 返回 403。
- `super_admin` 默认不能 grant。

请求字段建议：

```json
{
  "permission_key": "jobs.read",
  "scope_type": "global",
  "scope_key": "*",
  "reason": "Needs access for daily job review.",
  "expires_at": null,
  "confirm_high_risk": false,
  "confirmation_phrase": null
}
```

响应字段：

- 返回创建或重新启用后的 assignment。
- 建议同时返回 `operation_id`，便于前端和审计联动。

operation_logs：

- action：`permission.assignment.grant`
- actor：当前 owner。
- target：目标用户或 assignment。
- result：`success` 或失败时 `failure`。
- details 包含 `actor_user_id`、`target_user_id`、`permission_key`、
  `scope_type`、`scope_key`、`before`、`after`、`reason`、`risk_level`、
  `requires_confirmation`、`confirmation_provided`。

错误码：

- 400：scope 不合法、reason 缺失、owner 自己不能作为目标、确认短语错误。
- 401：未登录。
- 403：非 owner。
- 404：目标用户不存在或 permission key 不存在。
- 409：active assignment 已存在且请求没有产生状态变化。
- 422：请求 schema 不合法。

安全校验：

- permission key 必须来自 enabled `permission_registry`。
- 不允许授予 wildcard `*`。
- 不允许给 owner 创建普通 assignment。
- 不允许非 owner 给自己授权。
- 不允许静默批量授予全部权限。
- `scope_type/scope_key` 必须通过 C05 现有 `validate_scope()`。
- `global` scope 必须使用 `scope_key="*"`。
- 高风险权限必须二次确认。
- 授予 `permissions.manage`、`users.manage`、`system.admin`、
  `settings.manage`、`production.release` 等高风险权限时必须带 reason 和确认。

是否允许操作 owner：

- 不允许给 owner grant 普通 assignment。
- owner 的 full access 来自 role，不来自 assignment。

是否允许授予 wildcard：

- 不允许。
- wildcard 只用于 owner effective response，不作为 assignment 存储。

是否允许授予 system/admin 权限：

- 可以授予 registry 中存在的 system/admin 权限，但必须高风险确认。
- C06B 第一版不允许通过这些权限反过来获得 grant/revoke API 调用权，grant/revoke 仍
  owner-only。

是否需要二次确认：

- 高风险权限必须需要。

### PATCH /permissions/users/{user_id}/assignments/{assignment_id}

用途：owner 更新 assignment 状态，例如修改 `expires_at`、`reason` 或重新启用。

调用者：

- C06B 第一版只允许 owner。

请求字段建议：

```json
{
  "is_enabled": true,
  "reason": "Extend access for project handoff.",
  "expires_at": "2026-07-11T00:00:00Z",
  "confirm_high_risk": true,
  "confirmation_phrase": "UPDATE permissions.manage FOR USER 12"
}
```

响应字段：

- 返回更新后的 assignment。
- 返回 `operation_id`。

operation_logs：

- action：`permission.assignment.update`
- details 包含完整 `before` / `after`。
- 如果是重新启用高风险 assignment，按高风险 grant 处理，必须二次确认。

错误码：

- 400：assignment 不属于 path 中的 `user_id`、非法 scope、缺少原因或确认。
- 401：未登录。
- 403：非 owner。
- 404：目标用户或 assignment 不存在。
- 409：试图更新 owner assignment 或造成不允许的状态。
- 422：请求 schema 不合法。

安全校验：

- assignment 必须属于 path 中的目标用户。
- 不允许更新 owner 的普通 assignment。
- 不允许把 permission key 更新成另一个 key。变更 permission key 应通过 revoke +
  grant，便于审计。
- 高风险重新启用必须二次确认。

### DELETE /permissions/users/{user_id}/assignments/{assignment_id}

用途：owner revoke assignment。删除语义应实现为软撤销，即设置
`is_enabled=false`，不硬删历史记录。

调用者：

- C06B 第一版只允许 owner。

请求字段：

- 建议要求 `reason`。
- 如果客户端或 proxy 不适合 DELETE body，C06B 可以选择更显式的
  `POST /permissions/users/{user_id}/assignments/{assignment_id}/revoke`，但内部语义仍是
  soft revoke。

响应字段：

- 返回 soft-revoked assignment。
- 返回 `operation_id`。

operation_logs：

- action：`permission.assignment.revoke`
- details 包含 `before` / `after`、`reason`、`risk_level`。

错误码：

- 400：assignment 不属于 path 用户、缺少 reason、目标为 owner。
- 401：未登录。
- 403：非 owner。
- 404：目标用户或 assignment 不存在。
- 409：assignment 已经 disabled 且请求没有产生状态变化。
- 422：请求 schema 不合法。

安全校验：

- 不硬删。
- 不允许 revoke owner 的 full access。
- revoke 高风险权限也必须记录明确原因。
- 当前 owner 自己不能通过 assignment revoke 把自己锁死，因为 owner full access 不依赖
  assignment。API 仍应阻止以 owner 为目标的 revoke。

## 五、权限授权规则

- owner 全局全权限，不需要 assignment。
- 不允许给 owner 创建普通 assignment 来模拟 owner 权限。
- 非 owner 只能通过 assignment 获权。
- `super_admin` 不自动拥有 grant 权限。答案必须是：不允许。
- `role_default_permissions` 不自动生效。答案必须是：不允许。
- C06B 第一版建议 owner-only grant/revoke，scope admin 授权延后或单独设计。
- 权限 key 必须来自 enabled `permission_registry`。
- 禁用或过期 assignment 不生效。
- registry disabled 的 permission 不生效。
- `global:*` assignment 可以匹配任意 scope 请求，但必须显式 grant。
- scoped assignment 不能反向提升为 global permission。
- grant/revoke 后 `/permissions/me` 应立即反映变化。
- 不允许用 role default、前端状态或本地缓存替代后端 effective permission 判断。

## 六、scope 策略

- C05 已预留 `global`、`company`、`factory`、`department`、`organization`、
  `module` 等 scope 概念。
- C06 第一版可以支持 `global` 和 `module` 的常规录入，并保存/展示现有
  `scope_type`、`scope_key` 字段。
- C06 第一版可以展示已有 `company`、`factory`、`department`、`organization`
  assignment 行，但不构造完整组织树。
- 完整公司/工厂/部门组织树和 scope admin 权限延后到 C18。
- 不允许在没有组织模型前伪造完整组织权限。
- 不允许把 `super_admin` 做成无组织模型的隐式全局管理员。
- 若 C06B 要接受非 global scope，必须只保存明确的 `scope_type/scope_key`，并在 UI 中清楚标识
  这是基础 scope 字段，不是完整组织管理。

## 七、高风险权限策略

高风险权限识别规则建议：

- registry `risk_level` 为 `high` 或 `critical`。
- permission key 命中显式高风险清单：
  - `users.manage`
  - `permissions.manage`
  - `settings.manage`
  - `system.settings.manage`
  - `system.admin`
  - `secrets.manage`
  - `release.manage`
  - `production.release`
  - `production.manage`
  - `billing.manage`
- permission `category` 为 `admin` 或 `system`，且 action 为 `manage`、`admin`、
  `release`。
- permission key 包含 `secret`、`billing`、`production`、`release`、`admin` 等高风险词。

要求：

- 高风险权限 grant 必须二次确认。
- 二次确认建议包括：
  - 非空 reason。
  - `confirm_high_risk=true`。
  - 输入包含 permission key 和 target user id 的确认短语，例如
    `GRANT permissions.manage TO USER 12`。
- revoke 高风险权限也要记录明确原因。
- 不允许 owner 误操作锁死自己。
- 不允许普通账号授予自己权限。
- 不允许静默批量授予全部权限。
- 不允许一次 grant wildcard。
- 不允许前端只靠隐藏按钮来防止高风险授权，后端必须强制校验确认字段。

## 八、operation_logs 设计

当前 `operation_logs` 表字段在 `backend/app/models/operation_log.py`：

- `operation_id`
- `actor_type`
- `actor_id`
- `action`
- `target_type`
- `target_id`
- `job_id`
- `result`
- `error_code`
- `request_id`
- `ip_address`
- `user_agent`
- `details`
- `created_at`

C06B 应沿用 `create_operation_log()`，并依赖它现有的敏感 key 清理逻辑。

每次 grant/revoke/update 必须记录：

- `actor_user_id`
- `target_user_id`
- `action`
- `permission_key`
- `scope_type`
- `scope_id` 或当前字段名 `scope_key`
- `before`
- `after`
- `reason`
- `request_id` 或 trace
- `created_at`
- `result`
- `risk_level`

建议映射：

- `actor_type="user"`
- `actor_id=str(owner.id)`
- `target_type="user_permission_assignment"`
- `target_id=str(assignment.id)`；如果 grant 失败且没有 assignment，可用
  `target_type="user"`、`target_id=str(target_user_id)`。
- `action` 使用：
  - `permission.assignment.grant`
  - `permission.assignment.revoke`
  - `permission.assignment.update`
- `result` 使用 `success` / `failure`。
- `error_code` 使用稳定短码，例如 `permission_not_found`、
  `high_risk_confirmation_required`、`owner_assignment_not_allowed`、
  `non_owner_grant_forbidden`。

`details` 建议结构：

```json
{
  "actor_user_id": 1,
  "target_user_id": 12,
  "permission_key": "permissions.manage",
  "scope_type": "global",
  "scope_key": "*",
  "before": {
    "is_enabled": false,
    "expires_at": null
  },
  "after": {
    "is_enabled": true,
    "expires_at": null
  },
  "reason": "Temporary admin coverage.",
  "risk_level": "critical",
  "requires_confirmation": true,
  "confirmation_provided": true
}
```

不要在 operation logs 中存储 password、token、secret、Authorization header 或真实 env 内容。

## 九、前端 UI 设计草案

推荐在 User Management 中增加“权限管理”抽屉、面板或用户详情页区域，而不是 C06C 第一版新增
独立 `/permissions` 页面。

理由：

- 权限管理天然围绕某个用户进行。
- `/users` 当前已经是 owner-only 后端安全边界。
- C06C 可以复用现有 User Management 用户列表和详情上下文。
- 独立 `/permissions` 页面更像全局权限治理中心，可以留到后续权限矩阵或组织 scope 阶段。

UI 边界：

- User Management 入口仍 owner-only。
- 权限列表来自 `GET /permissions/registry`。
- 用户当前授权来自新的 assignments API。
- 展示 `is_enabled`、`scope_type`、`scope_key`、`expires_at`、
  `granted_by_user_id`、`reason`、`created_at`、`updated_at` 和 effective 状态。
- 对 owner 目标用户显示 “Owner full access”，不显示可编辑 assignment 表单。
- grant 操作要支持搜索/筛选 permission key，按 module/category/risk 分组。
- revoke 操作要确认。
- 高风险 grant 显示二次确认。
- 高风险 revoke 要输入 reason。
- 没权限时管理入口隐藏。
- 前端仍不是安全边界，后端 401/403/409 才是最终授权结果。
- C06C 需要给 restricted backend proxy 精确放行新的 assignment API，不应变成通用代理。

## 十、测试计划

后端测试必须覆盖：

- owner 可 list/grant/revoke。
- non-owner 不能 list/grant/revoke。
- `super_admin` 默认不能 grant/revoke。
- grant 后 `/permissions/me` 生效。
- revoke 后 `/permissions/me` 移除权限。
- disabled assignment 不生效。
- expired assignment 不生效。
- permission key 不存在时拒绝。
- registry disabled permission 拒绝 grant 或不生效。
- high-risk permission 缺少确认时拒绝。
- high-risk permission 带确认时允许 owner grant。
- owner 不能被禁用或误撤核心 owner 能力。
- 不允许给 owner 创建普通 assignment。
- 不允许 grant wildcard。
- operation_logs 正确写入，包括 before/after、reason、risk_level、result。
- operation_logs 不写 password/token/secret/Authorization header。
- `/users` 后端仍 owner-only，除非后续独立任务改变。

前端测试必须覆盖：

- 普通用户看不到权限管理入口。
- owner 可看到用户权限管理入口。
- owner 可读取 registry 并展示 permission key、risk、category。
- owner 可读取用户 assignment 状态。
- grant 表单能提交普通权限。
- revoke 操作需要确认。
- 高风险确认正常。
- 缺少高风险确认时显示后端错误。
- owner 目标用户显示 full access 且不可编辑 assignment。
- 前端对 API 403/404/409/422 有明确错误提示。

联调测试必须覆盖：

- 同一个 non-owner token 在 grant 前 `/permissions/me` 无权限，grant 后下一次
  `/permissions/me` 立即出现权限。
- revoke 后下一次 `/permissions/me` 移除权限。
- `/auth/me.permissions` 与 `/permissions/me` 一致。

## 十一、C06 施工拆分

### C06B：后端 API 与测试

允许：

- 新增 owner-only assignment list/grant/revoke/update API。
- 补充 schemas/service/repository 必要逻辑。
- 写 operation_logs。
- 增加后端测试。
- 如确需调整 service helper 的 transaction 边界，可在 C06B 内完成并测试。

禁止：

- 不实现前端权限管理 UI。
- 不发布 staging/production。
- 不改变 `/users` owner-only。
- 不让 `super_admin` 默认 grant/revoke。
- 不让 `role_default_permissions` 自动生效。
- 不接真实业务。

### C06C：前端 UI 与测试

允许：

- 在 User Management 增加权限管理抽屉/面板或详情区域。
- 新增 frontend API client。
- 精确放行 frontend proxy assignment API。
- 增加前端测试和 verify 检查。

禁止：

- 不新增后端 API 行为。
- 不发布 staging/production。
- 不把前端当安全边界。
- 不接真实业务。

### C06D：staging 验收

允许：

- 按 OPS01 safe release 流程发布 staging backend/frontend。
- 在 staging 做 owner grant/revoke 联调。
- 如任务明确批准，可创建 staging-only 测试账号。
- 只在 staging 验证 non-owner 权限变化。

禁止：

- 不发布 production。
- 不操作 production 数据库或 production postgres 容器。
- 不读取真实 `.env.staging` / `.env.production`。
- 不打印 secret/token/password/Authorization header。
- 不接真实业务。

### C06E：production 发布

允许：

- C06D 验收通过后，按 OPS01 safe release 流程发布 production backend/frontend。
- 做 owner API/UI 只读和最小写入验收，具体写入范围必须在 C06E 任务中再次确认。

禁止：

- 不创建 production 测试账号，除非后续任务明确批准。
- 不直接操作 production postgres。
- 不读取真实 env。
- 不接真实业务。
- 不跳过 staging。

### C06F：封板

允许：

- 归档 C06B-E 完成范围、生产状态、安全边界、残余风险和后续任务。

禁止：

- 不新增功能。
- 不发布 staging/production。
- 不接真实业务。
- 不进入 P 系列。

如 C06B 发现高风险确认、operation_logs 或 frontend proxy 变更过大，可以额外拆出：

- C06B-1：后端只读 list API。
- C06B-2：grant/revoke/update 写 API 与 operation_logs。
- C06C-1：只读 UI。
- C06C-2：grant/revoke UI。

## 十二、风险与暂缓项

- scope admin 暂缓。
- 公司/工厂/部门组织结构暂缓。
- 业务模块真实权限接入暂缓。
- grant/revoke UI 不在 C06A 实现。
- grant/revoke API 不在 C06A 实现。
- 生产测试账号不创建。
- 不接 P 系列。
- 不接 WooCommerce、n8n 真实业务流、MinIO、Filebrowser 或产品页业务模块。
- 不改变 `/users` owner-only。
- 不让 `super_admin` 默认拥有全局权限。
- 不让 `role_default_permissions` 自动生效。
- 不用 wildcard assignment 模拟 owner。
- 不做静默批量全权限授权。
