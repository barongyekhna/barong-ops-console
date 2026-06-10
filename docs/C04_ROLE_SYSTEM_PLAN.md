# C04 Role System Plan

日期：2026-06-10 UTC

本文件记录 C04A：角色体系审计与设计方案，并追加 C04B 后端角色常量与校验落地状态。

C04A 只做审计、设计、风险分析、后续任务拆分和文档更新。它不实现功能，不新增
migration，不修改 production/staging 容器，不创建真实用户，不接真实业务。

C04B 已在后端新增统一 role constants、role metadata、assignable-role 校验和测试。
C04B 仍不做完整 RBAC，不新增 migration，不部署 staging，不发布 production，不接真实业务。

## 一、为什么要做角色体系

C03 已经让 owner 可以创建和管理子账户。现在系统能区分“谁登录了”，也能做基础的
停用、启用、重置密码和操作日志。

但是 C03 的 role 还很粗：

- 数据库存的是一个字符串。
- owner 之外，只支持 `viewer`、`operator`、`reviewer`。
- `/users` 管理接口还是 owner-only。
- 没有 `super_admin`、`module_admin`、`bot_agent`。
- 没有完整 RBAC，也没有 permissions 表。

C04 要解决的是“账号是什么身份”。它先把系统身份类型定义清楚，让后续 C05 能在这个
基础上做“这个身份能做什么”。

## 二、C03、C04、C05 的关系

C03 是账号生命周期：

- owner 创建子账户。
- owner 管理子账户状态。
- owner 重置子账户密码。
- 子账户可以登录。
- 操作写入 operation logs。

C04 是角色体系：

- 定义标准 role。
- 统一后端 role 校验。
- 统一前端 role 展示和选择。
- 说明每个 role 是账号身份，不是具体权限。

C05 才是权限系统：

- 定义 permissions。
- 定义 role 和 permissions 的绑定。
- 定义模块访问范围。
- 定义谁能管理用户、谁能操作模块、谁能审核、谁能发布。

所以 C04 不是完整 RBAC。C04 只把身份类型摆正，不在 C04 里直接给
`super_admin` 或 `module_admin` 放权。

## 三、当前 role 审计结论

本轮只读审计了这些文件：

- `backend/app/models/user.py`
- `backend/app/schemas/user.py`
- `backend/app/services/user_management_service.py`
- `backend/app/api/routes/users.py`
- `backend/app/api/deps.py`
- `backend/app/repositories/users.py`
- `backend/app/cli/bootstrap_owner.py`
- `backend/app/core/security.py`
- `frontend/src/components/user-management-panel.tsx`
- `frontend/src/lib/users-api.ts`
- `docs/C03_OWNER_ACCOUNT_MANAGEMENT_PLAN.md`
- `docs/C03_OWNER_ACCOUNT_MANAGEMENT_SEAL.md`
- `tests/backend/test_user_management_api.py`

当前结论：

- `users.role` 是 `String(50)`，非空，不是数据库 enum，也没有 check constraint。
- 当前创建和更新子账户时，Pydantic schema 只允许 `viewer`、`operator`、
  `reviewer`。
- 当前 owner 由 `role == "owner"` 表示。
- `require_owner` 在 `backend/app/api/deps.py`，直接判断 `user.role != "owner"` 时
  返回 403。
- `/users` 相关 API 全部依赖 `require_owner`。
- JWT token 里带 `role`，`get_current_user` 会校验 token role 和数据库 role 一致。
  用户 role 被修改后，旧 token 会因为 role 不一致失效，需要重新登录。
- owner bootstrap 通过 `create_owner` 创建 `role="owner"` 且 `is_active=True` 的用户。
- 前端 `/users` 页面用 `currentUser?.role === "owner"` 判断是否显示用户管理界面。
- 前端 role 下拉来自 `MANAGED_USER_ROLES`，当前只有 `viewer`、`operator`、
  `reviewer`。
- 前端列表可以显示已有 owner，但详情页只允许修改 managed sub-account role。
- 测试覆盖了 operator 创建、viewer 默认创建、reviewer 更新、owner 创建被拒绝、
  非 owner 访问 `/users` 返回 403、禁用/启用/重置密码和 operation logs。
- 测试没有覆盖 `super_admin`、`module_admin`、`bot_agent`，因为这些角色还没有实现。
- 当前结构可以承载 C04 的标准 role 字符串，但不足以承载 C05 的权限矩阵。

## 四、当前 role 是否够用

结论：够 C04 用，不够 C05 用。

够 C04 用的原因：

- `String(50)` 可以存下 `owner`、`super_admin`、`module_admin`、`operator`、
  `reviewer`、`viewer`、`bot_agent`。
