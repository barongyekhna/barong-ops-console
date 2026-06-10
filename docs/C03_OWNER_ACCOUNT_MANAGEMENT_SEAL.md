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

## 八、C03 封板结论

C03 已完成。

后续所有账号权限扩展必须基于 C03 已封板能力，不允许绕过 owner-only 管理边界。
