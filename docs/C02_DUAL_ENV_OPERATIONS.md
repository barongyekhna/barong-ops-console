# C02 Dual Environment Operations

日期：2026-06-09 UTC

## 1. 一句话说明

production 是正式服。现在正式入口是：

`https://ops.barongyekhna.com`

staging 是测试服。它现在只在服务器本机开放，不暴露公网。访问入口是：

`http://127.0.0.1:3100`

这两套环境必须当成两套系统看待。代码可以来自同一个 Git commit，但数据库、
volume、network、env、owner 密码和 token secret 都不能混用。

C02F 已完成最终封板。后续真实功能接入必须先上 staging，验收通过并得到 owner
批准后，再发布 production。下一阶段是 C03：Owner 创建子账户。

## 2. 当前真实运行状态

production 当前状态：

- frontend：`barong-ops-console-prod_console_frontend_1`，宿主机
  `127.0.0.1:3000`。
- backend：`barong-ops-console-prod_console_backend_1`，宿主机
  `127.0.0.1:8000`。
- postgres：`barong-ops-console-prod_console_postgres_1`，`healthy`，只在
  Docker 内网使用 `5432/tcp`。
- 域名：`https://ops.barongyekhna.com`。
- env：服务器本地 `.env.production`，必须被 Git 忽略，禁止读取内容。

staging 当前状态：

- frontend：`barong-ops-console-staging_console_staging_frontend_1`，宿主机
  `127.0.0.1:3100`。
- backend：`barong-ops-console-staging_console_staging_backend_1`，宿主机
  `127.0.0.1:8100`。
- postgres：`barong-ops-console-staging_console_staging_postgres_1`，
  `healthy`，只在 Docker 内网使用 `5432/tcp`。
- 公网：暂不暴露。
- env：服务器本地 `.env.staging`，必须被 Git 忽略，禁止读取内容。
- owner：staging owner 已初始化，后端登录链路已测试通过。

## 3. 两套环境的边界

| 项目 | production | staging |
| --- | --- | --- |
| 用途 | 正式服 | 测试服 |
| 对外入口 | `https://ops.barongyekhna.com` | 暂不暴露公网 |
| frontend 容器 | `barong-ops-console-prod_console_frontend_1` | `barong-ops-console-staging_console_staging_frontend_1` |
| backend 容器 | `barong-ops-console-prod_console_backend_1` | `barong-ops-console-staging_console_staging_backend_1` |
| postgres 容器 | `barong-ops-console-prod_console_postgres_1` | `barong-ops-console-staging_console_staging_postgres_1` |
| frontend 端口 | `127.0.0.1:3000` | `127.0.0.1:3100` |
| backend 端口 | `127.0.0.1:8000` | `127.0.0.1:8100` |
| postgres 端口 | Docker 内网 `5432/tcp` | Docker 内网 `5432/tcp` |
| network | `barong-ops-console-prod` | `barong-ops-console-staging` |
| volume | `console_postgres_data` | `console_staging_postgres_data` |
| env 文件 | `.env.production` | `.env.staging` |

production 数据库和 staging 数据库绝不共用。staging 测试数据不能复制到
production。production 的数据也不能为了图方便倒到 staging 里做测试。

## 4. 为什么不能直接手改正式服

staging 测试通过，只能说明这一份代码在测试服跑通了。它不代表可以上服务器去
手改 production 文件、容器、数据库或 Nginx。

不能手改 production 的原因很简单：

- 手改不会留下清晰的 Git 记录，之后不知道线上到底跑了什么。
- 手改可能跳过 staging 验证，把未测试状态放进正式服。
- 手改可能把测试 env、测试 owner、测试数据库 URL 或测试 webhook 带进正式服。
- 手改可能让 production 数据库结构和代码版本不匹配。
- 手改出了问题不好回滚，只能靠猜。

正式服只能按可追踪、可复查、可回滚的发布流程变更。

## 5. 从 staging 发布到 production 的原则

功能从 staging 发布到 production 必须遵守：

1. 同一份 Git commit。staging 验收通过的 commit，才允许考虑发布到
   production。
2. staging 先部署和测试。包括页面、API、迁移、登录链路和 smoke check。
3. owner 批准。没有 owner 明确批准，不推进 production。
4. production 再部署。部署动作必须使用 production 专用 compose project、
   production env 和 production network/volume。
