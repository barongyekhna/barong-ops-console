# C06 Permission Backend Access

日期：2026-06-11 UTC

本文件记录 C06B：后端 owner-only 权限分配 API。

C06B 只实现后端 API、schema、service/repository、operation_logs 和测试。
本阶段不做前端权限分配 UI，不发布 staging，不发布 production，不接
WooCommerce、n8n 真实业务流、MinIO、Filebrowser、产品页或 P 系列。

## 一、C06B 做了什么

C06B 在 C05/C06A 的权限模型上新增 owner-only 用户 permission assignment
管理能力：

- owner 可以查看某个非 owner 用户的 explicit permission assignments。
- owner 可以给非 owner 用户 grant registry 中存在的 permission。
- owner 可以 update assignment 的 enabled、expires_at、scope_type、scope_key/
  scope_id 和 reason。
- owner 可以 revoke assignment；revoke 是软撤销，设置 `is_enabled=false`，
  不物理删除。
- grant/update/revoke 都写入现有 `operation_logs`。
- 高风险权限 grant 和高风险重新启用或 scope 变更必须二次确认。
- grant/revoke/update 后，`/permissions/me` 下一次请求会按数据库最新 assignment
  重新解析 effective permissions。

本阶段没有新增 migration。C05B 的 `user_permission_assignments` 字段已经足够：
`permission_key`、`scope_type`、`scope_key`、`is_enabled`、`expires_at`、
`granted_by_user_id`、`reason`、`created_at`、`updated_at`。

## 二、新增 API

所有 C06B 新增 API 都使用 `require_owner()`，不是
`require_permission("permissions.manage")`。

### `GET /permissions/users/{user_id}/assignments`

owner 查看某个用户的 explicit permission assignments。

响应包含：

- `user_id`
- `username`
- `role`
- `is_owner_full_access`
- `owner_full_access_note`
- `assignments`

assignment 响应包含：

- `id`
- `user_id`
- `permission_key`
- `permission_name`
- `description`
- `scope_type`
- `scope_id`
- `scope_key`
- `enabled`
- `is_enabled`
- `expires_at`
- `granted_by_user_id`
- `created_at`
- `updated_at`
- `reason`
- `risk_level`
- `high_risk`
- `effective`

如果 target user 是 owner，API 返回 `is_owner_full_access=true`、
`assignments=[]` 和说明文字。owner 的全局全权限来自 role，不通过普通
assignment 模拟。

响应不返回 `password_hash`、password、token、secret 或 Authorization header。

### `POST /permissions/users/{user_id}/assignments`

owner 给非 owner 用户 grant 一个 permission assignment。

请求字段：

- `permission_key`
- `scope_type`，默认 `global`
- `scope_id` 或 `scope_key`，默认 `*`
- `reason`
- `expires_at`
- `confirm_high_risk`
- `confirmation_text`

规则：

- `permission_key` 必须存在且 enabled 于 `permission_registry`。
- 不允许 grant wildcard `*`。
- 不允许给 owner 创建普通 assignment。
- 不允许重复创建同一 `user_id + permission_key + scope_type + scope_key`
  的 active assignment。
- 如果相同 assignment 已禁用或已过期，grant 会复用该行并重新启用，保留审计记录。
- 高风险权限必须提供非空 `reason`、`confirm_high_risk=true`，且
  `confirmation_text` 等于 `CONFIRM_HIGH_RISK_PERMISSION`。
- 成功后写 `permission.assignment.grant` operation log。

### `PATCH /permissions/users/{user_id}/assignments/{assignment_id}`

owner 更新 assignment。

允许字段：

- `enabled`，兼容 `is_enabled`
- `expires_at`
- `scope_type`
- `scope_id` 或 `scope_key`
- `reason`
- `confirm_high_risk`
- `confirmation_text`

禁止直接修改 `permission_key`。如果需要改变 permission key，必须先 revoke，再
grant 新 permission，保证审计链条清楚。

规则：

- `assignment_id` 必须属于 path 中的 `user_id`，否则返回 404。
- 不允许更新 owner 的普通 assignment。
- 高风险 assignment 重新生效或 scope 变更必须二次确认。
- 高风险敏感更新必须提供 reason。
- 成功后写 `permission.assignment.update` operation log，包含 before/after。

### `DELETE /permissions/users/{user_id}/assignments/{assignment_id}`

owner revoke assignment。

规则：

- `assignment_id` 必须属于 path 中的 `user_id`，否则返回 404。
- revoke 是软撤销：设置 `is_enabled=false`。
- 高风险权限 revoke 必须提供 reason。
- 成功后写 `permission.assignment.revoke` operation log，包含 before/after。

## 三、为什么 C06B 第一版 owner-only

C06B 第一版的目标是先建立安全、可审计、可测试的权限分配后端能力。授权本身是高风险管理动作，
如果在第一版直接开放给 `super_admin`、`module_admin` 或 scoped admin，会需要完整组织树、
scope admin 模型、委派边界和 UI 防误操作策略。当前这些内容尚未实现。

