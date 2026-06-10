# C03 Owner Account Management Seal

日期：2026-06-10 UTC

本文件记录 C03F：Owner 创建子账户功能最终封板。

## 一、C03 最终结论

C03 Owner 创建子账户功能已经完成。

production 正式服已经可以访问 User Management：

- `https://ops.barongyekhna.com/users`

当前系统仍然没有公开注册。`/auth/register` 继续返回 404。

## 二、C03A-C03F 完成清单

- C03A：用户系统审计与设计方案。
- C03B：后端用户管理 API。
- C03C：前端用户管理页面。
- C03D：staging 测试服验收。
- C03E：production 正式服发布。
- C03F：最终封板。

## 三、当前已实现能力

- owner 可以查看用户列表。
- owner 可以创建 `viewer` / `operator` / `reviewer` 子账户。
- owner 可以查看用户详情。
- owner 可以停用 / 启用子账户。
- owner 可以重置子账户密码。
- active 非 owner 子账户可以登录。
- 非 owner 不能访问 `/users` 管理 API，staging 已验收返回 403。
- inactive 用户不能登录。
- `/auth/register` 仍然返回 404。
- API 不返回 `password_hash`。
- 用户管理动作写入 `operation_logs`。

## 四、当前没有做的内容

- 不做 `super_admin`。
- 不做完整 RBAC。
- 不做模块权限。
- 不做部门组织架构。
- 不做机器人账号。
- 不做邮件邀请。
- 不做密码找回邮件。
- 不接真实业务模块。

## 五、安全边界

- User Management 当前只有 owner 可以操作。
- 未来 C04/C05 会升级成 Owner + Super Admin + 权限系统。
- 美工、运营、审核员等普通角色当前不能管理用户。
- 前端隐藏入口只是体验，真正安全靠后端 `require_owner` / 403。
- 没有公开注册。
- 不允许创建 `role=owner` 的子账户。

## 六、production 发布状态

本轮只读复核结果：

- production `/users` 返回 200。
- 未登录 `/api/backend/users` 返回 401。
- `/api/backend/auth/register` 返回 404。
- production smoke 通过。
- staging smoke 通过。
- dual env check 通过。

production 和 staging 容器均正常运行。

## 七、剩余风险与后续任务

- 当前 JWT logout 仍是 stateless audit，后续可做 session/token revocation。
- 当前权限仍是粗粒度 owner-only，不是完整 RBAC。
- `super_admin` 留到 C04/C05。
- 用户管理页面更多体验优化后续再做。
- 下一阶段是 C04：角色体系。

## 八、C04 后续承接说明

C04 已由 C04A 开始，方案文档见 `docs/C04_ROLE_SYSTEM_PLAN.md`。

C04 只定义角色体系，也就是账号身份类型。C04 不等于完整权限系统，不新增
permissions 表，不做 role_permissions，不做模块权限，不接真实业务。

C04 标准角色建议为：

- `owner`
- `super_admin`
- `module_admin`
- `operator`
- `reviewer`
- `viewer`
- `bot_agent`

其中 `owner` 只能通过 bootstrap 或系统初始化产生，不能通过 `/users` 创建。
`super_admin` 在 C04 只定义，不应在 C04 直接拥有全部权限；具体能做什么留给 C05
权限系统。`bot_agent` 只作为未来机器人账号类型预留，不在 C04 接真实机器人。

美工、SEO 编辑、客服、工厂主管等公司岗位不应该硬编码成 role。后续应通过
`role` + `job_title` + `department` + `module_access` + `permissions` 组合表达。

C05 才承接 permissions、module access 和角色权限绑定。

C04B 已补充后端统一角色常量和校验。标准角色现在已在代码中定义为 `owner`、
`super_admin`、`module_admin`、`operator`、`reviewer`、`viewer`、`bot_agent`，
但 `/users` 当前仍只允许 owner 创建 `viewer`、`operator`、`reviewer`。`super_admin`、
`module_admin` 和 `bot_agent` 仍未放权、未开放创建，完整权限系统仍由 C05 承接。

C04C 已补充前端 User Management 角色目录化：页面通过 owner-only
`GET /users/roles` 读取角色目录，创建用户下拉只展示 `viewer`、`operator`、
`reviewer`，并在说明区展示 `owner`、`super_admin`、`module_admin`、`bot_agent`
为 C04 当前不可选择角色。C04C 不做完整 RBAC，不部署 staging/production，不创建真实用户，
不接真实业务。下一步 C04D 是部署到 staging 测试服验收角色目录 UI。

## 九、C03 封板结论

C03 已完成。

后续所有账号权限扩展必须基于 C03 已封板能力，不允许绕过 owner-only 管理边界。
