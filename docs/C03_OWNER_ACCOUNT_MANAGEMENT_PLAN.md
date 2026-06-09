# C03 Owner Account Management Plan

## 1. C03 为什么重要

C01 已经把正式服上线封板，C02 已经把 production 和 staging 隔离封板。现在系统有一个可登录的 `owner`，但只有一个 owner 账号会带来几个问题：

- 所有人都用同一个账号时，操作日志只能看到 owner，不能区分具体操作者。
- 后续要做审核、任务执行、只读查看、运营操作时，没有账号边界。
- C04/C05 要做角色和权限系统，必须先有稳定的用户生命周期。
- staging 要先验证创建账号、停用账号、重置密码这些基础动作，不能直接在 production 上试。

C03 的目标是补上“账号管理基础”。它不是完整 RBAC，也不是业务权限系统。C03 做完后，owner 能创建和管理子账户，后续 C04/C05 再把这些账号接入正式角色和权限矩阵。

## 2. C03A 本阶段边界

C03A 只做审计、风险分析、设计方案和任务拆分：

- 只读查看现有 users、auth、migration、schema、service、repository、test 和 frontend auth 代码。
- 运行只读安全检查脚本和 foundation acceptance。
- 新增本设计文档。
- 小范围更新 README 和 CHANGELOG。

C03A 不做这些事：

- 不实现用户管理 API。
- 不新增数据库 migration。
- 不创建真实用户或测试用户。
- 不读取真实 `.env.production` 或 `.env.staging` 内容。
- 不修改 production/staging 容器。
- 不修改 Nginx、证书或真实业务系统。
- 不接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser。

## 2.1. C03B 后端实现状态

C03B 已完成后端 owner-only 用户管理 API，仍然不做前端页面、不部署
staging、不发布 production、不创建真实用户、不接真实业务。

C03B 实现内容：

- 新增 `/users` 后端 API，全部使用 `require_owner`。
- 拆分 `get_current_user` 和 `require_owner`。
- `/auth/login` 允许 active 用户登录，不再限制只能 `owner` 登录。
- `/auth/me` 允许任何已登录且 active 的用户访问。
- inactive 用户不能登录，也不能继续通过 token 访问 protected API。
- owner 可创建 `viewer`、`operator`、`reviewer` 子账户。
- 创建、更新、停用、启用、重置密码都写 `operation_logs`。
- API response 不返回 `password_hash`。
- 继续没有 `/auth/register`，也没有公开注册页面。
- 未新增 migration，继续使用现有 `users` 表字段。

C03B 仍不做：

- 前端用户管理页面。
- 完整 RBAC 或模块级权限矩阵。
- email、邀请、找回密码、首次登录强制改密。
- session table 或 token revocation。
- staging/production 发布。
- 真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser 或真实业务任务。

## 3. 审计过的主要文件

后端用户和认证：

- `backend/app/models/user.py`
- `backend/app/repositories/users.py`
- `backend/app/schemas/auth.py`
- `backend/app/services/auth_service.py`
- `backend/app/api/routes/auth.py`
- `backend/app/api/deps.py`
- `backend/app/core/security.py`
- `backend/app/cli/bootstrap_owner.py`
- `backend/app/models/operation_log.py`
- `backend/app/repositories/operation_logs.py`
- `backend/alembic/versions/20260608_01_create_core_foundation_tables.py`

测试：

- `tests/backend/test_auth_api.py`
- `tests/backend/test_owner_bootstrap.py`
- `tests/backend/test_security.py`
- `tests/backend/test_schema_models.py`
- 其他 foundation/API 测试通过 acceptance 间接覆盖。

前端：

