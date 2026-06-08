# Barong Ops Console 空地基蓝图 V1.1

## 1. 系统总定位

Barong Ops Console 是独立站自动化运营系统的统一控制台，负责统一入口、状态管理、任务调度、资产索引、审核决策、错误追踪、记忆事件和操作日志。

它不是白苏婉企业微信机器人的升级版，不是聊天窗口，也不是普通 Dashboard。

控制台以结构化操作、明确状态、可追踪任务、可审核产物和完整日志为基础。AI 机器人仅用于生成、分析、判断、补全、润色和审核建议，不作为系统主入口，也不能绕过控制台直接改变核心状态。

## 2. 施工原则

所有空地基和后续业务施工必须遵守以下顺序：

1. 先地基，后业务。
2. 先注册，后运行。
3. 先测试，后生产。
4. 先 artifact，后下游。
5. 先审核，后高风险动作。
6. 先日志，后成功。

任何模块、机器人和工作流在完成注册前不得运行。任何任务结果在形成并登记 artifact 前不得交给下游。任何高风险动作必须经过人工审核。任何重要动作必须先完成可验证的日志记录，系统才可以将任务标记为成功；禁止 silent success。

## 3. 系统边界

- Barong Ops Console：统一入口、统一认证、统一状态、统一任务、统一资产、统一审核、统一错误、统一记忆和统一操作日志。
- PostgreSQL：系统状态真相源和长期记忆本体。
- n8n：只作为执行引擎，通过 Adapter 或 Webhook 接入，不作为控制台、认证中心或长期记忆中心。
- AI Agent：提供生成、分析、建议和辅助审核能力，不直接决定核心状态。
- Filebrowser / MinIO：外部资产存储设施，空地基施工不得修改其生产环境。
- 企业微信：未来只可承担通知和告警，不承担复杂任务入口。
- WooCommerce：未来的受控外部目标；空地基阶段不连接真实 WooCommerce，不执行真实写操作。

## 4. 登录认证基础

登录认证属于空地基本体，不是后续可选功能。空地基必须包含：

- `/login` 登录页。
- `owner` 管理员账号。
- 登录 API。
- 退出 API。
- 当前用户 API。
- 登录状态校验。
- 页面保护。
- 未登录访问控制台页面时自动跳转 `/login`。
- 密码哈希存储，禁止明文保存密码。
- `users` 表。
- 基础角色字段。

第一版禁止公开注册，不提供公开注册页面或公开注册 API。系统只允许通过受控初始化流程创建首个 `owner` 管理员账号。

认证实现必须保证：

- 未认证用户只能访问明确允许的公共端点，例如 `/login` 和 `/health`。
- 除 `/login` 外，所有控制台页面默认必须登录后访问。
- 已停用用户不能建立新的有效登录状态。
- 登录成功后更新 `last_login_at`。
- 退出登录后原登录状态失效。
- 登录、退出和认证相关的重要动作进入审计范围。

## 5. 用户表最低要求

`users` 表至少包含：

| 字段 | 最低含义 |
| --- | --- |
| `id` | 用户唯一标识 |
| `username` | 唯一登录名 |
| `password_hash` | 密码哈希，禁止存储明文密码 |
| `role` | 基础角色，首个账号为 `owner` |
| `is_active` | 账号是否启用 |
| `created_at` | 创建时间 |
| `updated_at` | 更新时间 |
| `last_login_at` | 最近成功登录时间，可为空 |

## 6. 空地基页面范围

第一阶段页面范围为：

- `/login`
- Dashboard
- Products
- Modules
- Agents
- Workflows
- Jobs
- Artifacts
- Reviews
- Errors
- Memory Events
- Settings

除 `/login` 外，其他页面默认必须登录后访问。空地基页面可以先提供结构化空状态、列表骨架和导航，但不能伪造真实业务成功状态。

## 7. 核心机制

空地基必须建立以下核心机制：

- **Module Registry**：登记模块职责、边界、版本、状态、权限、输入输出和依赖。
- **Agent Registry**：登记 Agent 的职责、能力、权限、风险等级、版本和可调用工作流。
- **Workflow Registry**：登记工作流入口、输入输出、执行引擎、回调约定、风险等级和状态。
- **Job Manager**：统一创建、执行、追踪和终止任务，管理任务状态及事件。
- **Artifact**：登记任务产物、类型、位置、来源、版本、状态和关联任务。
- **Review**：承载人工审核、结论、意见和高风险动作放行。
- **Memory Event**：记录对长期上下文有意义的重要事件。
- **Operation Log**：记录用户、系统、模块和工作流的重要操作及结果。