- 当前没有数据库 enum 或 check constraint，C04B 可以先在应用层统一 role 常量和校验。
- 不需要为了增加几个标准 role 立刻改表。

不够 C05 用的原因：

- role 只是身份标签，不知道能进哪些模块。
- role 不能表达“只能管某一个模块”。
- role 不能表达具体动作，比如创建、审核、发布、导出、停用用户。
- role 不能表达部门、岗位、审批链、机器人凭证范围。

因此 C04B 建议不新增 migration，只做应用层 constants、validation 和测试。C05 再设计
permissions、module access 和角色权限绑定。

## 五、标准角色定义

### 1. owner

owner 是系统最高所有者身份。它代表这套 console 的归属方，不是普通管理岗位。

- 人类账号：是。
- 机器人账号：否。
- 是否可由 owner 创建：否。owner 只能由 bootstrap 或系统初始化产生。
- 是否可由普通用户创建：否。
- 是否可以管理用户：当前 C03 已经允许 owner 管理用户；C04 不新增更多授权。
- 是否可以操作模块：C04 不定义。当前已有 owner-only demo/API 行为继续保留，真实模块权限留给 C05。
- C04 是否只定义不放权：是，C04 不扩展 owner 的业务权限。
- C05 如何绑定 permissions：C05 可以把 owner 绑定到最高级系统权限，但要通过明确权限矩阵表达。

### 2. super_admin

super_admin 是未来的超级管理员身份。它不是 owner，也不代表系统所有权。

- 人类账号：是。
- 机器人账号：否。
- 是否可由 owner 创建：C04A 建议否。C04 先定义，不在 `/users` 放开创建。
- 是否可由普通用户创建：否。
- 是否可以管理用户：C04 不授权。后续 C05 通过 `user.manage` 等 permission 决定。
- 是否可以操作模块：C04 不授权。后续 C05 通过模块权限决定。
- C04 是否只定义不放权：是。
- C05 如何绑定 permissions：C05 再决定是否给 super_admin 绑定跨模块管理权限、用户管理权限和高风险操作权限。

不建议 C04 创建 super_admin 的原因：

- 名字天然暗示“很大权限”，但 C04 还没有权限系统。
- 如果 C04 先创建 super_admin，C05 再赋权，可能让已有账号突然获得大量权限。
- 需要二次确认、审计策略、可能还需要双人审批或 owner-only 升级流程，这些都属于 C05 或后续安全任务。

### 3. module_admin

module_admin 是未来的模块管理员身份。它只说明这个账号可能管理某些模块，不等于能管理所有模块。

- 人类账号：是。
- 机器人账号：否。
- 是否可由 owner 创建：C04B 先不开放，等 C05/C07 明确模块范围后再决定。
- 是否可由普通用户创建：否。
- 是否可以管理用户：C04 不授权。C05 再决定是否有 scoped user management。
- 是否可以操作模块：C04 不授权。模块范围必须由后续 module access / permissions 决定。
- C04 是否只定义不放权：是。
- C05 如何绑定 permissions：C05/C07 再绑定具体模块范围，例如只能管理某个模块、某类任务或某条 workflow。

风险说明：`module_admin` 不能被理解成“所有模块管理员”。没有模块范围字段和权限矩阵前，它只是一个角色标签。

### 4. operator

operator 是普通操作员身份，适合执行日常业务动作。

- 人类账号：是。
- 机器人账号：否。
- 是否可由 owner 创建：是。
- 是否可由普通用户创建：否。
- 是否可以管理用户：否，除非 C05 明确授予。
- 是否可以操作模块：C04 不授权。C05 再按模块和动作授予。
- C04 是否只定义不放权：是。
- C05 如何绑定 permissions：C05 可绑定任务创建、资料维护、素材处理、订单处理等具体权限。

### 5. reviewer

reviewer 是审核员身份，适合做人审、质检、确认和驳回。

- 人类账号：是。
- 机器人账号：否。
- 是否可由 owner 创建：是。
- 是否可由普通用户创建：否。
- 是否可以管理用户：否，除非 C05 明确授予。
- 是否可以操作模块：C04 不授权。C05 再决定可查看哪些待审核内容、可做哪些决定。
- C04 是否只定义不放权：是。
- C05 如何绑定 permissions：C05 可绑定审核、驳回、评论、放行、查看审计记录等权限。

### 6. viewer

viewer 是只读查看身份。

- 人类账号：是。
- 机器人账号：否。
- 是否可由 owner 创建：是。
- 是否可由普通用户创建：否。
- 是否可以管理用户：否。
- 是否可以操作模块：C04 不授权。C05 再决定能看哪些模块和字段。
- C04 是否只定义不放权：是。
- C05 如何绑定 permissions：C05 可绑定只读页面、报表、状态查看和低风险审计查看权限。

### 7. bot_agent