- `frontend/src/app/login/page.tsx`
- `frontend/src/components/login-form.tsx`
- `frontend/src/components/auth-provider.tsx`
- `frontend/src/components/auth-guard.tsx`
- `frontend/src/components/console-shell.tsx`
- `frontend/src/lib/auth.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/navigation.ts`
- `frontend/src/app/(console)/layout.tsx`
- `frontend/src/app/(console)/settings/page.tsx`
- `frontend/src/app/api/backend/[...path]/route.ts`

## 4. 现有 users 表和模型审计结果

当前 `User` 模型对应 `users` 表，已有字段：

- `id`：BigInteger 主键，自增。
- `username`：字符串，非空，唯一。
- `password_hash`：字符串，非空。
- `role`：字符串，非空。当前 owner 用字符串 `"owner"` 表示。
- `is_active`：布尔值，非空，数据库默认 `false`。
- `last_login_at`：带时区时间，可为空。
- `created_at`：由 `TimestampMixin` 提供，非空，数据库默认当前时间。
- `updated_at`：由 `TimestampMixin` 提供，非空，数据库默认当前时间，模型层有 `onupdate`。

当前不存在的字段：

- 没有 `email`。
- 没有 `disabled_at`、`disabled_by`、`disabled_reason`。
- 没有 `created_by`。
- 没有 `password_changed_at` 或 `password_reset_required`。
- 没有数据库层 role enum 或 check constraint。

当前唯一约束：

- migration 里已有 `uq_users_username`，保证 `username` 唯一。
- 没有 `email`，所以也没有 email 唯一约束。

当前 migration 情况：

- `f07_core_001` 已包含 `users` 表。
- `users` 表创建字段与模型一致。
- migration 没有 seed 用户。
- owner 通过受控 bootstrap 逻辑创建，不是 migration seed。

当前是否支持停用：

- 支持基础停用状态：`is_active = false`。
- 当前认证逻辑会拒绝 inactive 用户登录，也会拒绝 inactive 用户通过 token 访问受保护 API。
- 但没有记录停用原因、停用时间和停用操作者的专用字段。C03 可以先用 `operation_logs` 留痕。

## 5. 现有认证流程审计结果

### 登录

`POST /auth/login` 调用 `auth_service.login`：

- 按 `username` 查询用户。
- 使用 Argon2id 校验密码。
- 用户不存在时也会 hash 输入密码，用来减少明显的时序差异。
- 登录成功必须同时满足：用户存在、密码正确、`is_active = true`、`role == "owner"`。
- 登录失败统一返回 401，避免暴露用户是否存在。
- 登录成功会更新 `last_login_at`。
- 登录成功和失败都会写 `operation_logs`。
- 响应返回 `access_token`、`token_type` 和最低必要用户信息，不返回 `password_hash`。

### JWT token

当前 token 由 `create_access_token` 生成，包含：

- `sub`：用户 id 字符串。
- `role`：用户角色字符串。
- `iat`：签发时间。
- `exp`：过期时间。

签名算法是 `HS256`。`AUTH_TOKEN_SECRET` 必须存在且至少 32 字节，否则认证服务不可用。

### 当前用户

`GET /auth/me` 依赖 `get_current_user`：

- 从 Bearer token 解码 `sub` 和 `role`。
- 按 `sub` 查用户。
- 要求用户存在、`is_active = true`、用户角色仍是 `"owner"`、token 里的 role 与数据库 role 一致。
- 返回 `id`、`username`、`role`、`is_active`、`last_login_at`，不返回密码哈希。

### 退出

`POST /auth/logout` 当前是 stateless logout：

- 后端写 `auth.logout` operation log。
- 前端随后清除本地 token。
- 当前没有 session table 或 token revocation 表。

已知限制：

- 用户主动 logout 后，旧 JWT 在过期前从密码学角度仍是有效 token。
- 只要 API 继续查数据库状态，停用用户后旧 token 会被 `is_active` 拦住。
- 但“单个 token 立即吊销”目前做不到。未来需要 token revocation 或 session table，不列入 C03 必做。

### owner bootstrap

`bootstrap_owner` 当前逻辑：

