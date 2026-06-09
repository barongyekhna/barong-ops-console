# C01 Production Acceptance

日期: 2026-06-09 UTC

## 验收范围

C01C 是 Barong Ops Console 的正式部署验收与封板任务。它只验收已上线的
foundation/console production 环境，并归档当前边界；本阶段不接任何真实业务
功能、不接真实 n8n workflow、不接 P 系列、不接 WooCommerce、不接 MinIO 或
Filebrowser。

## C01A 到 C01C 完成内容

- C01A: 接受当前仓库作为第一代空地基，确认 FastAPI backend、PostgreSQL /
  Alembic、owner 认证、Next.js shell、F10 foundation APIs、F11 Foundation
  Demo 和 F12 n8n Test Bridge 已存在，但仍不是业务系统。
- C01B: 准备 production 部署文件，包括 `docker-compose.production.yml`、
  `.env.production.example`、Nginx 模板、部署文档、静态部署文件检查脚本和
  production smoke check 脚本。
- C01C: 验收已上线 production frontend/backend/postgres、正式域名、HTTPS、
  HTTP 跳转、Nginx 语法、证书状态、Docker 暴露面和当前安全边界，并完成封板
  文档归档。

## Production 现状

- 正式域名: `https://ops.barongyekhna.com`
- Owner: 已初始化，并已由人工确认可登录；C01C 不读取或打印 owner 密码。
- Production compose 服务:
  - `console_frontend`: Next.js frontend。
  - `console_backend`: FastAPI backend。
  - `console_postgres`: compose 内网 PostgreSQL。
- 当前实际 Docker 容器名:
  - `barong-ops-console-prod_console_frontend_1`
  - `barong-ops-console-prod_console_backend_1`
  - `barong-ops-console-prod_console_postgres_1`
- Frontend 只绑定宿主机 `127.0.0.1:3000`。
- Backend 只绑定宿主机 `127.0.0.1:8000`。
- PostgreSQL 仅在 Docker 网络内暴露 `5432/tcp`，不暴露宿主机端口，不直接暴露
  公网。
- Nginx 已反代 `ops.barongyekhna.com` 到 console frontend。
- HTTPS 已启用。
- HTTP 已自动跳转 HTTPS。

## 验收证据

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| HTTPS login | 通过 | `https://ops.barongyekhna.com/login` 返回 `200` |
| Backend health proxy | 通过 | `https://ops.barongyekhna.com/api/backend/health` 返回 backend health JSON |
| HTTP 跳转 | 通过 | `http://ops.barongyekhna.com/login` 返回 `301`，跳转到 `https://ops.barongyekhna.com/login` |
| Frontend 容器 | 通过 | `console_frontend` Up，端口为 `127.0.0.1:3000->3000/tcp` |
| Backend 容器 | 通过 | `console_backend` Up，端口为 `127.0.0.1:8000->8000/tcp` |
| PostgreSQL 容器 | 通过 | `console_postgres` Up 且 healthy，`5432/tcp` 没有宿主机绑定 |
| Nginx 语法 | 通过 | `nginx -t` syntax ok/test successful |
| HTTPS 证书 | 通过 | `certbot certificates` 中存在 `ops.barongyekhna.com` 证书 |
| Git 起点 | 通过 | C01C 开始时 `git status --short` 无输出 |

当前 backend health JSON:

```json
{"status":"ok","service":"barong-ops-console-backend","version":"0.1.0","environment":"production","database":"not_configured","external_services":"not_connected"}
```

## HTTPS 证书

- Certificate Name: `ops.barongyekhna.com`
- Domains: `ops.barongyekhna.com`
- Key Type: `ECDSA`
- Expiry Date: `2026-09-07 11:54:59+00:00`
- Certificate Path:
  `/etc/letsencrypt/live/ops.barongyekhna.com/fullchain.pem`
- Private Key Path:
  `/etc/letsencrypt/live/ops.barongyekhna.com/privkey.pem`
- Live directory:
  `/etc/letsencrypt/live/ops.barongyekhna.com`

证书由 certbot 管理；C01C 只读取证书状态，没有申请、更新或续期证书。

## Nginx 备份

当前仓库文档和本轮只读终端记录中没有可靠确认 Nginx 备份路径。需要从终端历史或
`/root/nginx_backup_before_ops_*` 查找。

## 当前非集成边界

- n8n Test Bridge 的 production webhook 仍未配置；点击测试时安全失败是预期
  行为，不会向外部 n8n 发送请求。
- 当前仍未接真实功能。
- 当前仍未接真实 P 系列。
- 当前仍未接真实 n8n workflow。
- 当前仍未接 WooCommerce。
- 当前仍未接 MinIO/Filebrowser。
- 当前不创建真实业务任务，不创建真实产品，不发布真实商品页。

## 已知风险和后续事项

- `/health` 仍显示 `database: "not_configured"`，因为 health 尚未做真实 DB 探测。
- n8n Test Bridge 未配置真实 webhook；这是当前安全边界，不是生产业务能力。
- 旧 Nginx 站点仍有 unrelated warning，包括 443 protocol options 重复和
  `n8n.barongyekhna.com` server name 冲突；这些 warning 不属于 C01。
- SSH 安全加固后续放到 C16 或专门任务。
- C02 后续要做生产/测试环境分离。

## C01 封板结论

C01 从空地基审计、production 部署文件准备、正式域名上线、HTTPS 和反代验收，到
C01C 文档归档已完成。Barong Ops Console production 当前可以作为
foundation/console 使用。

C01 封板成立，但封板范围只覆盖 console foundation production 部署，不代表任何
真实业务链路、真实 n8n workflow、P 系列、WooCommerce、MinIO 或 Filebrowser
已经接入。
