# C04 Role System Seal

日期：2026-06-10 UTC

本文件记录 C04F：角色体系总封板。

C04F 只做只读复核和文档封板。不新增功能，不部署，不重建容器，不创建真实用户，
不修改 Nginx，不接真实业务，不新增 migration，不 git commit。

## 一、C04 最终结论

C04 角色体系已完成。

说白了，C04 已经把“系统里有哪些标准账号身份”定清楚了：

- 标准角色已经统一定义。
- 后端统一角色常量、角色 metadata、角色校验已完成。
- 后端已有 owner-only `GET /users/roles` 角色目录。
- 前端 User Management 页面已经使用后端角色目录。
- production 正式服已经发布角色目录 UI。
- 当前 `/users` 仍只允许创建和分配安全的普通子账号角色。
- 当前仍不做完整权限系统。

C04 的重点是“身份”，不是“权限”。真正的 permissions、RBAC、模块权限和
role-to-permission 绑定进入 C05。

## 二、C04A-C04F 完成清单

- C04A：角色体系设计。审计现有 role 使用方式，定义标准角色和 C04/C05 边界。
- C04B：后端角色常量与校验。新增统一 role constants、role metadata、
  assignable-role 校验、`GET /users/roles` 和测试。
- C04C：前端角色目录 UI。User Management 创建用户和修改角色下拉改为读取角色目录。
- C04D：staging 验收。staging 角色目录 UI/API 验收通过，reserved roles 拒绝矩阵正确。
- C04E：production 发布。production `/users` 已发布角色目录 UI，并完成只读验收。
- C04F：总封板。完成 C04 最终边界、结果、风险和后续任务归档。

## 三、当前标准角色

C04 标准角色一共七个：

- `owner`
- `super_admin`
- `module_admin`
- `operator`
- `reviewer`
- `viewer`
- `bot_agent`

| role | 当前定位 | 当前是否可创建 | 当前是否放权 | 后续扩展阶段 |
| --- | --- | --- | --- | --- |
| `owner` | 系统最高所有者，代表这套 console 的归属方，不是普通岗位。 | 不可通过 `/users` 创建，只能 bootstrap 或 system 初始化。 | C04 不新增放权。当前已有 owner-only 用户管理行为继续保留。 | C05 用权限矩阵明确最高权限；C18 或后续再处理组织范围。 |
| `super_admin` | 未来超级管理员，不等于 owner，也不代表系统所有权。 | 不可创建，不可分配。 | 不放权。C04 只定义名字。 | C05 决定是否以及如何授予跨模块管理权限。 |
| `module_admin` | 未来模块管理员，必须绑定具体模块范围才有意义。 | 不可创建，不可分配。 | 不放权。没有 module scope 前不能开放。 | C05/C07 继续定义 module scope、module access 和模块权限。 |
| `operator` | 日常操作员身份，适合执行具体业务动作。 | 可由 owner 通过 `/users` 创建和分配。 | C04 不放业务权限。 | C05 按模块和动作绑定 permissions。 |
| `reviewer` | 审核员身份，适合做人审、质检、确认和驳回。 | 可由 owner 通过 `/users` 创建和分配。 | C04 不放业务权限。 | C05 定义审核、驳回、放行、查看审计等权限。 |
| `viewer` | 只读查看身份。 | 可由 owner 通过 `/users` 创建和分配。 | C04 不放业务权限。 | C05 定义可查看哪些模块、页面、字段和报表。 |
| `bot_agent` | 未来机器人或自动化代理账号类型。 | 不可创建，不可分配。 | 不放权。没有 agent identity 和 token scope 前不能开放。 | 后续机器人体系处理，必要时和 C05/C18/C19 权限、scope、审计衔接。 |

## 四、当前可创建角色

当前 owner 可以通过 User Management 创建和分配的角色只有三个：

- `viewer`
- `operator`
- `reviewer`

这三个是 C04 的安全白名单。前端下拉来自后端角色目录，并继续经过前端安全白名单过滤。
后端创建和 PATCH 也只接受这三个 assignable roles。

## 五、当前预留但不可创建角色

当前预留但不可通过 `/users` 创建或分配的角色是：

- `owner`：只能 bootstrap 或 system 初始化，不能由页面创建。
- `super_admin`：只预留，不放权，C05 后续处理。
- `module_admin`：缺少 module scope，C05/C07 后续处理。
- `bot_agent`：缺少 agent identity / token scope，后续机器人体系处理。

这些角色现在可以在角色目录里展示，但 `assignable=false`，不会进入创建用户或修改角色下拉。

## 六、C04 和 C05 的边界

C04 定义“身份”。

C05 定义“权限”。

C04 不做这些事：

- 不做 RBAC。
- 不新增 `permissions` 表。
- 不新增 `role_permissions` 表。
- 不做 `module_permissions`。
- 不做 module access 权限矩阵。
- 不让 `super_admin` 自动拥有全部权限。
- 不把 `module_admin` 当成所有模块管理员。
- 不接真实业务模块。