- 校验 owner username 必填且长度合法。
- 校验 owner password 必填且至少 12 位。
- PostgreSQL 下使用 advisory lock，避免并发创建多个 owner。
- 已有 owner 时跳过并写 `auth.owner_bootstrap` skipped 日志。
- username 冲突时失败并写日志。
- 创建 owner 前必须 hash 密码。
- 创建的 owner 为 `role = "owner"` 且 `is_active = true`。
- 成功、跳过、失败都会写 operation log。

### operation_logs

当前 operation log 模型已有：

- actor、action、target、result、error_code、request_id、ip、user_agent、details、created_at。
- details 会过滤 key 中包含 `password`、`password_hash`、`token`、`secret`、`authorization`、`api_key` 等敏感标记的字段。

认证相关日志当前已覆盖：

- `auth.login`
- `auth.logout`
- `auth.owner_bootstrap`

### 公开注册

当前没有公开注册接口：

- `main.py` 只挂载 `/auth/login`、`/auth/me`、`/auth/logout`。
- 测试明确断言 `POST /auth/register` 返回 404。
- 前端没有 `/register` 页面。
- 前端 README 也明确没有 `/register`。

## 6. 现有前端登录与 auth guard 审计结果

### 登录页

`/login` 是公开页面，使用 `PublicOnly` 包裹。登录表单提交：

- `username.trim()`
- `password`
- 调用 `/auth/login`
- 成功后跳转 `/dashboard`
- 失败显示统一错误文案

没有注册入口。

### AuthProvider

`AuthProvider` 负责：

- 从 `localStorage` 读取 token。
- 调 `/auth/me` 刷新当前用户。
- 登录成功后把 token 写入 `localStorage`。
- 401 时清除本地 session。
- logout 时先调用 `/auth/logout`，然后清本地 session。
- 监听跨标签页 storage 变化。

当前 token 存储 key 是 `barong_ops_access_token`。

### AuthGuard 和 protected layout

`frontend/src/app/(console)/layout.tsx` 使用 `AuthGuard` 包住 `ConsoleShell`：

- 未认证跳转 `/login`。
- checking 状态显示加载。
- `/auth/me` 错误时显示 retry。

这只是前端体验保护，真正的认证和授权仍由后端 API 处理。

### ConsoleShell 和 logout

左上角显示 Barong Ops Console，右上角显示当前用户 `username` 和 `role`。Logout 按钮调用 auth provider 的 logout。

### 当前用户管理入口

当前没有用户管理入口：

- 左侧导航 System 下面只有 `/settings`。
- `/settings` 现在是空状态。
- 没有 `/users` 页面。
- 前端 API proxy allowlist 当前不允许 `/users`。
- 前端 API route 当前只有 GET 和 POST handler，没有 PATCH handler。

结论：C03C 可以新增独立 `/users` 页面，并在 System 菜单中增加 User Management。`/settings` 可以保留为空状态，或者后续放系统配置；不建议把完整用户列表塞进空状态 settings 页面里。

## 7. 当前 users/auth 系统总体结论

当前系统适合“只有 owner 登录”的 F08-F13 空地基阶段，但不支持 C03 子账户使用：

- 数据库已经有 C03 最小账号管理所需的基础字段。
- 密码哈希、登录审计、logout 审计、owner bootstrap 审计已经存在。
- 公开注册已经被禁止并有测试覆盖。
- `is_active` 已经可以作为停用/启用基础状态。
- C03A 时后端认证硬性要求 `role == "owner"`，所以 viewer/operator 这类子账户即使被创建，也无法登录。
- C03B 已把“当前登录用户”和“必须是 owner”的授权逻辑拆开：`get_current_user` 只做登录态校验，`require_owner` 做 owner 授权。

C03B 实际改法：

