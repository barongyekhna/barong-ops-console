# C04E Production Release

日期：2026-06-10 UTC

本文件记录 C04E：角色目录 UI production 发布后的只读验收归档。

C04E 的发布动作已经由人工完成。本轮 C04E-6 不再部署、不重建、不停止、不删除任何
production 或 staging 容器，只做只读复核和文档归档。

## 1. 本次发布了什么

C04E 把 C04B 和 C04C 的角色目录能力放到了 production：

- C04B 后端角色目录已经进入 production。
- C04C 前端角色目录 UI 已经进入 production。
- production 正式地址是 `https://ops.barongyekhna.com/users`。
- User Management 页面已经使用后端角色目录。
- 创建用户下拉只允许选择 `viewer`、`operator`、`reviewer`。
- `owner`、`super_admin`、`module_admin`、`bot_agent` 是 reserved，不可选、
  不可通过 `/users` 创建。

说白了：C04E 不是新增一套权限系统，而是让 production 的用户管理页面使用 C04 的
标准角色目录。

## 2. 当前角色边界

C04 当前只定义角色体系，不做完整 RBAC。

当前规则：

- `owner` 仍然只能来自 bootstrap 或系统初始化，不能通过 `/users` 创建。
- `viewer`、`operator`、`reviewer` 是当前 owner 可以创建的普通子账号角色。
- `super_admin` 当前没有放权，不可创建。
- `module_admin` 当前没有模块范围，所以不开放。
- `bot_agent` 当前没有机器人身份和 token scope，所以不开放。
- C05 才做 permissions、module access、role-to-permission 绑定和完整权限系统。

因此，`super_admin`、`module_admin`、`bot_agent` 在 C04 只是预留角色名，不代表已经
可以使用或已经拥有权限。

## 3. 只读验收结果

本轮运行了这些只读命令：

```bash
git status --short --untracked-files=all
./scripts/production_smoke_check.sh
./scripts/staging_smoke_check.sh
./scripts/check_dual_env_status.sh
curl -I --max-time 15 https://ops.barongyekhna.com/users
curl -sS -i --max-time 15 https://ops.barongyekhna.com/api/backend/users/roles | head -40
curl -sS --max-time 15 https://ops.barongyekhna.com/api/backend/health
curl -I --max-time 15 http://127.0.0.1:3100/users
curl -sS --max-time 15 http://127.0.0.1:3100/api/backend/health
```

结果：

- production `/users` 返回 `200`。
- 未登录访问 production `/api/backend/users/roles` 返回 `401`。
- production backend health 返回 `status=ok`、`service=barong-ops-console-backend`、
  `environment=production`。
- staging `/users` 返回 `200`。
- staging backend health 返回 `status=ok`、`service=barong-ops-console-backend`、
  `environment=staging`。
- `./scripts/production_smoke_check.sh` 通过。
- `./scripts/staging_smoke_check.sh` 通过。
- `./scripts/check_dual_env_status.sh` 通过。
- production frontend、backend、postgres 三个容器仍然正常。
- staging frontend、backend、postgres 三个容器仍然正常。
- production/staging Postgres 都没有暴露宿主机 5432。

## 4. 本轮没有做什么

本轮没有做这些事：

- 没有新增 migration。
- 没有接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser 或任何真实业务模块。
- 没有创建真实业务任务。
- 没有读取、打印或修改真实 `.env.production` 或 `.env.staging` 内容。
- 没有打印 secret、token、password 或 Authorization header。
- 没有创建 production 用户。
- 没有调用 production `/users` API 创建用户。
- 没有操作 production 或 staging 数据库数据。
- 没有执行 `docker-compose up/down`。
- 没有停止、删除、重启或重建 production/staging 容器。
- 没有修改 Nginx 或证书。
- 没有执行 certbot。
- 没有 git commit。

## 5. 结论

C04E production 发布验收归档通过。

结论：

- C04B 后端角色目录已经在 production 可用。
- C04C 前端角色目录 UI 已经在 production 可用。
- `https://ops.barongyekhna.com/users` 可访问。
- 未登录访问 `/api/backend/users/roles` 正确返回 `401`。
- 当前创建用户仍只允许 `viewer`、`operator`、`reviewer`。
- `owner`、`super_admin`、`module_admin`、`bot_agent` 仍是 reserved，不可创建、
  不可选择。
- C04 不做完整 RBAC，C05 才做权限系统。
- staging 仍保留为测试服。

C04F 角色体系总封板已完成，封板文档见
`docs/C04_ROLE_SYSTEM_SEAL.md`。

下一步建议先做 OPS01：Docker Compose v1 `ContainerConfig` 问题治理；随后 C05
再做 permissions / RBAC。

## 6. C04F 封板补充

2026-06-10 UTC，C04F 对 production 发布后的角色体系做了只读复核和总封板。

C04F 复核结果：

- production `/users` 返回 `200`。
- 未登录 production `/api/backend/users/roles` 返回 `401`。
- 未登录 production `/api/backend/users` 返回 `401`。
- production `/api/backend/auth/register` 仍返回 `404`。
- `./scripts/production_smoke_check.sh` 通过。
- `./scripts/staging_smoke_check.sh` 通过。
- `./scripts/check_dual_env_status.sh` 通过。
- production/staging 容器均正常运行。
- production/staging PostgreSQL 未暴露宿主机 `5432`。

C04F 封板结论：

- C04 已完成，当前只定义账号身份，不做完整 RBAC。
- 当前可创建角色为 `viewer`、`operator`、`reviewer`。
- `owner`、`super_admin`、`module_admin`、`bot_agent` 仍为 reserved，不可创建、
  不可分配。
- `super_admin` 当前没有放权，必须等 C05 权限系统。
- C04F 没有读取真实 env，没有创建 production 用户，没有重启、删除、重建容器，
  没有修改 Nginx/证书，没有接真实业务，没有 git commit。