所有模块、Agent 和工作流必须先注册后运行。模块之间只能通过受控 API、Job、Artifact、Review、Memory Event 和 Context Packet 协作，不得跨模块直接修改状态或读取未完成任务的临时结果。

## 8. 核心数据表

空地基核心表至少包括：

- `users`
- `module_registry`
- `agent_registry`
- `workflow_registry`
- `automation_jobs`
- `job_events`
- `artifacts`
- `review_items`
- `system_errors`
- `memory_events`
- `operation_logs`
- `context_packets`
- `memory_summaries`
- `agent_memory_access_logs`

数据库是状态真相源。重要状态变化必须可通过任务事件、错误、记忆事件和操作日志追溯。工作流结束后必须按实际结果回写 Job、Artifact、Error、Memory Event 和 Operation Log，不得只依赖 n8n 执行历史。

## 9. 任务、产物、审核与日志规则

任务至少应具备明确的创建、待执行、运行中、成功、失败和取消等状态，并通过 `job_events` 记录状态变化。

执行结果必须先登记为 Artifact，再允许下游消费。下游不得读取未完成任务结果，也不得将临时文件路径当作稳定产物契约。

高风险动作必须创建 Review Item，并在人工审核通过后才能执行。禁止一个模块生成并批准自己的高风险结果，禁止系统自动跨越人工审核。

所有重要动作必须写入 `memory_events` 和 `operation_logs`，至少覆盖：

- 用户登录和退出。
- 模块、Agent、工作流注册或状态变化。
- 任务创建、启动、完成、失败和取消。
- Artifact 创建或状态变化。
- Review 创建、通过、驳回和撤销。
- 错误产生、确认和修复。
- 外部 Adapter / Webhook 调用及回调结果。
- 系统原则和关键设置变化。

日志写入失败时，不得将对应重要动作报告为成功。

## 10. 技术路线

- Frontend：Next.js / React / TypeScript。
- Backend：FastAPI / Python。
- Database：PostgreSQL。
- Migration：Alembic。
- Deployment：Docker Compose。
- n8n：只作为执行引擎，通过 Adapter / Webhook 接入。

生产部署配置与空地基开发配置必须保持边界。施工期间不得修改任何现有生产 Docker Compose 文件。

## 11. V1.1 施工任务顺序

施工必须按以下顺序推进：

1. 任务 0：只读环境审计。
2. 任务 1：创建安全项目目录。
3. 任务 2：写入蓝图文档。
4. 任务 3：Codex 只读施工计划。
5. 任务 3B：同步 V1.1 蓝图。
6. 任务 4：工程文档拆分。
7. 任务 5：后端空骨架。
8. 任务 6：数据库迁移骨架。
9. 任务 7：核心空地基表。
10. 任务 8：认证基础。
11. 任务 9：前端空壳与登录页。
12. 任务 10：Registry / Job / Artifact / Review / Memory 基础 API。
13. 任务 11：假测试模块闭环。
14. 任务 12：n8n 测试 Webhook 闭环。
15. 任务 13：空地基验收与封板。

后续任务必须以本 V1.1 蓝图为准。任何任务不得提前接入真实业务，不得以演示成功代替可追踪、可审核、可复现的闭环。

## 12. 禁止事项

施工期间禁止：

- 修改 `/root`、`/opt/n8n`、`/opt/filebrowser`、`/opt/minio`、`/var/lib/docker`。
- 修改任何生产 Docker Compose 文件。
- 读取或打印真实密钥。
- 停止、重启、删除或修改生产容器。
- 接入真实 P 系列。
- 接入真实 WooCommerce 写操作。
- 开放公开注册。
- 明文保存密码。
- silent success。
- 自动跨越人工审核。
- 在空地基验收前接入复杂真实业务模块。
- 未注册模块、Agent 或工作流直接运行。
- 绕过控制台授权 API 修改核心状态。

## 13. 最终验收标准

任务 13 封板前必须同时满足：

- `/login` 可访问。
- `owner` 可登录。
- 未登录访问控制台页面自动跳转 `/login`。
- 用户可以退出登录，退出后原登录状态失效。
- `/health` 正常。
- Alembic migration 可执行。
- fake-test 模块完成创建任务、记录事件、生成 Artifact、展示结果和记录日志的闭环。
- 测试 n8n callback 完成受控请求、回调校验、任务状态更新和日志记录闭环。
- 所有重要动作写入 `memory_events` 和 `operation_logs`。
- 生产 n8n、Filebrowser、MinIO 和白苏婉容器未被修改。
- 未开放公开注册，密码仅以哈希形式存储。
- 高风险动作不能绕过 Review。
- 不存在 silent success；失败必须有明确状态、错误记录和可追踪日志。

只有全部验收项均有可复现证据时，空地基才能封板并进入真实业务模块的独立设计阶段。
