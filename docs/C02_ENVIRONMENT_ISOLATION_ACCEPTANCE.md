# C02 Environment Isolation Acceptance

日期：2026-06-09 UTC

## 1. 这次验收做了什么

C02E 是 production / staging 双环境最终验收。它只做只读检查和文档归档：

- 不新增功能。
- 不接真实业务。
- 不修改 Nginx。
- 不申请或更新证书。
- 不启动、停止、重启或删除 production/staging 容器。
- 不读取、打印或修改 `.env.production` / `.env.staging` 内容。
- 不 git commit。

C02A 到 C02E 当前完成情况：

- C02A：看清 production 当前状态，写下 staging 隔离方案。
- C02B：准备 staging compose、`.env.staging.example`、静态检查和 smoke check。
- C02C：在服务器本机启动 staging，初始化 staging owner，完成后端登录链路测试。
- C02D：补双环境运维手册和只读检查脚本。
- C02E：对 production 和 staging 做最终只读验收，确认隔离真实有效。

下一步是 C02F：环境隔离封板。

## 2. production 当前状态

production 正式入口是：

`https://ops.barongyekhna.com`

本次验收结果：

- `https://ops.barongyekhna.com/login` 返回 `200`。
- `https://ops.barongyekhna.com/api/backend/health` 返回 backend health JSON：
  `status=ok`，`service=barong-ops-console-backend`，
  `environment=production`。
- `http://ops.barongyekhna.com/login` 返回 `301`，跳到
  `https://ops.barongyekhna.com/login`。
- frontend 容器是 `barong-ops-console-prod_console_frontend_1`，状态 `Up`，
  只绑定 `127.0.0.1:3000->3000/tcp`。
- backend 容器是 `barong-ops-console-prod_console_backend_1`，状态 `Up`，
  只绑定 `127.0.0.1:8000->8000/tcp`。
- postgres 容器是 `barong-ops-console-prod_console_postgres_1`，状态
  `healthy`，只显示 Docker 内网 `5432/tcp`。
- 宿主机 `5432` 没有监听。
- `./scripts/production_smoke_check.sh` 通过。

结论：production 当前可用，且没有被 staging 端口、network、volume 或容器影响。

## 3. staging 当前状态

staging 当前不暴露公网，只能在服务器本机访问：

`http://127.0.0.1:3100`

本次验收结果：

- `http://127.0.0.1:3100/login` 返回 `200`。
- `http://127.0.0.1:3100/api/backend/health` 返回 backend health JSON：
  `status=ok`，`service=barong-ops-console-backend`，`environment=staging`。
- `http://127.0.0.1:8100/health` 返回 backend health JSON：
  `status=ok`，`service=barong-ops-console-backend`，`environment=staging`。
- frontend 容器是
  `barong-ops-console-staging_console_staging_frontend_1`，状态 `Up`，
  只绑定 `127.0.0.1:3100->3000/tcp`。
- backend 容器是
  `barong-ops-console-staging_console_staging_backend_1`，状态 `Up`，
  只绑定 `127.0.0.1:8100->8000/tcp`。
- postgres 容器是
  `barong-ops-console-staging_console_staging_postgres_1`，状态 `healthy`，
  只显示 Docker 内网 `5432/tcp`。
- 宿主机 `5432` 没有监听。
- `./scripts/staging_smoke_check.sh` 通过。

结论：staging 当前可用，但仍然只作为本机测试服使用。

## 4. 两套环境如何隔离

production 和 staging 使用不同 compose project：

- production：`barong-ops-console-prod`
- staging：`barong-ops-console-staging`

production 和 staging 使用不同容器名：

- production frontend/backend/postgres 都带
  `barong-ops-console-prod_console_...`
- staging frontend/backend/postgres 都带
  `barong-ops-console-staging_console_staging_...`

production 和 staging 使用不同 network：

- production：`barong-ops-console-prod`
- staging：`barong-ops-console-staging`

production 和 staging 使用不同 volume：

- production：`console_postgres_data`
- staging：`console_staging_postgres_data`

production 和 staging 使用不同 env 文件：

- production：服务器本地 `.env.production`
- staging：服务器本地 `.env.staging`

两个真实 env 文件都存在，但本次验收没有读取内容。Git 忽略检查确认：

- `.env.production` 被 Git 忽略。
- `.env.staging` 被 Git 忽略。
- `.env.production.example` 可追踪。
- `.env.staging.example` 可追踪。