- `get_current_user` 改为只校验 token 有效、用户存在、`is_active = true`、token role 与数据库 role 一致。
- 新增 `require_owner` dependency。
- 用户管理 API 全部使用 `require_owner`。
- `/auth/login` 允许 active 用户登录，C03B 创建用户时只允许
  `viewer`、`operator`、`reviewer` 这些基础子账户角色。
- 完整 RBAC 和其他模块的细粒度角色权限不在 C03B 内实现。

## 8. C03 功能边界设计

C03 只做“账号管理基础”，不做完整 RBAC。

C03 应该支持：

- owner 查看用户列表。
- owner 创建子账户。
- owner 查看某个用户详情。
- owner 停用子账户。
- owner 启用子账户。
- owner 重置子账户密码。
- owner 不能删除自己。
- owner 不能停用自己。
- 子账户不能创建 owner。
- 子账户不能调用用户管理 API。
- 禁止公开注册接口和公开注册页面。
- 所有账号管理写操作都写 `operation_logs`。
- 默认新用户 role 可以先是 `viewer` 或 `operator` 这类基础枚举。
- C04/C05 再做完整角色权限系统。

建议 C03 暂时不做物理删除。账号停用比删除更利于审计。

## 9. C03 明确不做什么

C03 暂不做：

- 完整模块权限矩阵。
- 复杂 RBAC。
- 部门、组织架构、岗位层级。
- 聊天。
- 机器人账号。
- 外部 OAuth。
- 邮件邀请。
- 密码找回邮件。
- 用户头像、个人资料中心。
- SSO。
- API key 管理。
- session table。
- token revocation。
- 真实业务任务、真实订单、真实产品、真实工作流。
- 连接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser。

这些内容留给 C04/C05/C18/C19 或后续单独任务。

## 10. 安全规则设计

C03 必须遵守这些安全规则：

- 只有 owner 可以创建子账户。
- 只有 owner 可以查看用户列表和用户详情。
- 只有 owner 可以启用、停用、重置子账户密码。
- 后续 super admin 能否创建账号，等 C04 之后结合角色模型再决定。C03 不引入 super admin。
- 禁止公开注册 API。
- 禁止公开注册页面。
- 创建用户时后端必须 hash 密码，不能保存明文。
- 重置密码时后端必须 hash 新密码，不能保存明文。
- 后端 response 不能包含 `password_hash`。
- API 不能打印密码。
- 日志不能打印 token、密码、密码哈希或真实密钥。
- operation log 的 details 只能放最低必要信息，比如目标用户 id、角色、启用/停用状态变化，不能放密码。
- 重置密码必须写 `operation_logs`。
- 停用用户必须写 `operation_logs`。
- 启用用户必须写 `operation_logs`。
- 停用用户后，该用户不能再登录。
- 停用用户后，该用户已有 token 访问受保护 API 时也必须被拒绝。
- owner 不能停用自己。
- owner 不能删除自己。
- C03 不提供删除账号接口。
- 子账户不能创建 owner。
- 子账户不能修改自己的 role。
- 子账户不能重置别人的密码。

当前 JWT stateless logout 的限制必须写入风险：

- 当前 logout 主要是后端审计加前端清本地 token。
- 没有 token revocation，所以不能单独吊销某一个已签发 token。
- 用户停用可以通过数据库状态拦住后续 API 访问。
- 未来如果需要强制踢下线、设备管理、单 token 撤销，需要 session table 或 token revocation 表。
- 这不是 C03 必做，但必须作为已知风险保留。

## 11. C03B 后端 API 实现

所有 `/users` API 都需要 owner 身份。不要开放 `/auth/register`，也不要让未登录用户创建账号。

### 数据返回形状

用户响应建议只包含：

- `id`
- `username`
- `role`
- `is_active`
- `last_login_at`
- `created_at`
- `updated_at`

不返回：

- `password_hash`
- 明文密码
- token
- secret

如果 C03 不新增 migration，则不要在响应中设计 `email`。当前数据库没有 email 字段。