bot_agent 是未来机器人或自动化代理账号类型。

- 人类账号：否。
- 机器人账号：是。
- 是否可由 owner 创建：C04A 建议否。C04 只预留，不接真实机器人。
- 是否可由普通用户创建：否。
- 是否可以管理用户：否。
- 是否可以操作模块：C04 不授权。后续必须由专门 token、scope、module access 和审计策略控制。
- C04 是否只定义不放权：是。
- C05 如何绑定 permissions：C05/C18/C19 再决定机器人可调用哪些 API、能写哪些日志、如何吊销凭证。

## 六、标准角色一览

| role | 定位 | 人类账号 | 机器人账号 | owner 在 C04 是否可创建 | 普通用户是否可创建 | C04 是否放权 |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | 系统所有者 | 是 | 否 | 否，只能 bootstrap/系统初始化 | 否 | 不新增放权 |
| `super_admin` | 未来超级管理员 | 是 | 否 | 建议否，先定义 | 否 | 不放权 |
| `module_admin` | 未来模块管理员 | 是 | 否 | 否，C04B 先不开放 | 否 | 不放权 |
| `operator` | 日常操作员 | 是 | 否 | 是 | 否 | 不放权 |
| `reviewer` | 审核员 | 是 | 否 | 是 | 否 | 不放权 |
| `viewer` | 只读查看账号 | 是 | 否 | 是 | 否 | 不放权 |
| `bot_agent` | 未来机器人账号 | 否 | 是 | 建议否，先预留 | 否 | 不放权 |

## 七、role、job_title、department、permissions 的区别

role 是系统身份等级。它回答“这个账号在系统里是什么类型”。

job_title 是公司岗位名称。它回答“这个人在公司里叫什么岗位”。

department 是部门。它回答“这个人属于哪个组织单元”。

permissions 是具体能做什么。它回答“这个账号能执行哪些动作”。

module access 是能进入哪些板块。它回答“这个账号能看到或使用哪些模块”。

不要把具体职位硬编码成 role。否则 role 会很快变成一堆公司岗位名，比如
`designer`、`seo_editor`、`customer_service`、`factory_manager`。这会让权限系统失控，
也会让同一个岗位在不同部门、不同模块、不同权限范围下无法表达。

正确做法是组合：

- `role`
- `job_title`
- `department`
- `module_access`
- `permissions`

例子：美工账号不应该做成 `role=designer`。

正确表达方式：

- `role=operator`
- `job_title=美工`
- `department=设计部`
- `module_access=image_assets`
- `permissions` 后续在 C05/C07 定义

其他例子：

- SEO 编辑：`role=operator`，`job_title=SEO 编辑`，`department=内容部`，模块访问和权限后续定义。
- 客服：`role=operator` 或 `viewer`，`job_title=客服`，`department=客服部`，订单/消息权限后续定义。
- 工厂主管：`role=module_admin` 或 `operator`，`job_title=工厂主管`，`department=工厂部`，工厂模块范围后续定义。

## 八、C04 应该做什么

C04 建议做这些事：

- 定义标准角色常量或枚举方案。
- 后端统一校验 role，避免每个 schema 自己写一份字符串列表。
- 前端用户管理页面显示标准角色名称。
- owner 可以创建基础角色子账户。
- 明确 `owner` 不能通过 `/users` 创建。
- 明确 `super_admin` 在 C04 只定义，不建议开放创建，也不直接拥有全部权限。
- 明确 `bot_agent` 只预留，不接真实机器人。
- 文档写清楚每个角色的含义和边界。
- 增加测试覆盖标准 role 白名单和危险 role 拦截。

C04B 的保守建议：

- `/users` 继续禁止创建 `owner`。
- `/users` 暂不开放创建 `super_admin`。
- `/users` 暂不开放创建 `bot_agent`。
- `/users` 暂不开放创建 `module_admin`，等 C05/C07 明确模块范围后再决定。
- `viewer`、`operator`、`reviewer` 继续作为普通 owner-created 子账户角色。

C04B 实际落地：

- 新增 `backend/app/core/roles.py`，集中定义 `owner`、`super_admin`、
  `module_admin`、`operator`、`reviewer`、`viewer`、`bot_agent`。
- 当前 owner 通过 `/users` 可创建角色仍只有 `viewer`、`operator`、`reviewer`。
- `/users` 继续拒绝创建或更新为 `owner`、`super_admin`、`module_admin`、`bot_agent`。
- `super_admin` 只作为标准角色定义存在，没有任何 C04B 实际权限。
- `module_admin` 和 `bot_agent` 只预留，不开放创建。
- 新增 owner-only `GET /users/roles`，返回用户管理页可创建角色和标准角色目录。
- `require_owner` 改为通过统一 helper 判断 owner，不改变 `/users` owner-only 行为。