## 5. 两套数据库如何隔离

production 数据库：

- 容器：`barong-ops-console-prod_console_postgres_1`
- service：`console_postgres`
- volume：`console_postgres_data`
- network：`barong-ops-console-prod`
- host port：没有暴露 PostgreSQL 端口

staging 数据库：

- 容器：`barong-ops-console-staging_console_staging_postgres_1`
- service：`console_staging_postgres`
- volume：`console_staging_postgres_data`
- network：`barong-ops-console-staging`
- host port：没有暴露 PostgreSQL 端口

`docker-compose.staging.yml` 和 `.env.staging.example` 指向
`console_staging_postgres`，不使用 production 的 `console_postgres`。
宿主机 `5432` 没有监听。

结论：两套数据库不共用容器、network、volume 或 service name。

## 6. 两套 env 如何隔离

真实 env 文件规则：

- `.env.production` 只给 production 用。
- `.env.staging` 只给 staging 用。
- 两个文件都必须只留在服务器本地。
- 两个文件都必须被 Git 忽略。
- 禁止把 secret、token、password 或数据库连接串打印到日志。

本次验收没有 `cat`、没有读取、没有修改真实 env 文件。compose 静态验收用的是
`/tmp` 临时安全目录：

- staging：把 `.env.staging.example` 复制成临时 `.env.staging` 后运行
  `docker-compose -f docker-compose.staging.yml config`。
- production：把 `.env.production.example` 复制成临时 `.env.production` 后运行
  `docker-compose -f docker-compose.production.yml config`。

这两个 config 输出只来自 example 占位值，不来自真实 env。

## 7. 两套端口如何隔离

production 使用：

- frontend：`127.0.0.1:3000`
- backend：`127.0.0.1:8000`
- postgres：Docker 内网 `5432/tcp`，不暴露宿主机

staging 使用：

- frontend：`127.0.0.1:3100`
- backend：`127.0.0.1:8100`
- postgres：Docker 内网 `5432/tcp`，不暴露宿主机

staging 没有使用 production 域名，也没有使用 production 端口。

## 8. 真实业务边界

当前没有接真实业务：

- 没有接真实 n8n workflow。
- 没有接 P 系列。
- 没有接 WooCommerce。
- 没有接 MinIO。
- 没有接 Filebrowser。
- 没有创建真实业务任务。

`N8N_TEST_WEBHOOK_URL` 在 production backend 和 staging backend 中做了不打印值的
空值测试，结果为空。example 文件也保持 `N8N_TEST_WEBHOOK_URL=`。所以当前 n8n
test bridge webhook 未配置，点击测试时安全失败是预期行为，不是生产业务能力。

## 9. 从 staging 发布到 production 的原则

测试服功能要发布到正式服，必须按这个顺序：

1. 同一份 Git commit。
2. 先上 staging。
3. staging 验收通过。
4. owner 批准。
5. 再上 production。
6. production smoke check。
7. 记录结果并封板。

不能把 staging 的 env、数据库、owner、secret、webhook 配置或测试数据复制到
production。

## 10. 本次命令验收结果

本次指定脚本全部通过：

- `./scripts/check_dual_env_status.sh`
- `./scripts/staging_smoke_check.sh`
- `./scripts/production_smoke_check.sh`
- `./scripts/check_staging_deploy_files.sh`
- `./scripts/check_production_deploy_files.sh`

Compose 静态检查全部通过：

- `docker-compose -f docker-compose.example.yml config`
- `docker-compose -f docker-compose.staging.yml config`，在 `/tmp` 安全目录中使用
  临时 `.env.staging`
- `docker-compose -f docker-compose.production.yml config`，在 `/tmp` 安全目录中使用
  临时 `.env.production`

## 11. 当前剩余风险

当前剩余风险和后续事项：

- staging 暂无公网域名。
- `/health` 仍显示 `database: "not_configured"`，因为 health 还没有做真实数据库
  连通性探测。
- n8n test bridge 未配置真实 webhook；安全失败是当前预期。
- SSH 安全加固后续做。
- 旧 Nginx unrelated warning 后续单独处理。

## 12. C02E 结论

C02E 验收通过：

- production 正式服可用。
- staging 测试服可用。
- production/staging 的 project、容器、network、volume、env、端口和数据库隔离
  真实有效。
- production 没有被 staging 影响。
- 当前仍未接真实业务模块。
- 下一步可以进入 C02F 环境隔离封板。
