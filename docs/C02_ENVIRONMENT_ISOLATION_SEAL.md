# C02 Environment Isolation Seal

日期：2026-06-09 UTC

## 一、C02 最终结论

C02 已经完成 production / staging 双环境隔离。

production 是正式服。正式入口是：

`https://ops.barongyekhna.com`

staging 是测试服。当前只在服务器本机开放，不暴露公网。测试入口是：

`http://127.0.0.1:3100`

以后所有新功能都必须先上 staging，在 staging 验收通过并得到 owner 批准后，才
能发布到 production。不能直接在 production 上试新功能、试迁移、试 webhook
或试真实业务流程。

## 二、C02A-C02F 完成清单

- C02A：完成 production 只读审计和 production/staging 隔离方案。
- C02B：完成 staging 施工图，包括 `docker-compose.staging.yml`、
  `.env.staging.example`、静态检查脚本和 smoke check。
- C02C：完成 staging 本机启动，初始化 staging owner，并测试后端登录链路。
- C02D：完成双环境运维手册和只读状态检查脚本。
- C02E：完成 production/staging 双环境最终只读验收。
- C02F：完成环境隔离最终封板。

## 三、当前双环境状态

production 当前状态：

- 域名：`https://ops.barongyekhna.com`。
- frontend：`barong-ops-console-prod_console_frontend_1`，宿主机
  `127.0.0.1:3000`。
- backend：`barong-ops-console-prod_console_backend_1`，宿主机
  `127.0.0.1:8000`。
- postgres：`barong-ops-console-prod_console_postgres_1`，`healthy`，只在
  Docker 内网使用 `5432/tcp`。
- env：服务器本地 `.env.production`，必须被 Git 忽略，禁止读取内容。

staging 当前状态：

- 公网：暂不暴露。
- frontend：`barong-ops-console-staging_console_staging_frontend_1`，宿主机
  `127.0.0.1:3100`。
- backend：`barong-ops-console-staging_console_staging_backend_1`，宿主机
  `127.0.0.1:8100`。
- postgres：`barong-ops-console-staging_console_staging_postgres_1`，
  `healthy`，只在 Docker 内网使用 `5432/tcp`。
- env：服务器本地 `.env.staging`，必须被 Git 忽略，禁止读取内容。

## 四、隔离规则

production 和 staging 必须一直按两套系统管理：

- 不共用数据库。
- 不共用 env。
- 不共用 Docker project。
- 不共用 network。
- 不共用 volume。
- 不共用端口。
- staging 不接真实业务。
- staging 不使用 production owner 密码。
- staging 不使用 production webhook。

测试数据不能复制到 production。production 数据也不能为了图方便倒到 staging
里做测试。

## 五、发布原则

以后从 staging 发布到 production，必须按这个顺序：

1. 使用同一份 Git commit。
2. 先部署 staging。
3. staging 验收通过。
4. owner 批准。
5. 再部署 production。
6. 跑 production smoke check。
7. 记录结果并封板。

staging 的 env、数据库、owner、secret、webhook 配置和测试数据都不能复制到
production。

## 六、n8n / workflow 未来原则

workflow 也必须版本化。未来接真实 n8n 时，不能在测试服手改 workflow，再靠
人工记忆去正式服照抄。

必须遵守：

- workflow 定义要有版本、来源 commit、发布记录和回滚办法。
- staging webhook 和 production webhook 必须区分。
- staging workflow 不能指向 production 业务系统。
- production workflow 不能靠复制 staging 测试数据来验证。
- 当前 `N8N_TEST_WEBHOOK_URL` 仍为空，安全失败是预期。

## 七、安全禁止项

后续运维和开发禁止做这些事：

- 不允许读取真实 env。
- 不允许把 `.env.production` / `.env.staging` 提交。
- 不允许无 project name 的 `docker-compose up/down`。
- 不允许在 production 上直接试新功能。
- 不允许 staging 连接真实 WooCommerce / MinIO / Filebrowser / P 系列。
- 不允许把 secret、token、password 或数据库连接串打印到日志。
- 不允许测试 webhook 指向 production 业务系统。

## 八、剩余风险与后续任务

当前剩余风险和后续任务：

- staging 暂无公网域名。
- `/health` 仍显示 `database: "not_configured"`，因为 health 还没有做真实数据
  库连通性探测。
- n8n test bridge 未配置真实 webhook；安全失败是当前预期。
- SSH 安全加固后续做。
- 旧 Nginx unrelated warning 后续单独处理。
- 下一阶段 C03：Owner 创建子账户。

## 九、C02 封板结论

C02 已完成并封板。

production / staging 双环境隔离体系已经完成，当前仍未接真实业务。后续所有真实
功能接入都必须遵守 production/staging 隔离原则：先 staging，后 production；
先验收，后发布；测试数据不进正式服。

C02F 复核命令结果：

- `./scripts/check_dual_env_status.sh` 通过。
- `./scripts/production_smoke_check.sh` 通过。
- `./scripts/staging_smoke_check.sh` 通过。
- `./scripts/check_production_deploy_files.sh` 通过。
- `./scripts/check_staging_deploy_files.sh` 通过。
- `docker-compose -f docker-compose.example.yml config` 通过。
- `docker-compose -f docker-compose.production.yml config` 使用临时 example env 通过。
- `docker-compose -f docker-compose.staging.yml config` 使用临时 example env 通过。
- `./scripts/test_foundation_acceptance.sh` 使用 example-only 测试环境通过。

本次 C02F 没有读取或修改真实 env，没有启动、停止、重启或删除 production /
staging 容器，没有修改 Nginx 或证书，没有接真实 n8n、P 系列、WooCommerce、
MinIO、Filebrowser，也没有创建真实业务任务。