### `GET /users`

用途：owner 查看用户列表。

C03B 参数：

- `limit`：默认 50，范围 1-100。
- `offset`：默认 0。

C03B 暂不做 role、is_active、q 过滤；后续可以在 C03C/C04 结合前端需求再加。

响应延续现有 `ListResponse` 风格：

- `items`
- `count`
- `limit`
- `offset`

### `POST /users`

用途：owner 创建子账户。

C03B 请求：

```json
{
  "username": "operator_01",
  "password": "temporary-password",
  "role": "operator",
  "is_active": true
}
```

规则：

- `username` 必填，最大 255。
- `password` 必填，建议最少 12 位，最大长度沿用认证层限制。
- `role` 只允许基础子账户角色：`viewer`、`operator`、`reviewer`。
- C03 不允许通过这个接口创建 `owner`。
- 后端 hash 密码后落库。
- username 冲突返回 409。
- 成功写 `operation_logs`，action 建议为 `user.create`。

### `GET /users/{user_id}`

用途：owner 查看用户详情。

规则：

- 只能 owner 调用。
- 找不到返回 404。
- 不返回 `password_hash`。

### `PATCH /users/{user_id}`

用途：owner 更新基础账号字段。

C03B 只允许很小范围：

- 更新 `role`，但不能把子账户改成 `owner`。
- 可选更新 `is_active`，但更推荐启用/停用走专用 endpoint。

不建议 C03 更新 username，除非有明确需求。username 是登录标识，改名会增加审计和沟通成本。

规则：

- 找不到返回 404。
- 重复 username 返回 409，如果 C03 最终允许改 username。
- 非法 role 返回 422。
- 尝试停用自己返回 400 或 422。
- 成功写 `operation_logs`，action 建议为 `user.update`。

### `POST /users/{user_id}/reset-password`

用途：owner 重置子账户密码。

建议请求：

```json
{
  "new_password": "new-temporary-password"
}
```

规则：

- 后端 hash 新密码。
- 不返回 `password_hash`。
- 不写明文密码到日志。
- 找不到返回 404。
- 成功写 `operation_logs`，action 建议为 `user.reset_password`。
- C03B 禁止 owner 通过这个接口重置自己的密码。自助改密留到后续单独任务。
- 如果以后要做“首次登录必须改密码”，需要新增字段或 session 策略，不在 C03B 决定。

### `POST /users/{user_id}/disable`

用途：owner 停用子账户。

规则：

- 不能停用自己。
- 找不到返回 404。
- C03B 幂等设置 `is_active = false` 并返回当前用户状态。
- 停用后该用户不能登录，也不能继续通过 `get_current_user` 访问受保护 API。
- 成功写 `operation_logs`，action 建议为 `user.disable`。

### `POST /users/{user_id}/enable`

用途：owner 启用子账户。

规则：

- 找不到返回 404。
- C03B 幂等设置 `is_active = true` 并返回当前用户状态。
- 成功写 `operation_logs`，action 建议为 `user.enable`。

### 错误码规则

建议沿用现有 FastAPI 风格：

- 401：未登录、token 无效、token 过期。
- 403：已登录但不是 owner。
- 404：用户不存在。
- 409：username 唯一约束冲突，或状态冲突如果不做幂等。
- 422：请求字段不合法，例如密码太短、role 不在允许列表。
- 400：试图停用自己、通过 reset-password 重置自己的密码。
- 422：请求字段不合法，例如密码太短、role 不在允许列表、试图创建或设置 `owner` 角色。

### operation_logs 规则

每个成功写操作都必须落一条 operation log：

- `user.create`
- `user.update`
- `user.reset_password`
- `user.disable`
- `user.enable`

日志建议字段：

