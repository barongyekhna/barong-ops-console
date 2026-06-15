# C05 Permission System Plan

日期：2026-06-10 UTC

本文件记录 C05A：权限系统现状审计与设计方案。

C05A 只做审计、设计、数据模型建议、后续任务拆分和文档更新。不实现功能，不新增
migration，不部署，不修改 production/staging，不接真实业务。

C05B 已在此方案之后开始落地后端权限数据地基。C05B 的实现记录见
`docs/C05_PERMISSION_DATA_MODEL.md`。C05B 新增 `permission_registry`、
`user_permission_assignments`、`role_default_permissions` 三张表，以及后端 seed/upsert、
基础查询服务、owner 全局 resolver 和测试。C05B 仍不做前端权限 UI，不接 `/auth/me.permissions`
正式响应，不替换 `require_owner()`，不发布 production。

C05C 已在 C05B 之后接入后端权限 dependency 和当前用户权限返回。C05C 的实现记录见
`docs/C05_PERMISSION_BACKEND_ACCESS.md`。C05C 新增 `require_permission()`、`/auth/me.permissions`、
`GET /permissions/me` 和 `GET /permissions/registry`，并保持 `/users` 暂时 owner-only。
本阶段不做前端 UI，不做 grant/revoke API，不接真实业务，不发布 production。

C05D 已在 C05C 后接入前端权限感知。C05D 的实现记录见
`docs/C05_PERMISSION_FRONTEND_ACCESS.md`。C05D 读取 `/auth/me.permissions`，实现 business
板块 `show_locked`、admin/system 板块 `hide_when_denied`、无权访问提示和基础路由保护。
C05D 继续保持 `/users` owner-only，不把普通 `users.manage` 非 owner 放进 User Management。

C05E 已在 staging 完成权限系统联调验收。C05E 的验收记录见
`docs/C05_PERMISSION_STAGING_ACCEPTANCE.md`。C05E 使用 OPS01 safe release 发布 staging
backend/frontend，在 staging backend 容器内执行 Alembic `upgrade head`，并验证 owner
wildcard、non-owner 空权限、`/users` owner-only、`/auth/register` 404 和前端权限 UX。

C05F 已完成 production 安全发布归档。C05F 的验收记录见
`docs/C05_PERMISSION_PRODUCTION_RELEASE.md`。C05F 使用 OPS01 safe release 发布 production
backend/frontend，在 production backend 容器内执行 Alembic `upgrade head` 到
`c05b_permissions_001 (head)`，并验证 production owner `/auth/me`、`/permissions/me`、
`/permissions/registry`、`/users`、未登录 401 边界、`/auth/register` 404 和前端 owner
User Management 可见性。C05F 没有操作 production postgres 容器，没有直接连接 production
DB，没有读取真实 env，没有接真实业务。

C05G 已完成 C05 权限系统最终封板。C05G 的封板记录见
`docs/C05_PERMISSION_SYSTEM_SEAL.md`。C05G 只归档 C05A-F 完成范围、最终权限模型、
后端/前端状态、staging/production 验收摘要、安全边界和后续 C06/C18/业务模块接入规则；
不新增功能，不发布 staging/production，不接真实业务，不新增 grant/revoke API 或权限分配 UI。

## 一、为什么要做权限系统

C03 已经让 owner 可以创建内部子账户。C04 已经把标准 role 定清楚。

但是 role 只能说明“这个账号是什么身份”，不能直接说明“这个账号能做什么”。如果继续只靠
role，会出现两个问题：

- 权限会一刀切。例如所有 `operator` 都能做同一批动作，无法区分美工、SEO、客服、工厂主管。
- `super_admin` 很容易被误做成全局 owner。这样会绕过公司、工厂、组织范围，风险太高。

C05 要解决的是：每个用户到底能看什么、点什么、创建什么、审核什么、发布什么，以及这些权限在
哪个公司、工厂、部门、组织或模块范围内生效。

当前仍然不接真实业务模块。C05 是权限系统基础设施，不是新增业务板块。

## 二、C04 和 C05 的区别

C04 定义身份。

例如：

- `owner`
- `super_admin`
- `module_admin`
- `operator`
- `reviewer`
- `viewer`
- `bot_agent`

C05 定义权限。

例如：

- `users.manage`
- `permissions.manage`
- `jobs.create`
- `reviews.approve`
- `production.release`