因此 C06B 全部 list/grant/update/revoke API 只允许 owner 调用。非 owner、viewer、
operator、reviewer、super_admin、module_admin 都不能调用。即使某个非 owner 拥有
`permissions.manage` assignment，也不能调用 C06B grant/revoke/update API。

## 四、super_admin 和 role defaults

`super_admin` 不默认拥有全局权限，也不默认拥有 grant/revoke 能力。

`role_default_permissions` 仍是角色建议模板，不是授权事实：

- resolver 不读取 role defaults。
- `/permissions/me` 不返回 role default 带来的权限。
- `super_admin` 不会因为 role default 获得 `permissions.manage`。
- 普通用户也不会因为 role default 自动获权。

非 owner 的 effective permissions 仍只来自 enabled、未过期、registry enabled 且
scope 匹配的 explicit `user_permission_assignments`。

## 五、high-risk 权限确认策略

C06B 优先使用 `permission_registry.risk_level`。`risk_level` 为 `high` 或
`critical` 时视为高风险。

此外，下列权限或类别也按高风险处理：

- `users.manage`
- `permissions.manage`
- `system.settings.manage`
- `settings.manage`
- `system.admin`
- `secrets.manage`
- `release.manage`
- `production.release`
- `production.manage`
- `billing.manage`
- permission key、module、category、action 命中 admin/system/release/secrets/
  production/billing 等高风险特征

高风险 grant 必须提供：

- 非空 `reason`
- `confirm_high_risk=true`
- `confirmation_text="CONFIRM_HIGH_RISK_PERMISSION"`

高风险 update 在重新生效或 scope 变更时也必须提供上述确认。高风险 revoke 必须提供
reason。

C06B 不允许静默批量授权全部权限，不允许 wildcard assignment，也不允许 owner 通过普通
assignment 机制模拟或破坏自己的 full access。

## 六、operation_logs 写入策略

C06B 沿用现有 `backend/app/repositories/operation_logs.py` 的
`create_operation_log()`，不另建日志系统。

成功 grant/update/revoke 写入：

- `action="permission.assignment.grant"`
- `action="permission.assignment.update"`
- `action="permission.assignment.revoke"`
- `actor_type="user"`
- `actor_id=str(owner.id)`
- `target_type="user_permission_assignment"`
- `target_id=str(assignment.id)`
- `result="success"`

`details` 包含：

- `actor_user_id`
- `target_user_id`
- `action`
- `permission_key`
- `assignment_id`
- `scope_type`
- `scope_id`
- `scope_key`
- `before`
- `after`
- `reason`
- `risk_level`
- `high_risk`
- `requires_confirmation`
- `confirmation_provided`
- `result`

已知校验失败也会写 `result="failure"` 和稳定 `error_code`，例如
`permission_not_found`、`high_risk_confirmation_required`、
`owner_assignment_not_allowed`、`duplicate_active_assignment`。

`create_operation_log()` 仍负责清理 password、token、secret、authorization 等敏感 key。

## 七、保持不变的安全边界

- `/users` 后端仍是 owner-only，继续使用 `require_owner()`。
- `/auth/register` 仍不存在，返回 404。
- `/permissions/me` 仍允许当前登录用户查看自己的 effective permissions。
- `/permissions/registry` 仍是 owner 或 `permissions.read` 可读。
- C06B 不新增公开注册接口。
- C06B 不新增公开权限接口。
- C06B 不修改 frontend UI。
- C06B 不发布 staging 或 production。
- C06B 不接真实业务。

## 八、测试覆盖

新增 `tests/backend/test_permission_assignments_api.py` 覆盖：

- owner 可以 list 用户 assignments。
- non-owner 不能 list/grant/update/revoke。
- `super_admin` 默认不能 list/grant/revoke。
- owner 可以 grant 普通 permission 给 non-owner。
- grant 后 `/permissions/me` 返回该 permission key。
- permission key 不存在、wildcard、owner target、重复 active assignment 被拒绝。
- high-risk 缺少 reason/confirmation 被拒绝。
- high-risk 带 reason 和确认可 grant。
- high-risk update/revoke 规则和 operation_logs。
- owner 可以 disable/enable、更新 expires_at 和 scope。
- disabled/expired assignment 不在 `/permissions/me` 生效。
- assignment_id 不属于 path user_id 时返回 404。
- revoke 后 assignment 软禁用，`/permissions/me` 移除该 permission key。
- grant/update/revoke 都写 operation_logs。
- API 响应不返回 password_hash。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。
- `role_default_permissions` 不自动生效。
- `super_admin` 不因 role defaults 获得 grant/revoke 能力。

## 九、下一步

- C06C：前端 User Management 内的用户权限管理 UI。
- C06D：staging 验收。
- C06E：production 发布归档。
- C06F：C06 权限管理封板。
