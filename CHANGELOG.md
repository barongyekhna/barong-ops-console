# Changelog

本项目的重要文档和工程变更记录在此文件中。

## [Unreleased]

### Added

- F12：新增 owner-only `POST /n8n-test/run`、公开但 callback header 鉴权的 `POST /n8n-test/callback`、owner-only `GET /n8n-test/latest`，完成 Console 与 n8n test webhook 闭环。
- F12：新增 `n8n_test_bridge` / `n8n_test_agent` / `n8n_test_webhook_workflow` demo Registry、test Job、callback Job Events、demo Artifact / Review / Memory Event、System Error 与 Operation Logs。
- F12：新增受保护的 `/n8n-test` 页面、Run n8n Test 按钮、waiting callback 自动轮询、latest event / artifact / review / memory / error 展示及 test-only 安全提示。
- F12：新增 webhook 未配置、mock HTTP payload、HTTP failure、callback secret 缺失/错误/正确、demo terminal status、敏感信息隔离和无真实集成测试。
- F11：新增 owner-only `POST /foundation-demo/run` 与 `GET /foundation-demo/latest`，完成 Module / Agent / Workflow / Job / Job Events / Artifact / Review / Memory Event / Operation Logs 演习闭环。
- F11：新增受保护的 Foundation Demo 前端页面、运行按钮、latest 状态展示及明确的 demo-only 外部系统隔离提示。
- F11：新增闭环幂等 Registry、新 Job、多步事件、metadata-only Artifact、pending demo Review、无模型 Memory Event、事务回滚与 failure 审计测试。
- F10：新增 owner-only Registry、Job / Job Event、Artifact、Review、System Error、Memory Event、Context Packet 基础 API，以及只读 Memory Summary / Operation Log API。
- F10：所有基础写入与 `operation_logs` 审计在同一事务提交，并新增 demo 状态、敏感字段、外部 URL、重复键和引用完整性校验。
- F10：Modules、Agents、Workflows、Jobs、Artifacts、Reviews、Errors、Memory Events 前端页面接入真实只读列表，提供 loading、error、empty 和简易卡片状态。
- F10：新增 Registry、Jobs、Artifact / Review / Error、Memory / Operation Log 数据库集成测试及无外部 HTTP 客户端边界检查。
- F09：新增 Next.js / React / TypeScript 前端空壳、`/login`、Dashboard、基础导航和结构化空状态页面。
- F09：新增基于 F08 `login`、`me`、`logout` 认证 API 的前端登录状态、401 清理、受保护路由和退出流程。
- F09：新增 frontend Dockerfile、固定依赖 lockfile、前端 route/safety 验证、TypeScript 检查和 production build 脚本。
- F08：新增 Argon2id 密码哈希、JWT token、owner 幂等初始化 CLI 与 example Docker 脚本。
- F08：新增 `POST /auth/login`、`POST /auth/logout`、`GET /auth/me` 和认证 operation logs。
- F08：新增密码安全、owner bootstrap、登录失败统一响应、停用用户、当前用户和退出审计测试。
- F07：新增 14 张核心空地基表的 SQLAlchemy 模型与单一 Alembic migration。
- F07：新增 schema metadata、字段、主键、稳定业务 ID 唯一约束和 migration 无 seed 测试。
- F07：数据库 Docker 验证脚本新增 migration upgrade、downgrade、再次 upgrade 的完整验证。
- F06：新增 PostgreSQL、SQLAlchemy 与 Alembic 迁移机制骨架，metadata 和 migration versions 保持为空。
- F06：新增 example-only PostgreSQL Compose 服务、数据库配置测试和隔离 Docker 验证脚本。
- F05B：新增后端 Docker 隔离测试脚本和可复现的健康检查验证方式。
- F05：新增 FastAPI / Python 后端空骨架、非敏感应用配置和 `GET /health`。
- F05：新增后端 Dockerfile、示例 Compose 配置和健康检查测试。
- F04：新增架构、模块合同、API 边界、数据库 Schema、认证、n8n 集成、固定任务序列和 Codex 施工规则文档。
- 新增 `docs/FOUNDATION_BLUEPRINT_V1_1.md`，同步 Barong Ops Console 空地基 V1.1 基线。
- 将登录认证、`owner` 初始化账号、受保护页面、用户表和密码哈希存储纳入空地基范围。
- 明确 Registry、Job、Artifact、Review、Memory Event、Operation Log、核心表、技术路线、施工顺序和最终验收标准。

### Changed

- F12：example 配置新增 `N8N_TEST_WEBHOOK_URL`、`N8N_TEST_CALLBACK_SECRET`、`N8N_TEST_REQUEST_TIMEOUT_SECONDS`；URL 默认空并安全失败，示例值仅使用 `example.invalid`。
- F12：数据库 Docker 测试纳入 n8n test bridge API/回调鉴权/审计/失败测试；前端验证纳入 `/n8n-test` 路由、精确 API 代理及 test bridge only 文案。
- F11：数据库 Docker 测试纳入 Foundation Demo API/事务/失败回滚/敏感信息/无外部客户端测试，前端验证纳入 demo 页面和精确 API 代理检查。
- F11：README 明确演习闭环不接真实 n8n、WooCommerce、MinIO/Filebrowser、P 系列或真实业务任务，且不新增 migration。
- F10：数据库 Docker 验证脚本纳入全部 F10 API 测试；前端 foundation 校验要求八个只读 API 接线并阻止外部集成引用。
- F10：README 明确基础 API 仅登记 foundation/demo 数据，不触发真实工作流、不调用模型、不上传文件、不创建真实产品或业务任务。
- F09：example Compose 新增仅依赖 backend 的 frontend 服务，绑定 `127.0.0.1:3000`，不依赖外部业务服务。
- F09：README 明确第一版没有公开注册，除 `/login` 外页面受保护，前端仍不接真实业务模块或外部系统。
- F08：数据库 Docker 验证覆盖认证测试和 owner CLI，并继续执行 migration upgrade、downgrade、再次 upgrade 和清理。
- F08：README 明确第一版禁止公开注册，前端登录页留到 F09，example secret/password 不得用于生产。
- F07：Alembic metadata 现在加载全部核心空地基模型；`/health` 仍不声称已检查数据库。
- F07：README 明确认证、owner 初始化、业务 API、前端和真实业务仍未实现，认证基础留到 F08。
- F06：示例后端通过 `DATABASE_URL` 指向示例数据库；`/health` 仍不检查数据库连接，核心业务表留到 F07。
- F05B：固定后端 Python 直接和传递依赖版本，并调整示例镜像以非 root 用户运行后端和 `pytest`，不依赖系统 Python 环境。
- F05B：示例 Compose 继续仅包含 backend，明确不使用生产路径、真实密钥、数据库或外部服务。
- F04：将空地基工程约束拆分为可独立审查和后续实现引用的专题合同，并固定 F04 至 F13 任务代号。
- 明确第一版禁止公开注册，除 `/login` 外的控制台页面默认要求登录。
- 明确 n8n 仅作为通过 Adapter / Webhook 接入的执行引擎。
- 明确“先地基后业务、先注册后运行、先测试后生产、先 artifact 后下游、先审核后高风险动作、先日志后成功”的施工原则。
- 补充生产环境保护、真实系统隔离、禁止 silent success 和禁止自动跨越人工审核的约束。