C05 才负责回答“这个身份能做什么”。例如谁能管理用户、谁能访问某个模块、谁能创建、
审核、发布、导出、删除或执行高风险动作，都必须进入 C05 的权限系统设计。

## 七、职位与角色的区别

`role` 是系统身份等级。它回答：这个账号在系统里是什么类型。

`job_title` 是职位。例如美工、SEO、客服、工厂主管。它回答：这个人在公司里是什么岗位。

`department` 是部门。它回答：这个人属于哪个部门或组织单元。

`permissions` 是具体能做什么。它回答：这个账号可以执行哪些动作。

未来职位不硬编码成 role。美工、SEO、客服、工厂主管这些都不应该变成
`designer`、`seo_editor`、`customer_service`、`factory_manager` 这样的系统 role。

以后应该用组合表达：

- `role`
- `job_title`
- `department`
- `module access`
- `permissions`

例子：

- 美工：`role=operator`，`job_title=美工`，`department=设计部`，再配图片或素材模块权限。
- SEO：`role=operator`，`job_title=SEO`，`department=内容部`，再配内容模块权限。
- 客服：`role=operator` 或 `viewer`，`job_title=客服`，`department=客服部`，再配订单或消息权限。
- 工厂主管：后续可用 `module_admin` 或 `operator`，再配工厂模块范围和权限。

## 八、production 发布状态

2026-06-10 UTC，C04F 只读复核结果：

- production `/users` 返回 `200`。
- 未登录 production `/api/backend/users/roles` 返回 `401`。
- 未登录 production `/api/backend/users` 返回 `401`。
- production `/api/backend/auth/register` 仍然返回 `404`。
- `./scripts/production_smoke_check.sh` 通过。
- `./scripts/staging_smoke_check.sh` 通过。
- `./scripts/check_dual_env_status.sh` 通过。
- production frontend/backend/postgres 容器正常运行。
- staging frontend/backend/postgres 容器正常运行。
- production/staging PostgreSQL 未暴露宿主机 `5432`。

production 正式页面：

- `https://ops.barongyekhna.com/users`

## 九、安全边界

C04F 没有做这些事：

- 没有公开注册。
- 没有创建 production 用户。
- 没有调用 production `/users` API 创建用户。
- 没有操作 production 或 staging 数据库数据。
- 没有新增 migration。
- 没有接真实业务。
- 没有接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser。
- 没有创建真实业务任务。
- 没有修改 Nginx 或证书。
- 没有 reload/restart Nginx。
- 没有执行 certbot。
- 没有读取、打印或修改真实 env 文件内容。
- 没有打印 secret、token、password 或 Authorization header。
- 没有执行 `docker-compose up/down`。
- 没有 stop、restart、rm、recreate production 或 staging 容器。
- 没有 git commit。

reserved 角色仍不可创建、不可分配：

- `owner`
- `super_admin`
- `module_admin`
- `bot_agent`

## 十、剩余风险与后续任务

剩余风险：

- 数据库层目前没有 role enum 或 check constraint，C04 仍依赖应用层统一校验。
- `super_admin` 只是标准角色名，还没有任何权限矩阵，不能开放。
- `module_admin` 没有 module scope，不能开放。
- `bot_agent` 没有 agent identity、token scope 和吊销策略，不能开放。
- 公司、工厂、部门、组织范围还没有进入模型。

后续任务：

- C05：权限系统 / RBAC。
- C05：permissions、role-to-permission、module access、模块动作权限。
- C18 或后续：公司 / 工厂 / 部门 / 组织范围。
- 后续机器人体系：`bot_agent` 真实机器人账号、token scope、审计和吊销。
- `super_admin` 真正放权必须等 C05。
- OPS01：Docker Compose v1 `ContainerConfig` 问题治理。

C04 后建议先处理 OPS01，再进入 C05。原因是权限系统会继续增加测试和发布复杂度，
先把 Docker Compose v1 的 `ContainerConfig` 问题治理掉，可以降低后续施工风险。

## 十一、C04 封板结论

C04 已完成。

后续账号身份扩展必须遵守 C04 标准角色体系，不允许业务模块自己随便发明系统 role。

后续权限扩展必须进入 C05，不允许在业务模块里私自写死权限。

当前最终规则：

- 标准角色：`owner`、`super_admin`、`module_admin`、`operator`、`reviewer`、
  `viewer`、`bot_agent`。
- 当前可创建角色：`viewer`、`operator`、`reviewer`。
- 当前不可创建角色：`owner`、`super_admin`、`module_admin`、`bot_agent`。
- C04 不做完整 RBAC。
- C05 才做 permissions / RBAC。
- C04 后先做 OPS01：Docker Compose v1 `ContainerConfig` 问题治理。