## 九、C04 暂不做什么

C04 不做这些事：

- 不做完整 RBAC。
- 不新增 permissions 表。
- 不新增 role_permissions 表。
- 不做 module_permissions。
- 不做 department 组织架构。
- 不做 job_title 管理。
- 不接 bot/agent 真实账号。
- 不让 super_admin 真正拥有全部权限。
- 不做模块权限。
- 不发布 production。
- 不接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser。
- 不创建真实业务任务。

这些内容留给 C05、C18、C19 或后续模块体系。

## 十、是否需要 migration

C04A 判断：不建议 C04B 新增 migration。

原因：

- 现有 `users.role` 是字符串，长度 50，能存下 C04 标准角色。
- 当前没有数据库 enum/check constraint，应用层可以先统一校验。
- C04 只定义身份，不需要新增权限表。
- C04 不做 department、job_title、module access、permissions，所以不需要新字段。

如果后续要把 role 变成数据库 enum 或 check constraint，要单独评估：

- 线上已有 role 数据是否全部合法。
- migration 如何处理旧值。
- rollback 怎么做。
- C05 的 permissions 设计是否已经定稿。

所以 C04B 先不要新增 migration，等老板确认 C05 权限模型后再决定是否改数据库约束。

## 十一、风险分析

1. `super_admin` 过早创建的风险

   C04 还没有权限系统。如果现在允许创建 `super_admin`，后续 C05 一旦给
   `super_admin` 绑定高权限，已有账号可能突然变成高权限账号。建议 C04 先定义，
   不创建、不放权。

2. `module_admin` 被误解的风险

   没有 module access 前，`module_admin` 不能表示“管哪个模块”。C04B 已选择先不开放
   `/users` 创建，等 C05/C07 明确模块范围后再决定。

3. 职位塞进 role 的风险

   美工、SEO、客服、工厂主管都不是系统身份等级。把这些塞进 role 会导致 role 膨胀，
   后续权限无法维护。

4. 只有应用层校验的风险

   由于数据库没有 check constraint，直接写库仍可能写入未知 role。C04B 可以通过代码、
   API 测试和文档控制；数据库约束留到 C05 模型稳定后再做。

5. JWT role 变更的影响

   当前 token 带 role，后端要求 token role 和数据库 role 一致。修改 role 会让旧 token
   失效，用户需要重新登录。这是安全上可接受的行为，但前端提示可以后续优化。

## 十二、C04B-C04F 后续计划

### C04B：后端角色常量、校验和测试

- 新增后端标准 role 常量或枚举。
- 统一 `owner`、`viewer`、`operator`、`reviewer` 等字符串来源。
- 扩展或调整 `ManagedUserRole` 的校验策略。
- 明确禁止 `/users` 创建 `owner`、`super_admin`、`bot_agent`。
- C04B 已保守决定暂不允许 `/users` 创建 `module_admin`。
- 增加测试覆盖标准角色、危险角色和未知角色。
- 不新增 migration。
- 不发布 production。

### C04C：前端角色显示/选择优化

- 前端复用标准角色列表。
- 优化 role label，例如 `super_admin` 显示为 Super admin。
- 创建用户下拉只展示 C04B 允许 owner 创建的角色。
- 对 `owner`、`super_admin`、`bot_agent` 等不可创建或不可编辑角色给出安全边界。
- 不接真实业务。

### C04D：staging 验收角色创建和登录

- 在 staging 验收允许创建的基础角色。
- 验证非 owner 仍不能访问 `/users`。
- 验证不可创建 `owner`、`super_admin`、`bot_agent`。
- 验证角色变更后旧 token 失效或需要重新登录的行为。
- 不创建 production 用户。

### C04E：production 发布

- 只在 C04B/C04C/C04D 通过后发布。
- 发布前后运行 production/staging/dual env smoke。
- 不读取真实 env。
- 不重启、删除、重建 production/staging 容器，除非进入单独发布流程并获准。
- 不接真实业务。

### C04F：角色体系封板

- 归档 C04 完成内容。
- 记录最终允许创建的角色。
- 记录未做权限系统。
- 明确 C05 承接 permissions、module access、role_permissions。

## 十三、C04A 当前边界

本轮 C04A：

- 不读取或修改真实 `.env.production` / `.env.staging`。
- 不打印 secret、token、password。
- 不创建 production/staging 真实用户。
- 不操作 production/staging 数据库。
- 不新增 migration。
- 不修改后端业务代码。
- 不修改前端功能代码。
- 不启动、停止、重启、删除、重建容器。
- 不修改 Nginx 或证书。
- 不接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser。
- 不创建真实业务任务。
- 不 git commit。

当前仍然是 foundation/console 阶段。C04 只定义角色体系，不接真实业务。
