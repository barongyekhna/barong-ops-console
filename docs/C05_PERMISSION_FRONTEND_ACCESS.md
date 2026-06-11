# C05 Permission Frontend Access

日期：2026-06-10 UTC

本文件记录 C05D：前端权限感知、导航显示策略、无权访问提示和基础路由保护。

C05D 只做前端用户体验层的权限感知。真正安全边界仍然是后端
`require_permission()`、`require_owner()` 和各 API 自己的 401/403 返回。前端隐藏菜单或显示
locked 状态不能替代后端授权。

## C05D 做了什么

- 前端 `GET /auth/me` client 现在读取并归一化 `permissions`。
- 新增前端权限类型和 helper：
  - `isOwnerFullAccess`
  - `hasPermission`
  - `canAccessModule`
  - navigation/route access state helpers
- `auth/me.permissions` 缺失或格式异常时安全降级为无权限，不让页面崩溃。
- 导航项新增权限元数据：
  - `module_key`
  - `required_permission`
  - `category`
  - `denied_behavior`
  - `owner_only`
- 新增无权访问提示组件，标题为“无权访问此板块”。
- 控制台 layout 新增轻量路由保护。用户直接访问无权页面时显示无权访问提示。
- User Management 前端入口和页面挡板继续只认 owner full access，不认普通
  `users.manage`。

## 前端权限不是安全边界

前端权限只改善体验：

- 有权限时显示并进入对应页面。
- 无权限时隐藏管理入口或显示 locked 状态。
- 直接访问无权页面时显示无权访问提示。

真正安全边界仍在后端：

- `/auth/me`、`/permissions/me` 只返回当前用户可见的权限合同。
- 后端 `require_permission()` 判断 explicit assignment、scope、enabled、expires。
- `/users` 当前仍使用 `require_owner()`。
- 后端 401/403 才是最终授权结果。

因此后续真实业务 API 不能只依赖前端 guard，必须在后端接入对应 permission dependency。

## 业务板块为什么 show_locked

业务板块采用 `show_locked`：

- 普通用户可以看到系统有哪些业务板块。
- 没有权限的业务板块显示锁定状态。
- 点击 locked 业务入口后进入无权访问提示页。
- guard 会在业务组件挂载前短路，避免无权限时触发现有业务/demo/test API 请求。

当前 business 类导航包括 Dashboard、Foundation Demo、n8n Test Bridge、Products、Jobs、
Artifacts、Reviews 等前端板块。C05D 没有接真实业务，也没有新增真实写入。

## 管理板块为什么 hide_when_denied

管理/系统板块采用 `hide_when_denied`：

- 管理能力风险更高，不需要向普通用户展示入口。
- 无权限用户的菜单更干净。
- 直接输入 URL 访问时仍会显示无权访问提示，不会触发后端写操作。

当前 admin/system 类导航包括 Modules、Agents、Workflows、Errors、Memory Events、Settings
和 User Management。

## `/users` 为什么仍 owner-only

C05C 后端仍明确保持 `/users` owner-only：

- `GET /users`
- `POST /users`
- `GET /users/roles`
- `GET /users/{user_id}`
- `PATCH /users/{user_id}`
- `POST /users/{user_id}/reset-password`
- `POST /users/{user_id}/disable`
- `POST /users/{user_id}/enable`

C05D 不把 `/users` 改成 `users.manage`。原因：

- 后端真实安全边界仍是 `require_owner()`。
- 如果前端提前让普通 `users.manage` 用户看到入口，会造成 UI 合同和后端授权不一致。
- `super_admin` 仍不默认全局权限。
- `role_default_permissions` 仍不自动生效。

所以 C05D 的 User Management 入口只在 `permissions.is_owner_full_access=true` 时可见。
普通非 owner 即使未来拥有 `users.manage` assignment，本阶段也看不到 `/users` 入口。

后续如需将 `/users` 改为 `users.manage`，必须作为 C06 或独立后端任务，先修改后端
dependency、测试和验收，再调整前端策略。

## C05D 没有做的事

- 没有新增权限 grant/revoke 管理页面。
- 没有新增 grant/revoke API。
- 没有把 `/users` 改成 `users.manage`。
- 没有接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser。
- 没有创建真实业务任务。
- 没有部署 staging。
- 没有发布 production。
- 没有读取真实 env 文件。
- 没有操作 production/staging 数据库或容器。
- 没有 git commit。

## 测试覆盖

C05D 新增 `tests/frontend/permissions.test.mjs`，使用 Node 内置 test runner，不引入新的
frontend test framework。覆盖：

- owner full access 可访问 business/admin 模块。
- 普通用户业务模块 visible + locked。
- 用户拥有 `jobs.read` 后 Jobs 不再 locked。
- 没权限直接访问受保护 route 会得到 denied decision。
- `auth/me.permissions` 缺失或异常时安全降级。
- `/users` 入口和访问仍只允许 owner full access，普通 `users.manage` 非 owner 仍不可见。

同时保留现有 frontend `typecheck`、`build`、`verify` 检查。

## C05E / C06 建议

- C05E 已完成 staging 联调验收，记录见
  `docs/C05_PERMISSION_STAGING_ACCEPTANCE.md`。
- C05E 验证了 staging frontend proxy 可以用临时 `viewer` non-owner 登录并读取
  `/auth/me.permissions`。
- C05E 验证了 non-owner 前端权限决策：User Management 不可见，admin/system
  入口无权限隐藏，business 入口无权限显示 locked，直接访问无权 route 显示
  “无权访问此板块”。
- C05E 同步验证后端 `/users` 对 non-owner 返回 403，确认前端只是 UX，后端
  `require_owner()` 仍是真正安全边界。
- C05E 未给临时 non-owner 授予 permission assignment，因此未验证“有 explicit
  business permission 的 non-owner 可访问业务模块”。这一步应留到未来权限分配功能或
  明确的测试 fixture。
- C05F 下一步是 production 发布归档；C05G 下一步是 C05 权限系统封板。
- C06 或独立后端任务：如果要开放 User Management，先把后端 `/users` 从
  `require_owner()` 正式改为合适的 permission dependency，再改前端。
- 后续权限管理阶段：设计 owner 可用的 assignment 管理 UI 和 grant/revoke API，但必须先做
  后端安全设计、审计记录和 staging-first 验收。
