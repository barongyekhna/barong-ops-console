# C03 Production Release

日期：2026-06-10 UTC

本文件记录 C03E：Owner 用户管理功能已经进入 production 的发布归档。
C03F 最终封板已经完成，封板归档见
`docs/C03_OWNER_ACCOUNT_MANAGEMENT_SEAL.md`。

## 1. 这次发布了什么

C03E 把 C03B 和 C03C 已经做完、并且已经在 staging 验收通过的用户管理功能发布到了 production。

已经进入 production 的内容：

- C03B 后端 owner-only `/users` 用户管理 API。
- C03C 前端受保护 `/users` 用户管理页面。
- 左侧 System 导航里的 **User Management** 入口。
- owner 可以在网页里进入 User Management，查看用户、创建子账户、停用/启用子账户、重置子账户密码。

production 正式地址：

- `https://ops.barongyekhna.com/users`

## 2. production 当前行为

只读复核结果：

- `https://ops.barongyekhna.com/login` 返回 200。
- `https://ops.barongyekhna.com/users` 返回 200。
- `https://ops.barongyekhna.com/api/backend/health` 返回 production health JSON。
- 未登录访问 `https://ops.barongyekhna.com/api/backend/users` 返回 401。
- `https://ops.barongyekhna.com/api/backend/auth/register` 返回 404。

这说明：

- `/users` 页面已经在 production 可用。
- `/users` API 仍然需要登录和 owner 权限，未登录不会暴露用户列表。
- `/auth/register` 仍然不存在，没有公开注册。
- 当前只支持 owner 创建 `viewer`、`operator`、`reviewer` 子账户。
- 当前不做 `super_admin`。
- 当前不做完整 RBAC 或模块级权限矩阵。

`super_admin`、完整 RBAC、模块权限矩阵、权限继承和更细的业务授权留到 C04/C05。

## 3. 环境验收结果

本轮只读检查结果：

- `./scripts/production_smoke_check.sh` 通过。
- `./scripts/staging_smoke_check.sh` 通过。
- `./scripts/check_dual_env_status.sh` 通过。
- production frontend、backend、postgres 三个容器正常。
- staging frontend、backend、postgres 三个容器正常。

staging 仍然保留为测试服：

- staging 不作为 production 数据来源。
- staging 测试账号不复制到 production。
- staging 仍用于后续功能先验收，再决定是否发布 production。

## 4. 本次没有做什么

本次 C03E-6 只做 production 发布后的只读复核和文档归档。

本次没有：

- 没有新增 migration。
- 没有读取或修改真实 `.env.production`。
- 没有读取或修改真实 `.env.staging`。
- 没有打印 secret、token、password。
- 没有创建 production 真实用户。
- 没有调用 production `/users` API 创建用户。
- 没有操作 production/staging 数据库数据。
- 没有运行 `docker-compose up` 或 `docker-compose down`。
- 没有 stop、restart、rm 任何 production/staging 容器。
- 没有重建或 recreate production/staging 容器。
- 没有修改 Nginx。
- 没有 reload/restart Nginx。
- 没有修改证书，也没有运行 certbot。
- 没有连接真实 n8n、P 系列、WooCommerce、MinIO、Filebrowser。
- 没有创建真实业务任务。
- 没有 git commit。

## 5. 结论

C03E production 发布验收通过。

当前结论：

- C03B 后端 `/users` API 已进入 production。
- C03C 前端 `/users` 用户管理页面已进入 production。
- production owner 可以进入 User Management。
- 未登录访问 `/api/backend/users` 返回 401。
- `/auth/register` 仍然返回 404，没有公开注册。
- production smoke 通过。
- staging smoke 通过。
- dual env check 通过。
- staging 继续保留为测试服。
- 当前仍然没有接真实业务模块。

C03F 已完成 C03 Owner 创建子账户总封板。C03 不包含 `super_admin` 或完整
RBAC；下一阶段是 C04：角色体系。
