# C06 Permission Frontend UI

日期：2026-06-11 UTC

本文件记录 C06C：前端用户权限管理 UI。

C06C 只做前端 UI、前端 API client、前端 proxy allowlist、前端交互 helper、
前端测试和文档。不新增后端 API，不新增 migration，不发布 staging，不发布
production，不执行 safe release，不接 WooCommerce、n8n 真实业务流、MinIO、
Filebrowser、产品页业务模块或 P 系列。

## 一、C06C 做了什么

- 在 User Management 的用户行增加“权限”入口。
- 在用户详情区域增加“用户权限管理”面板。
- 新增前端 permission assignment 类型、normalize helper 和 API client。
- 接入 C06B 已完成的 owner-only assignment API：
  - `GET /permissions/users/{user_id}/assignments`
  - `POST /permissions/users/{user_id}/assignments`
  - `PATCH /permissions/users/{user_id}/assignments/{assignment_id}`
  - `DELETE /permissions/users/{user_id}/assignments/{assignment_id}`
- 继续使用 `/permissions/registry` 读取可授予的 permission key。
- 精确放行 frontend backend proxy 中的 C06B assignment 路径。
- 增加 high-risk 权限前端识别和二次确认 UI。
- 增加 Node 前端测试，不引入新的测试框架。

## 二、入口和 owner-only 边界

User Management 总入口仍只对 owner full access 可见。

当前边界保持不变：

- `/users` 导航项仍配置 `owner_only: true`。
- `canAccessModule()` 对 owner-only route 只认
  `permissions.is_owner_full_access=true`。
- `UserManagementPanel` 内部仍使用 `isOwnerFullAccess(currentUser?.permissions)`
  做页面挡板。
- 普通用户和非 owner 即使拥有 `users.manage` assignment，也看不到 User
  Management 和权限管理入口。
- `/users` 后端仍使用 `require_owner()`，C06C 没有改成 `users.manage`。

前端权限管理只是 UX，真正安全边界仍是后端 C06B owner-only API 和
`require_owner()`。

## 三、权限管理面板

权限管理面板位于 User Management 的用户详情区域。

owner 选中用户后可以看到：

- explicit assignments 列表。
- `permission_key`、名称/描述、risk、scope、enabled、effective、expires_at。
- `granted_by_user_id`、created/updated、reason。
- grant 表单。
- update 表单。
- revoke reason 输入和确认。

assignment 空列表显示“暂无显式授权。”

目标用户是 owner 时只显示：

- “Owner 拥有全局全权限，不需要单独授权。”
- owner full access 来自 role，不渲染成普通 assignment。
- 不显示普通 grant/update/revoke 操作。

## 四、Grant / Update / Revoke

Grant：

- permission key 来自 `GET /permissions/registry`。
- 支持按 key、name、description、module、category、action、risk 搜索。
- 支持 `scope_type`、`scope_id`、`expires_at`、reason。
- enabled 默认 true；如果前端选择不立即启用，创建后用 C06B update API 立即禁用。
- wildcard `*` 不出现在可授予选项中，前端 helper 也会阻断 wildcard grant。
- 不提供批量授予全部权限。

Update：

- 支持 enabled、expires_at、scope_type、scope_id、reason。
- 不支持直接修改 `permission_key`；需要变更 permission key 时应 revoke 后重新 grant。
- high-risk assignment 重新启用或 scope 变更时显示二次确认区。

Revoke：

- 使用 `DELETE /permissions/users/{user_id}/assignments/{assignment_id}`。
- UI 文案使用“撤销”，后端语义仍是 soft revoke，即设置 assignment disabled。
- 撤销前必须确认。
- high-risk revoke 必须填写 reason。
- revoke 成功后刷新 assignment 列表。

## 五、High-risk 二次确认

C06C 的 high-risk 识别与 C06B 文档保持一致：