大白话说：

- role 回答“这个人是什么类型的账号”。
- permission 回答“这个账号能执行哪个动作”。
- scope 回答“这个动作在哪个范围内能执行”。

C04 的结论不能被业务模块绕过。后续不能因为来了一个 SEO 模块，就新增 `seo_editor` 这种硬编码
系统 role。SEO 这类岗位应该通过 `role + job_title + department + module access +
permissions + scope` 表达。

## 三、本轮只读审计结论

本轮审计了以下文件：

- `backend/app/core/roles.py`
- `backend/app/api/deps.py`
- `backend/app/api/routes/users.py`
- `backend/app/schemas/user.py`
- `backend/app/services/user_management_service.py`
- `backend/app/services/auth_service.py`
- `backend/app/repositories/users.py`
- `backend/app/api/routes/auth.py`
- `backend/app/schemas/auth.py`
- `backend/app/models/user.py`
- `backend/app/models/registry.py`
- `frontend/src/components/user-management-panel.tsx`
- `frontend/src/lib/users-api.ts`
- `frontend/src/lib/auth.ts`
- `frontend/src/lib/navigation.ts`
- `docs/C03_OWNER_ACCOUNT_MANAGEMENT_SEAL.md`
- `docs/C04_ROLE_SYSTEM_SEAL.md`
- `tests/backend/test_user_management_api.py`
- `tests/backend/test_roles.py`

### 当前 owner 如何判断

当前 owner 判断在 `backend/app/core/roles.py`：

- `normalize_role(role)` 先做 trim 和 lower。
- `is_owner_role(role)` 判断标准化后的 role 是否等于 `owner`。

`backend/app/api/deps.py` 的 `require_owner()` 使用 `is_owner_role(user.role)` 做授权判断。

### 当前 require_owner 在哪里

`require_owner()` 在 `backend/app/api/deps.py`。

它依赖 `get_current_user()`。`get_current_user()` 做登录态校验：

- HttpOnly session cookie 存在。
- cookie 中的 session id 对应 server-side `auth_sessions` 记录。
- session 未过期且未被吊销。
- session 对应的用户存在。
- 用户 `is_active = true`。

然后 `require_owner()` 再判断当前用户是否为 owner。不是 owner 就返回 403。

### 当前 /users 如何限制 owner-only

`backend/app/api/routes/users.py` 的所有 `/users` 路由都依赖 `require_owner`：

- `GET /users`
- `POST /users`
- `GET /users/roles`
- `GET /users/{user_id}`
- `PATCH /users/{user_id}`
- `POST /users/{user_id}/reset-password`
- `POST /users/{user_id}/disable`
- `POST /users/{user_id}/enable`

所以当前 User Management 是真正后端 owner-only，不只是前端隐藏。

### 当前 /auth/me 返回什么

`GET /auth/me` 在 `backend/app/api/routes/auth.py`。

响应 schema 是 `AuthenticatedUser`，当前字段是：

- `id`
- `username`
- `role`
- `is_active`
- `last_login_at`

当前 `/auth/me` 不返回 permissions、scopes、module access、department 或 job title。

### 当前前端如何显示菜单

`frontend/src/lib/navigation.ts` 目前是静态菜单：

- Overview
- Registry
- Operations
- Governance
- System

`System` 里直接包含：

- `User Management`
- `Settings`

当前没有基于 permission 的菜单过滤。`UserManagementPanel` 内部再通过
`currentUser?.role === "owner"` 决定是否加载用户目录和显示 owner-only 页面内容。

### 当前是否有 permission 概念

当前没有“用户授权系统意义上的 permission”。

已有 `module_registry`、`agent_registry`、`workflow_registry` 里的 `permissions` JSON 字段，但它们是
F07/F10 foundation registry metadata，不是可执行的用户授权表。它们当前没有和用户、role、scope 或
API enforcement 绑定。

所以当前没有：

- `Permission Registry`
- `User Permission Assignment`
- `Role Default Permissions`
- `require_permission()`
- `/auth/me.permissions`

### 当前是否有 scope 概念

当前没有“权限系统意义上的 scope”。

已有少量 foundation 字段叫 `access_scope`，例如 memory/context 相关 metadata，但它们不是用户权限
生效范围，也没有和 company/factory/department/org/module 授权绑定。

