# Barong Ops Console 系统架构

## 1. 系统定位

Barong Ops Console 是 Barong Yekhna 独立站自动化运营系统的统一控制台空地基。它负责统一认证、注册信息、任务状态、产物索引、人工审核、错误追踪、记忆事件和操作审计。

它不是聊天机器人、普通 Dashboard，也不是现有白苏婉企业微信机器人的升级。控制台是系统状态和治理入口；AI Agent、自动化工作流和外部服务只能在受控边界内提供能力，不能绕过控制台直接改变核心状态。

空地基阶段只建设可注册、可追踪、可审核、可回滚的通用基础，不接入真实业务模块，不接真实 P 系列，也不以演示数据伪造业务闭环。

## 2. 总体架构

系统采用前后端分离架构：

- Frontend：Next.js / React / TypeScript。
- Backend：FastAPI / Python。
- Database：PostgreSQL。
- Migration：Alembic。

前端只通过后端公开的受控 API 读取和提交数据，不直接访问 PostgreSQL、n8n、Filebrowser、MinIO 或 WooCommerce。后端负责认证、授权、输入校验、状态转换、审计记录和外部适配。

PostgreSQL 是控制台状态的唯一真相源。任务是否成功、产物是否有效、审核是否通过和错误是否关闭，均以控制台数据库中的受控记录为准。

## 3. 组件职责

### 3.1 Frontend

Next.js / React / TypeScript 前端提供登录、导航、列表、详情、状态展示、审核操作和错误查看界面。除 `/login` 外，控制台页面默认受认证保护。

前端不得自行推断任务成功，不得直接修改跨模块状态，也不得保存真实服务密钥。

### 3.2 Backend

FastAPI / Python 后端提供认证 API、Registry API、Job Manager、Artifact、Review、Error、Memory Event、Operation Log 和外部回调入口。

后端必须实施权限检查、状态机约束、幂等控制和操作审计。所有重要写操作必须留下可追踪记录。

### 3.3 Database

PostgreSQL 保存用户、注册表、任务、任务事件、产物、审核、错误、记忆、操作日志和上下文包。业务状态不能只存在于进程内存、临时文件、浏览器状态或外部执行历史中。

Alembic 是数据库结构变更的唯一迁移机制。F04 只定义文档，不创建 migration。

### 3.4 n8n

n8n 只作为执行引擎，通过测试 Webhook 或后续受控 Adapter 接收任务。n8n 不是认证中心、控制台、数据库或状态真相源。

n8n 的成功或失败都必须携带 `job_id` 回写 Job Manager，并由控制台登记相应任务事件、产物、错误、记忆事件和操作日志。

### 3.5 Filebrowser / MinIO

Filebrowser / MinIO 只作为资产仓库。控制台保存资产索引、元数据、归属和状态，不把外部资产仓库当作任务状态真相源。

空地基施工不得修改现有生产 Filebrowser / MinIO，不得读取其真实密钥，也不得写入真实业务资产。

### 3.6 企业微信

企业微信后续只作为通知和告警通道，不作为复杂任务入口、认证入口或核心状态管理入口。通知失败不能改变控制台中的事实状态。

### 3.7 WooCommerce

WooCommerce 是后续受控外部目标。接入时必须经过独立模块设计、权限限制、审核和审计。

空地基阶段不连接真实 WooCommerce，不执行任何真实 WooCommerce 写操作。

## 4. 核心数据流

1. 已认证用户或受控系统创建 Job。
2. Job Manager 校验已注册且已启用的 Module、Agent 和 Workflow。
3. 执行引擎按受控输入执行任务，并以 `job_id` 报告结果。
4. 控制台记录 `job_events`，将结果登记为 Artifact，失败登记为 Error。
5. 高风险动作创建 Review Item，审核通过前不得执行外部写操作。
6. 有长期意义的事实写入 Memory Event；所有重要动作写入 Operation Log。
7. 下游只消费已登记、状态有效且权限允许的 Artifact 或 Context Packet。

模块之间不得直接修改彼此状态，具体协作约束见 `MODULE_CONTRACT.md`。

### 4.1 C13 Module Switch Gate

C13A 将模块 action execution flow 的架构位置固定为：

```text
C08 -> C13 -> C12 -> C09 -> C10
```

`ModuleSwitchGate` 位于 C08 Module Adapter 之后、C12 Approval System 之前。
它根据 `ModuleSwitchRegistry` 的 `module_key`、`state`、`enabled`、
`disabled_reason` 和 `updated_at` 判断模块是否可继续流转。

规则：

- `ON` -> allow flow to C12。
- `OFF` -> block request。
- `DEPRECATED` -> block request。
- `MAINTENANCE` -> block request。
- missing registry or invalid state -> block request。

C13A 是架构层设计。C13B 已实现运行时 enforcement layer：

- `ModuleSwitchRuntimeGate.check(module_key)` 返回 `ON` / `OFF`。
- C08 adapter module resolution、C12 approval request、C09 execution request 和
  C10 sandbox request 入口前均有 C13B check。
- OFF / missing / invalid / duplicate switch record 均 `BLOCKED`，并停止后续 chain。

被 Module Switch 阻断的请求不得创建 approval request、不得创建 C09 execution
request、不得调用 C10 sandbox、不得触发 runtime execution。`ON` 只表示可以继续接受
C12/C09/C10 的后续 gate，并不表示审批通过或可以执行。C13B 不新增 API、migration、
frontend UI、external provider call、production/staging 操作或真实执行能力。

## 5. 架构原则

- 先地基，后业务。
- 先注册，后运行。
- 先测试，后生产。
- 先 Artifact，后下游。
- 先审核，后高风险动作。
- 先日志，后成功，禁止 silent success。
- 外部执行系统不是状态真相源。
- 生产服务与空地基开发环境保持隔离。

## 6. 空地基边界

空地基允许建设认证、Registry、Job、Artifact、Review、Error、Memory 和 Operation Log 的通用骨架，以及假测试模块和 n8n 测试 Webhook 闭环。

空地基阶段明确禁止：

- 接入真实业务模块或真实 P 系列。
- 连接真实 WooCommerce 或执行真实写操作。
- 修改生产 n8n、Filebrowser、MinIO、白苏婉容器或生产 Docker Compose。
- 读取真实密钥或创建真实 `.env`。
- 用外部执行历史代替数据库状态和审计证据。