- registry `risk_level` 为 `high` 或 `critical`。
- 显式高风险 key，例如 `users.manage`、`permissions.manage`、
  `system.settings.manage`、`settings.manage`、`system.admin`、`secrets.manage`、
  `release.manage`、`production.release`、`production.manage`、`billing.manage`。
- permission key、module、category、action 命中 admin/system/release/secrets/
  production/billing 等高风险特征。

High-risk grant 必须满足：

- reason 非空。
- `confirm_high_risk=true`。
- `confirmation_text="CONFIRM_HIGH_RISK_PERMISSION"`。

High-risk update 在重新启用或 scope 变更时要求同样的确认。High-risk revoke
必须填写 reason。

前端缺少确认时不发送请求，直接显示阻断提示。后端 C06B 仍会再次校验，前端不能替代安全边界。

## 六、operation_logs

C06C 不直接写 operation_logs。

前端只传 reason、`confirm_high_risk` 和 `confirmation_text`。C06B 后端负责写入现有
`operation_logs`，记录 grant/update/revoke 的 actor、target、permission_key、
assignment_id、scope、before/after、reason、risk_level、confirmation 和 result。

前端不打印 token、password、secret 或 Authorization header，不把敏感信息保存到日志。

## 七、role defaults 和 super_admin

`role_default_permissions` 仍是建议模板，不自动生效：

- 前端文案明确“角色默认权限不会自动生效”。
- 前端 helper 不把 role default 当成 effective permission。
- `/permissions/me` 和 `/auth/me.permissions` 的真实 effective permissions 仍以后端解析为准。

`super_admin` 仍不默认拥有 grant/revoke 能力：

- User Management 和权限管理入口只认 owner full access。
- C06B assignment API 使用 `require_owner()`。
- 非 owner 即使拥有 `permissions.manage`，也不能调用 C06B grant/update/revoke。

## 八、Frontend proxy allowlist

C06C 继续使用 restricted same-origin proxy，不开放通用 backend proxy。

本轮精确放行：

- `GET /permissions/me`
- `GET /permissions/registry`
- `GET /permissions/users/{user_id}/assignments`
- `POST /permissions/users/{user_id}/assignments`
- `PATCH /permissions/users/{user_id}/assignments/{assignment_id}`
- `DELETE /permissions/users/{user_id}/assignments/{assignment_id}`

`user_id` 必须是正整数，`assignment_id` 必须是 UUID。未列出的 permissions 路径继续返回
404。

## 九、测试

新增 `tests/frontend/permission-management.test.mjs`，使用 Node 内置 test runner。

覆盖：

- assignment API path helper。
- frontend proxy assignment allowlist。
- high-risk permission 识别。
- wildcard grant option/filter 阻断。
- `role_default_permissions` 不自动生效文案。
- owner 可见权限管理入口，non-owner 不可见。
- owner 目标显示 full access mode。
- 普通用户 assignment 空状态。
- 普通 grant payload。
- high-risk grant 缺少 reason 或 confirmation 被阻断。
- high-risk grant 带确认时 payload 包含 `confirm_high_risk` 和 `confirmation_text`。
- high-risk update 重新启用或 scope 变更的确认要求。
- high-risk revoke 缺少 reason 被阻断。
- revoke 后需要刷新 assignment。
- assignment response 缺字段时安全降级。
- 403/409/422 错误显示安全摘要，不暴露敏感值。

同时保留 `tests/frontend/permissions.test.mjs` 的 C05D 覆盖。

## 十、未做事项

- 没有新增后端 API。
- 没有新增 migration。
- 没有新增 grant/revoke 后端逻辑，C06B 已完成。
- 没有改变 `/users` owner-only 后端边界。
- 没有发布 staging。
- 没有发布 production。
- 没有执行 safe release。
- 没有读取真实 `.env.staging` 或 `.env.production`。
- 没有操作 production/staging 容器或数据库。
- 没有接真实业务。

## 十一、下一步

C06D：staging 用户权限管理联调验收。