所以当前没有：

- company scope
- factory scope
- department scope
- organization scope
- scoped super_admin
- scoped module_admin

### 当前是否需要 migration 才能实现 C05

如果只做 permission 常量和 `require_permission()` 的代码骨架，可以暂时不新增表。

但只靠代码常量不能完成 C05 的核心目标，因为 owner 或被授权的 super_admin 必须能给普通员工手动分配
权限，授权结果必须可查询、可审计、可撤销、可按 scope 生效。

所以长期实现 C05 需要新表。C05A 不新增 migration；C05B 应该 staging-first 新增 migration。

## 四、C05 权限模型

C05 推荐用四层模型：

1. Role：基础身份。
2. Permission：具体动作。
3. Scope：权限生效范围。
4. Assignment：谁被授予了哪个权限以及在哪个范围内生效。

### Permission Registry

Permission Registry 记录系统有哪些权限点。

它不是“某个用户有什么权限”，而是“系统承认哪些权限代码”。例如：

- `users.read`
- `users.manage`
- `jobs.create`
- `reviews.approve`
- `production.release`

推荐字段：

- `id`
- `code`
- `name`
- `description`
- `category`
- `module_id`
- `risk_level`
- `default_scope_type`
- `source`
- `manifest_version`
- `is_active`
- `created_at`
- `updated_at`

其中 `code` 必须稳定，不能随便改名。API、前端菜单、operation logs、测试都应该引用稳定的
permission code。

### User Permission Assignment

User Permission Assignment 记录某个用户被授予了哪些权限。

推荐字段：

- `id`
- `user_id`
- `permission_id`
- `scope_type`
- `scope_id`
- `granted_by_user_id`
- `grant_reason`
- `expires_at`
- `is_active`
- `created_at`
- `updated_at`

建议唯一性：

- 同一个 `user_id + permission_id + scope_type + scope_id` 不应该有多条 active 授权。

`scope_id` 在第一版可以为空，表示 global。未来接 company/factory/department/org 后再绑定具体 ID。

### Role Default Permissions

Role Default Permissions 是“角色推荐默认权限”，不是最终授权事实。

用途：

- 创建用户时给 owner 一个建议模板。
- 让系统知道 `viewer` 通常适合只读，`reviewer` 通常适合审核，`operator` 通常适合操作。
- 减少 owner 手动配置时的重复劳动。

边界：

- 不能替代手动授权。
- 不能让 `super_admin` 自动跨公司、跨工厂、跨组织拥有全部权限。
- 不能让 `module_admin` 在没有 module scope 的情况下变成所有模块管理员。

推荐字段：

- `id`
- `role`
- `permission_id`
- `default_scope_type`
- `enabled_by_default`
- `description`
- `created_at`
- `updated_at`

第一版也可以先用代码常量表达 role defaults，但真正的用户 assignment 仍建议落库。

### Permission Scope

Permission Scope 说明权限在哪个范围内生效。

建议预留 scope type：

- `global`
- `company`
- `factory`
- `department`
- `organization`
- `module`

C05 第一版可以默认 `global`，但数据模型和 `require_permission()` 参数必须预留 scope。

例如：

- `users.manage` + `global`：能管理全局用户。
- `users.manage` + `company:independent_site`：只能管理独立站公司范围内用户。
- `jobs.create` + `module:seo`：只能创建 SEO 模块任务。
- `reviews.approve` + `factory:factory_a`：只能审核某个工厂范围内事项。

C18 后续再深化公司、工厂、部门、组织实体表和层级关系。

### Module Permission Manifest

每个新模块必须自带 Permission Manifest。

Manifest 是模块接入系统时提交的权限清单。它回答：

- 这个模块有哪些页面可以访问。
- 这个模块有哪些动作需要授权。
- 哪些权限是只读。
- 哪些权限是创建/修改/审核/发布/设置类高风险动作。
- 每个权限默认支持哪些 scope。

SEO 模块示例：