- `actor_type = "user"`
- `actor_id = 当前 owner id`
- `target_type = "user"`
- `target_id = 目标用户 id`
- `result = "success"` 或安全相关 failure
- `request_id`、`ip_address`、`user_agent` 来自 audit context
- `details` 只放安全信息，例如 role、状态变化、是否幂等，不放密码

C03B 记录成功写操作。普通 409/422 校验失败不额外写账号管理日志，避免日志噪音。

## 12. C03C 前端页面设计草案

建议新增 `/users` 页面，并在左侧 System 分组下增加：

- User Management

页面组成：

- 用户列表。
- 创建用户按钮。
- 创建用户弹窗或独立页面。
- 用户详情抽屉或详情页。
- 启用/停用按钮。
- 重置密码按钮。
- 当前登录用户标识。

用户列表建议字段：

- Username
- Role
- Status
- Last login
- Created at
- Actions

交互规则：

- 当前用户这一行禁用“停用”按钮。
- 不提供删除按钮。
- 创建用户时 role 默认 `viewer` 或 `operator`，不能选择 `owner`。
- 停用、启用、重置密码都必须二次确认。
- 重置密码输入框使用 password 类型。
- 不在浏览器 console 打印密码。
- 不把重置密码结果写入 URL。
- 操作成功后刷新列表或乐观更新。
- 401 时沿用当前 auth provider 清 session。
- 403 时显示无权限错误。

前端 API proxy 需要调整：

- allowlist 增加 `/users`。
- 支持 `GET /users`。
- 支持 `POST /users`。
- 支持 `GET /users/{id}`。
- 支持 `PATCH /users/{id}`。
- 支持 `POST /users/{id}/reset-password`。
- 支持 `POST /users/{id}/disable`。
- 支持 `POST /users/{id}/enable`。
- 当前 route 文件没有 PATCH export，C03C 或 C03B/C03C 协同时需要补。

`/settings` 可以继续保留为系统设置空状态。用户管理建议使用独立 `/users`，避免 settings 页面变成多个职责混合的页面。

## 13. 数据库和 migration 判断

C03A 不新增 migration。

从当前审计看，C03 最小功能可以不新增 migration：

- `username` 已存在且唯一。
- `password_hash` 已存在。
- `role` 已存在。
- `is_active` 已存在，可表示启用/停用。
- `created_at`、`updated_at` 已存在。
- `last_login_at` 已存在。
- `operation_logs` 已存在，可记录账号管理操作。

但如果产品要求以下能力，就需要单独 migration：

- 用户 email。
- email 唯一约束。
- 数据库层 role enum 或 check constraint。
- `disabled_at`、`disabled_by`、`disabled_reason`。
- `created_by`。
- `password_changed_at`。
- `password_reset_required`。
- session table 或 token revocation 表。

建议 C03B 先走“无 migration 的最小账号管理”：

- 用 `role` 字符串做应用层白名单。
- 用 `is_active` 做启用/停用。
- 用 `operation_logs` 记录谁在什么时候做了停用、启用、重置密码。
- C04/C05 再决定是否把 role 约束升级到数据库层。

如果老板明确要求 email 或禁用原因字段进入第一版 C03，则必须先单独审查 migration 方案，不能在 C03A 偷偷落表。

## 14. staging-first 测试发布流程

C03 必须 staging-first：

1. C03B 先在分支或工作区完成后端 API 和测试。
2. C03C 完成前端 `/users` 页面、导航、API proxy 和前端验证。
3. 只用 example Docker 测试跑完整后端、数据库、前端和 acceptance。
4. 部署到 staging，不动 production。
5. staging 创建测试子账户。
6. staging 测试子账户登录。
7. staging 测试 owner 查看用户列表和详情。
8. staging 测试 owner 停用子账户。
9. staging 测试停用后子账户不能登录、旧 token 不能继续访问受保护 API。
10. staging 测试 owner 启用子账户。
11. staging 测试 owner 重置子账户密码。
12. staging 验证所有账号管理写操作都有 operation log，且日志不含密码、token、password_hash。
13. staging 验收通过后，老板明确批准再发布 production。
14. production 发布后运行 production smoke check。
15. production 验收通过后封板。

