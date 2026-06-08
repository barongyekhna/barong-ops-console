# API 边界合同

## 1. 总则

Barong Ops Console 后端 API 是前端、受控执行引擎和后续外部 Adapter 改变系统状态的唯一入口。前端不得直连数据库，模块不得跨边界直接写其他模块状态。

空地基阶段 API 只提供认证、注册、任务、产物、审核、错误、记忆和日志的基础能力，以及假测试和 n8n 测试 Webhook 所需边界。任何 API 都不得触发真实业务、真实 P 系列或真实 WooCommerce 写操作。

## 2. 通用约定

- API 使用版本化前缀，具体版本方案在后端骨架任务中确定。
- 请求和响应使用明确 schema，禁止依赖未声明字段。
- 受保护端点必须校验登录状态、角色和资源权限。
- 错误响应必须包含稳定错误码、可读消息和追踪标识。
- 创建类请求应支持幂等控制，外部 callback 必须防止重复处理。
- 时间统一使用带时区的 UTC 时间。
- 列表端点应支持分页、过滤和稳定排序。
- 所有写操作必须可审计，并写入 `operation_logs`；有长期意义的事实按规则写入 `memory_events`。
- 重要写操作只有在必要日志成功落库后才能报告成功，禁止 silent success。

## 3. 健康检查

### `/health`

提供应用存活和基础就绪状态。响应不得泄露密钥、连接串或内部敏感配置。

健康检查不能执行真实业务，也不能将 n8n、Filebrowser、MinIO 或 WooCommerce 的生产访问作为空地基存活条件。

## 4. 认证 API

### `/auth/login`

验证用户名和密码，建立受控登录状态。第一版只允许已初始化且启用的 `owner` 登录，不提供公开注册。

### `/auth/logout`

使当前登录状态失效，并记录退出操作。

### `/auth/me`

返回当前用户的最低必要身份、角色和状态信息，不返回 `password_hash` 或其他认证秘密。

## 5. Registry API

### Modules API

提供 Module Registry 的列表、详情及后续受控注册、更新、启用和停用边界。资源标识为 `module_id`。

### Agents API

提供 Agent Registry 的列表、详情及后续受控注册、更新、启用和停用边界。资源标识为 `agent_id`。

### Workflows API

提供 Workflow Registry 的列表、详情及后续受控注册、更新、启用和停用边界。资源标识为 `workflow_id`。

Registry 写操作必须校验合同完整性。未注册、未启用或健康状态不合格的资源不得运行。

## 6. 执行与治理 API

### Jobs API

提供 Job 创建、列表、详情、状态查询、事件查询、受控取消和后续重试边界。资源标识为 `job_id`。

Job 状态只能通过合法状态转换更新；API 不得允许客户端任意指定成功状态。

### Artifacts API

提供 Artifact 列表、详情、元数据登记、版本和状态查询。Artifact API 管理索引和合同，不把临时路径直接当作稳定产物。

### Reviews API

提供 Review Item 列表、详情、领取、通过、驳回和撤销边界。高风险动作必须在审核通过后执行，生成方不能批准自己的高风险结果。

### Errors API

提供系统错误列表、详情、确认、处理状态和关联对象查询。错误关闭必须保留历史，不能物理抹除审计链。

### Memory Events API

提供 Memory Event 的列表、详情和受控创建边界。它记录具有长期上下文价值的事实，不替代 Operation Log。

### Operation Logs API

提供只读查询和受控写入边界。普通客户端不得修改或删除既有操作日志。

## 7. n8n Callback API

n8n callback API 是测试或后续受控工作流向 Job Manager 回报结果的入口。

callback 最低要求：

- 必须携带 `job_id`。
- 必须携带可验证的工作流身份、结果状态和幂等信息。
- 必须校验 Job 与 `workflow_id` 的绑定关系和当前状态。
- 成功和失败都必须回写 Job Manager。
- 成功结果必须登记 Artifact；失败结果必须登记 Error。
- 必须按规则登记 `memory_events` 和 `operation_logs`。
- 重复、过期、未知或状态冲突的 callback 必须明确拒绝并审计。

不得只依据 n8n execution id 或 n8n 执行历史判断任务成功。

## 8. 空地基限制

在 F13 空地基封板前：

- API 不连接真实 WooCommerce。
- API 不调用真实 P 系列。
- n8n 仅允许测试 Webhook。
- Artifact 仅使用测试数据或受控空状态。
- 所有外部写能力保持禁用或不存在。
- API 文档不得包含真实密钥、真实 endpoint token 或生产凭证。