```json
{
  "module_id": "seo",
  "permissions": [
    {
      "code": "seo.access",
      "name": "Access SEO module",
      "scope_types": ["global", "company", "department", "module"]
    },
    {
      "code": "seo.jobs.create",
      "name": "Create SEO jobs",
      "scope_types": ["global", "company", "department", "module"]
    },
    {
      "code": "seo.reports.read",
      "name": "Read SEO reports",
      "scope_types": ["global", "company", "department", "module"]
    },
    {
      "code": "seo.reviews.approve",
      "name": "Approve SEO reviews",
      "scope_types": ["global", "company", "department", "module"]
    },
    {
      "code": "seo.settings.manage",
      "name": "Manage SEO settings",
      "scope_types": ["global", "company", "department", "module"]
    }
  ]
}
```

模块注册时：

- Manifest 写入 Permission Registry。
- owner 或有授权管理权限的 super_admin 手动分配权限给员工。
- 前端菜单根据模块 category 和权限策略决定显示或隐藏。
- 后端 API 使用 `require_permission("seo.xxx", scope=...)` 做真实 enforcement。

C05A 不接真实 SEO 模块，这里只是设计样例。

## 五、Owner、Super Admin、普通员工的规则

### Owner

Owner 拥有所有公司、所有工厂、所有组织、所有板块、所有权限。

Owner 不需要逐条写入 User Permission Assignment。否则新增模块时还要给 owner 逐条补授权，容易漏。

推荐规则：

- `has_permission(user, permission, scope)` 看到 `role=owner` 直接返回 true。
- `/auth/me` 对 owner 返回 `is_owner_full_access=true`、`permission_keys=["*"]`。
- Owner 仍然不能被普通 `/users` 创建。
- Owner 的全局权限必须在文档、测试和后端 helper 里明确表达。

### Super Admin

Super Admin 不是全局 owner。

Super Admin 必须通过 assignment 获得权限，而且权限必须有 scope。

例如：

- 独立站公司 super_admin 可以管理独立站公司范围内用户和模块。
- 独立站公司 super_admin 不应该看到或管理工厂库存，除非 owner 另行授权。
- 某个工厂范围 super_admin 不应该自动获得 production release 或系统设置权限。

第一版即使先用 `global` scope，也不能默认让 `super_admin` 拥有全局全部权限。`super_admin` role 只能作为
高级管理身份，真正能做什么由 permission assignment 决定。

### 普通员工

普通员工包括 `viewer`、`operator`、`reviewer` 等。

他们通过 owner 或被授权的 super_admin 手动分配获得权限。

例如：

- 美工可以是 `role=operator`，`job_title=美工`，`department=设计部`，再获得图片系统相关权限。
- SEO 可以是 `role=operator`，再获得 SEO 模块任务创建和报告查看权限。
- 审核员可以是 `role=reviewer`，再获得某模块的 `reviews.approve`。

普通员工不能因为 role 名称本身自动获得跨模块高权限。

## 六、role / permission / scope / module access / job_title / department 的区别

`role` 是系统身份。它回答：账号属于哪类系统身份。

`permission` 是动作授权。它回答：账号能执行哪个动作。

`scope` 是生效范围。它回答：这个动作在哪个公司、工厂、部门、组织或模块内有效。

`module access` 是模块访问权。它回答：账号是否能进入某个业务模块或管理模块。

`job_title` 是公司职位。它回答：这个人在公司里是什么岗位，例如美工、SEO、客服、工厂主管。

`department` 是组织归属。它回答：这个人属于哪个部门。

这些概念不能混在一起。不能把每个岗位都做成 role，也不能把 module access 当成所有操作权限。

## 七、第一批基础权限点建议

用户管理：

- `users.read`
- `users.manage`

角色目录：

- `roles.read`

权限系统：

- `permissions.read`
- `permissions.manage`

任务：

- `jobs.read`
- `jobs.create`
- `jobs.manage`

审核：

- `reviews.read`
- `reviews.approve`

资产：

- `artifacts.read`

日志：

- `operation_logs.read`

模块：

- `modules.read`
- `modules.manage`

设置：

- `settings.read`
- `settings.manage`

发布：

- `production.release`

系统：

- `system.admin`

第一版建议从这些基础权限点开始，不要一次性做复杂业务权限矩阵。真实业务模块接入时再通过
Permission Manifest 增加模块自己的权限点。

## 八、菜单策略

前端菜单只是体验优化，后端必须真实 enforce 权限。

### 业务板块

业务板块菜单可以显示。

用户没有权限时，点击后进入无权页面或显示“无权查看此板块”。

原因：

- 员工可以知道公司有哪些业务板块。
- 没有授权时给出清晰提示，减少“页面坏了”的误解。
- 真正安全仍靠后端 `require_permission()`。

