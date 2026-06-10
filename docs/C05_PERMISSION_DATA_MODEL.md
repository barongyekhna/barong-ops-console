# C05 Permission Data Model

日期：2026-06-10 UTC

本文件记录 C05B：后端权限数据模型与 migration。

C05B 只实现权限系统的数据地基：权限目录、用户授权事实、角色默认建议、基础 seed/upsert、
权限查询服务、owner 全局 resolver 和测试。C05B 不接前端权限 UI，不替换现有
`require_owner()`，不把 `/auth/me` 正式扩展为 permissions 响应，也不发布 production。

## 本轮新增表

### permission_registry

`permission_registry` 是系统权限目录。它回答“系统承认哪些权限点”。

核心字段：

- `id`：UUID 主键。
- `permission_key`：稳定权限代码，唯一，例如 `users.manage`。
- `module_key`：权限所属模块，例如 `users`、`jobs`、`system`。
- `category`：权限类别，例如 `admin`、`business`、`system`。
- `action`：动作，例如 `read`、`create`、`manage`、`approve`、`release`。
- `label` / `description`：给管理端和审计使用的可读说明。
- `risk_level`：`low`、`medium`、`high`、`critical`。
- `menu_policy`：`show_locked` 或 `hide_when_denied`。
- `is_system`：系统内置权限标记。
- `is_enabled`：目录项是否启用。
- `created_at` / `updated_at`：审计时间。

`permission_registry` 不是用户已经拥有的权限。它只是权限目录。

### user_permission_assignments

`user_permission_assignments` 是某个用户被授予某个权限的事实。它回答“谁在什么范围内被授予了哪个权限”。

核心字段：

- `id`：UUID 主键。
- `user_id`：指向现有 `users.id`。因为当前 `users.id` 是 `BigInteger`，这里沿用
  `BigInteger` 外键，而不是单独改成 UUID。
- `permission_key`：指向 `permission_registry.permission_key`。
- `scope_type`：`global`、`company`、`factory`、`department`、`organization`、`module`。
- `scope_key`：scope 内的稳定 key；`global` 必须使用 `*`。
- `granted_by_user_id`：授权人，指向 `users.id`，允许为空。
- `reason`：授权原因。
- `is_enabled`：是否启用。撤销当前通过禁用实现，不硬删。
- `expires_at`：可选过期时间，过期后不生效。
- `created_at` / `updated_at`：审计时间。

唯一约束：

- `user_id + permission_key + scope_type + scope_key`

### role_default_permissions

`role_default_permissions` 是角色建议默认权限。它回答“某个 role 通常建议有哪些权限模板”。

它不是实际授权事实。C05B 的 resolver 不会因为这里有记录就给用户放权。

核心字段：

- `id`：UUID 主键。
- `role`：角色名，例如 `viewer`、`operator`、`reviewer`、`super_admin`。
- `permission_key`：指向 `permission_registry.permission_key`。
- `scope_type` / `scope_key`：建议默认 scope。
- `is_enabled`：模板项是否启用。
- `created_at` / `updated_at`：审计时间。

唯一约束：

- `role + permission_key + scope_type + scope_key`

## Owner 全局权限

Owner 是全局最高权限者。C05B 的服务层规则是：

- `user.role == owner` 时，`user_has_permission()` 直接返回 true。
- Owner 不需要在 `user_permission_assignments` 中逐条写 assignment。
- Owner 不受 `scope_type` 或 `scope_key` 限制。
- `resolve_effective_permissions()` 对 owner 返回 `is_owner_full_access=true`，并列出当前启用的
  registry 权限点作为可读目录。

这样新模块注册新权限后，不需要给 owner 补写授权行，也不会因为漏 seed assignment 导致 owner
突然没有权限。

## Super Admin 规则

`super_admin` 不是全局 owner。C05B 保证：

- 没有 assignment 的 `super_admin` 不拥有 `users.manage`、`permissions.manage` 或其他权限。
- `super_admin` 只有在 `user_permission_assignments` 存在 enabled 且未过期的授权时才获权。
- 非 global scope 的授权不会被误判成 global 授权。

C05B 允许 `global` assignment 存在，因为数据模型需要保留全局授权能力；但这必须是显式授权，不是
`super_admin` role 默认获得。

## Registry 和 Assignment 的区别

`permission_registry` 是系统权限目录：

- 记录系统有哪些权限点。
- 来自代码 seed 或未来模块 Permission Manifest。
- 不表示任何用户已经拥有权限。

`user_permission_assignments` 是用户授权事实：

- 记录某个用户被授予哪个权限。
- 带 scope、授权人、原因、禁用状态和过期时间。
- 是非 owner 用户权限判断的事实来源。

## Role Defaults 当前状态

`role_default_permissions` 当前只作为“建议默认权限模板”落库。

C05B 不启用自动放权：

- resolver 不读取 role defaults 来授予权限。
- `super_admin` 不会因为 role default 获得全局权限。
- 普通员工仍必须有 explicit assignment。

后续 C05C/C05D 可以在创建用户或权限管理 UI 中把 role defaults 当成初始化建议，但必须由 owner 或被授权的
scoped super_admin 明确确认。

## Scope 第一版预留

C05B 预留以下 scope：

- `global`
- `company`
- `factory`
- `department`
- `organization`
- `module`

当前还没有公司、工厂、部门、组织实体表。C05B 只保存 `scope_type` 和 `scope_key`，并实现基础匹配：

- owner 忽略 scope，直接通过。
- 非 owner 的 exact scope assignment 生效。
- 同 scope 下 `scope_key="*"` 可作为该 scope 类型的通配。
- `global:*` 是显式全局 assignment，可以覆盖 scoped 请求。
- scoped assignment 不会反向变成 global permission。

## 第一批 seed 权限

C05B 在 `backend/app/core/permissions.py` 定义第一批基础权限点：

- `users.read`
- `users.manage`
- `roles.read`
- `permissions.read`
- `permissions.manage`
- `jobs.read`
- `jobs.create`
- `jobs.manage`
- `reviews.read`
- `reviews.approve`
- `artifacts.read`
- `operation_logs.read`
- `modules.read`
- `modules.manage`
- `settings.read`
- `settings.manage`
- `production.release`
- `system.admin`

这些常量是 registry seed source，不是任何用户的实际授权。

## C05C 后端接入

C05C 已在 C05B 数据模型之上接入后端权限判断和只读权限查询：

- 新增 `require_permission(permission_key, scope_type="global", scope_key="*")`。
- Owner 在 dependency 层直接通过，不查询 assignment，不受 scope 限制。
- 非 owner 依赖 enabled、未过期、registry enabled、scope 匹配的 `user_permission_assignments`。
- `super_admin` 不默认全局全权限。
- `/auth/me` 追加 `permissions`，owner 返回 `permission_keys=["*"]`。
- 新增 `GET /permissions/me` 查看当前用户 effective permissions。
- 新增 `GET /permissions/registry` 查看 enabled registry，非 owner 需要 `permissions.read`。

详细合同见 `docs/C05_PERMISSION_BACKEND_ACCESS.md`。

C05C 仍不把 User Management 从 `require_owner` 升级为 `users.manage`。这一步留给 C05D，并需要同步处理前端菜单权限。

## 安全边界

C05B 不做这些事：

- 不读取或修改真实 `.env.production` / `.env.staging`。
- 不创建 production/staging 真实用户。
- 不操作 production/staging 数据库真实数据。
- 不部署 staging 或 production。
- 不替换现有 `/users` owner-only 行为。
- 不新增前端权限 UI。
- 不接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser 或真实业务任务。