重要边界：

- staging 测试数据不复制到 production。
- staging 测试账号不作为 production 账号。
- production 不用 staging 密码。
- production 不直接接真实业务。
- C03 发布期间不连接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser。

## 15. C03B-C03F 任务拆分建议

### C03B：后端用户管理 API

目标：

- 新增 owner-only `/users` API。
- 拆分 `get_current_user` 和 `require_owner`。
- 允许基础子账户登录，但不允许访问 owner-only API。
- 创建、列表、详情、启用、停用、重置密码都有测试。
- 确认不返回 `password_hash`。
- 确认 operation log 不含密码。
- 默认不新增 migration，除非老板先批准字段变更。

状态：已由 C03B 完成后端实现，等待老板审核；未提交 git commit。

验收重点：

- owner 可以创建 viewer/operator。
- 子账户不能创建 owner。
- 子账户不能调用 `/users`。
- inactive 用户不能登录。
- owner 不能停用自己。
- `/auth/register` 仍然 404。

### C03C：前端用户管理页面

目标：

- 新增 `/users` 页面。
- 左侧菜单新增 User Management。
- 接入 `/users` API。
- 创建用户、启用/停用、重置密码都有确认和错误状态。
- 当前用户不能停用自己。
- proxy allowlist 精确放行用户管理 API。
- 不加公开注册页面。

### C03D：staging 部署和验收

目标：

- 只部署 staging。
- 创建 staging 测试子账户。
- 验证登录、停用、启用、重置密码。
- 验证 operation logs。
- 验证 staging 不暴露公网。
- 不复制 staging 数据到 production。

### C03E：production 发布和验收

目标：

- 老板批准后再发布 production。
- production smoke check 通过。
- owner 在 production 创建真实需要的子账户前，先确认账号命名和密码交付规则。
- 不接真实业务。

### C03F：C03 封板

目标：

- 归档 C03 完成范围。
- 归档 staging 和 production 验收证据。
- 记录已知风险。
- 明确 C04/C05 角色权限系统入口。

## 16. 当前不接真实业务

C03 只处理账号管理基础，不代表系统可以开始跑真实业务。

当前仍然不接：

- 真实 n8n production workflow。
- P 系列任务。
- WooCommerce。
- MinIO。
- Filebrowser。
- 真实产品创建。
- 真实订单处理。
- 真实业务自动化任务。

真实业务接入必须等账号、角色、权限、审核、日志和 staging-first 发布链路继续封板后，再按独立任务进入。

## 17. C03A/C03B 结论

C03A 审计结论：

- 现有数据表足够支撑最小 C03 账号管理。
- 当前没有 email 字段，如果 C03 要 email，必须另开 migration 任务。
- 当前认证是 owner-only，C03B 必须拆分“已登录用户”和“owner 授权”。
- 当前公开注册不存在，必须继续保持。
- 当前 logout 是 stateless，C03 可接受，但必须记录风险。
- C03 应先 staging 验证，再 production 发布。
- C03A 不创建真实账号，不改业务代码，不接真实业务。

C03B 后端结论：

- 现有 `users` 表足够支撑本阶段，不新增 migration。
- owner-only `/users` API 已实现。
- active 非 owner 子账户可以登录，并可访问 `/auth/me`。
- 非 owner 访问 `/users` 返回 403，未登录访问 `/users` 返回 401。
- inactive 用户登录失败，已有 token 也会被 `get_current_user` 拒绝。
- `/auth/register` 继续不存在。
- operation logs 覆盖 `user.create`、`user.update`、`user.disable`、
  `user.enable`、`user.reset_password`。
- C03B 未做前端页面、完整 RBAC、staging/production 部署或真实业务接入。