示例：

- 美工可以看到图片系统菜单。
- 如果美工没有被授权，点击后显示“无权查看此板块”。
- 如果后端 API 被直接调用，也必须返回 403。

### 企业管理板块

企业管理板块没有权限就不显示菜单。

包括：

- User Management
- 权限管理
- 系统设置
- 发布管理
- 高风险审计入口

原因：

- 这些入口本身就暴露管理面。
- 普通员工不需要看到。
- 入口隐藏可以降低误操作和社工风险。

示例：

- 美工不应该看到 User Management。
- 独立站公司 super_admin 可以看到独立站公司范围内管理入口。
- 独立站公司 super_admin 不应看到工厂库存管理，除非 owner 授权。

## 九、后端 enforcement 设计

C05 后端必须新增统一 `require_permission()` 设计。

建议形式：

```python
def require_permission(
    permission_key: str,
    scope_type: str = "global",
    scope_key: str = "*",
) -> Callable[..., User]:
    ...
```

行为建议：

- 未登录返回 401。
- owner 直接通过。
- 非 owner 查询 active User Permission Assignment。
- 权限不存在或未激活返回 403。
- scope 不匹配返回 403。
- 高风险权限写 operation log 或至少在调用方写审计。

`/users` 未来升级路径：

- 当前：`Depends(require_owner)`
- C05D 后：后端仍是 `Depends(require_owner)`，前端也只允许 owner full access 看到
  User Management。
- 未来如需改成 `Depends(require_permission("users.manage"))`，必须作为 C06 或独立后端任务，
  同步更新后端 dependency、测试、staging 验收和前端策略。
- `GET /users/roles` 如需改为 `roles.read` 或 `users.manage`，也必须放到后续后端任务处理。

`/auth/me` 未来返回建议：

- 当前 user 字段保持兼容。
- C05C 已新增 `permissions`。
- owner 返回 wildcard `permission_keys=["*"]`，不依赖 registry seed。
- 非 owner 只返回 enabled、未过期、scope 匹配的 explicit assignment。
- 可新增 `manageable_modules` 或 `module_access`，但不要把它当成后端唯一安全判断。

## 十、是否需要 migration

C05A 不新增 migration。

但是 C05B 建议新增 migration。原因是 C05 的核心目标包含“手动分配权限”，这必须落库。

建议 C05B 新增表：

- `permission_registry`
- `user_permission_assignments`
- `role_default_permissions`

可选后续表：

- `module_permission_manifests`
- `permission_assignment_audit`

是否可以先用代码常量不落库：

- 可以用于第一版 Permission Registry seed source。
- 可以用于单元测试和 `require_permission` 的常量引用。
- 不适合保存用户授权事实。
- 不适合 owner/super_admin 在 UI 上分配和撤销权限。
- 不适合模块 Manifest 动态注册后的长期治理。

更适合长期扩展的方案：

- 权限定义由代码常量和模块 Manifest 维护。
- 应用启动或管理命令把权限定义 seed/upsert 到 `permission_registry`。
- 用户授权事实放在 `user_permission_assignments`。
- role 推荐模板放在 `role_default_permissions`。
- scope 字段第一版先支持 `global`，但表结构直接预留 `company/factory/department/organization/module`。

C05B 风险：

- 新增表需要 migration，必须 staging-first。
- 需要保证 migration 可 downgrade 或至少有清晰 rollback plan。
- 需要保证 seed 幂等，不能重复插入权限。
- 需要保证 owner 不依赖逐条 assignment，避免新权限上线后 owner 反而没有权限。
- 需要保证 production 发布前已完成 staging 验收。

建议 C05B 流程：

1. 本地/测试 Docker 先跑 migration。
2. 只用 example/test 数据验证 seed 和权限查询。
3. staging migration。
4. staging owner 登录验收。
5. staging 非 owner 权限拒绝验收。
6. 通过 safe release 流程发布 backend/frontend。
7. production 发布前准备 rollback tag 和 smoke plan。

## 十一、C05 第一版应该做什么

C05 第一版应该做：