5. production smoke check。部署后必须跑只读 smoke check，确认 login、backend
   health、端口和 postgres 暴露面。
6. 可回滚。发布前要知道回滚到哪个 commit、哪个镜像、哪个数据库迁移状态。

测试服通过之后，production 仍然要单独检查。staging 的数据、owner、secret、
webhook 配置都不能复制到 production。

## 6. n8n 和真实业务边界

C02D/C02E/C02F 不接真实 n8n workflow，不接 P 系列，不接 WooCommerce，不接 MinIO，
不接 Filebrowser，也不创建真实业务任务。

未来如果要接 n8n workflow，也必须版本化：

- workflow 定义要有版本、来源 commit、发布记录和回滚办法。
- 不能在 n8n UI 里手工改完，再靠人工记忆同步到 production。
- staging workflow 和 production workflow 要有清晰环境标识。
- 测试 workflow 不能指向 production 业务系统。
- production workflow 不能靠复制 staging 测试数据来验证。

## 7. 安全只读检查命令

这些命令属于 C02D/C02E/C02F 允许的只读检查。它们不应该启动、停止、重启或删除
production/staging 服务：

```bash
git status --short --untracked-files=all
git check-ignore -v .env.production .env.staging
docker ps --format '{{.Names}}|{{.Status}}|{{.Ports}}'
./scripts/check_dual_env_status.sh
./scripts/staging_smoke_check.sh
./scripts/production_smoke_check.sh
./scripts/check_staging_deploy_files.sh
./scripts/check_production_deploy_files.sh
```

其中 C02E/C02F 已经运行这些脚本，结果全部通过。

Compose config 也只能用安全临时目录跑。做法是把 compose 文件复制到临时目录，
再把 `.env.production.example` 或 `.env.staging.example` 复制成临时同名 env。
这样 `docker-compose -f ... config` 不会读取服务器本地真实 env。

不要在仓库根目录直接对 production/staging compose 跑 config，除非你已经确认
不会读取真实 env 内容。

## 8. 危险命令

这些命令在 C02D/C02E/C02F 禁止执行：

```bash
cat .env.production
cat .env.staging
docker-compose up
docker-compose down
docker-compose restart
docker stop
docker restart
docker rm
docker volume rm
docker network rm
nginx -s reload
systemctl reload nginx
systemctl restart nginx
certbot
```

也不要用 `docker exec` 进入 production 或 staging 数据库里做写操作。只读检查
够用时，不要碰数据库 shell。

## 9. C02D-C02F 边界

C02D 只补文档、只读状态检查脚本和安全边界说明。C02E 只做最终只读验收和文档
归档。C02F 只做最终封板和文档状态更新。

C02D/C02E/C02F 不做这些事：

- 不修改 Nginx。
- 不 reload 或 restart Nginx。
- 不申请或更新证书。
- 不启动、停止、重启或删除 production/staging 容器。
- 不读取或修改 `.env.production` / `.env.staging`。
- 不打印 secret、token、password 或数据库连接串。
- 不接真实 n8n、P 系列、WooCommerce、MinIO 或 Filebrowser。
- 不创建真实业务任务。
- 不 git commit。

## 10. C02F 封板结论

C02E 已经完成 production/staging 双环境最终验收。C02F 已经完成最终封板：

- production login、backend health、HTTP 到 HTTPS 跳转和 smoke check 通过。
- staging login、backend proxy health、backend direct health 和 smoke check 通过。
- 两套环境的 compose project、容器名、network、volume、env 文件、端口和数据库
  均保持隔离。
- `.env.production` 和 `.env.staging` 被 Git 忽略，真实 env 内容未读取。
- `.env.production.example` 和 `.env.staging.example` 可追踪。
- staging 仍不暴露公网，仍未接真实业务。
- n8n test bridge webhook 未配置，安全失败是预期。

验收归档在 `docs/C02_ENVIRONMENT_ISOLATION_ACCEPTANCE.md`。封板记录在
`docs/C02_ENVIRONMENT_ISOLATION_SEAL.md`。

C02 已完成。下一阶段是 C03：Owner 创建子账户。