- 权限系统设计。
- 后端 permission constants。
- Permission Registry seed 方案。
- `require_permission()` 设计和实现。
- `/auth/me` 返回 permissions 的合同设计和实现。
- 前端读取 permissions 并按业务/管理策略显示导航。
- User Management 保持 owner-only；从 `require_owner` 升级到 `users.manage` 不属于
  C05D，留给 C06 或独立后端任务。
- 前端企业管理菜单按权限隐藏。
- 前端业务板块无权限提示。
- scope 字段和接口参数预留。
- owner 全局通过逻辑。
- super_admin scoped assignment 规则。

## 十二、C05 第一版暂不做什么

C05 暂不做：

- 完整多公司组织结构。
- 公司、工厂、部门管理页面。
- 复杂权限矩阵 UI。
- 密钥管理。
- 机器人 token scope。
- 生产发布审批流。
- 真实业务模块权限接入。
- n8n/P 系列/WooCommerce/MinIO/Filebrowser 权限接入。
- 真实业务任务创建。

这些留给 C06/C07/C18 或具体模块接入阶段。

## 十三、后续任务拆分

建议把 C05 拆成更安全的小步：

- C05B：后端权限目录、数据模型和 migration。新增 `permission_registry`、
  `user_permission_assignments`、`role_default_permissions`，完成 seed/upsert、owner 全局
  resolver、基础查询服务和测试。
- C05C：`require_permission()`、API dependency 接入、只读 permission registry API 和
  `/auth/me.permissions` 合同。C05C 已完成，新增 `/permissions/me` 和 `/permissions/registry`，
  且 `/users` 仍保持 owner-only。
- C05D：前端权限感知和访问提示。读取 `/auth/me.permissions`，业务板块可见但 locked，
  企业管理/系统板块无权限隐藏，直接访问无权页面显示无权访问；`/users` 继续 owner-only。
- C05E：staging 联调验收。验证 owner wildcard、无权限普通用户、`/auth/me.permissions`、
  `/permissions/me`、`/permissions/registry`、前端 locked/hidden 策略和 `/users`
  owner-only 行为。C05E 已完成，验收记录见
  `docs/C05_PERMISSION_STAGING_ACCEPTANCE.md`。
- C05F：production 发布归档。按 OPS01 safe release 流程发布 production
  backend/frontend，保留 rollback tag，并归档 production 只读验收结果。C05F 已完成，
  验收记录见 `docs/C05_PERMISSION_PRODUCTION_RELEASE.md`。
- C05G：权限系统封板。C05G 已完成，封板记录见
  `docs/C05_PERMISSION_SYSTEM_SEAL.md`。

如果 C05B 发现 migration 风险高，可以再拆：

- C05B-1：只加代码常量和只读 registry seed dry-run。
- C05B-2：只加 migration 和空表。
- C05B-3：seed 基础权限点。
- C05B-4：assignment 查询和测试。

## 十四、安全边界

C05A 没有做这些事：

- 没有读取、打印或修改真实 `.env.production`。
- 没有读取、打印或修改真实 `.env.staging`。
- 没有打印 secret、token、password 或 Authorization header。
- 没有创建 production/staging 真实用户。
- 没有操作 production/staging 数据库。
- 没有新增 migration。
- 没有修改 backend/app 业务代码。
- 没有修改 frontend/src 功能代码。
- 没有部署 staging。
- 没有发布 production。
- 没有执行 `docker-compose up/down`。
- 没有 stop、restart、rm、recreate production/staging 容器。
- 没有修改 Nginx 或证书。
- 没有执行 certbot。
- 没有接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser。
- 没有创建真实业务任务。
- 没有 git commit。

## 十五、C05A 结论

C05 应该采用“role 是身份、permission 是动作、scope 是范围、assignment 是授权事实”的模型。

Owner 是全局最高权限者，不需要逐条分配。

Super Admin 不是全局 owner，必须通过带 scope 的 assignment 获得管理权限。

普通员工通过 owner 或被授权的 super_admin 手动分配获得权限。

业务板块菜单可以显示，无权限点击后提示无权。企业管理板块没有权限就隐藏菜单。

新模块必须自带 Permission Manifest，注册时写入 Permission Registry，然后由 owner 或被授权的
super_admin 分配给员工，后端 API 使用 `require_permission("module.action")` enforce。

C05A 不实现。C05B-C05F 已完成。C05G 已完成权限系统封板。下一步是 C06 或 C18/业务模块
接入前置规划，不进入 P 系列，不接真实业务。
