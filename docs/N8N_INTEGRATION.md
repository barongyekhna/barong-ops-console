# n8n 集成合同

## 1. 定位

n8n 是 Barong Ops Console 的外部执行引擎，不是控制台、认证中心、长期记忆中心或状态真相源。

PostgreSQL 中的 Job、Job Event、Artifact、Error、Memory Event 和 Operation Log 才是控制台判断执行状态和治理结果的依据。不得只依赖 n8n 执行历史、界面状态或 execution id 判断成功。

## 2. 空地基范围

空地基阶段只允许使用专用测试 Webhook 完成假数据闭环：

- 不接真实 P 系列。
- 不接真实 WooCommerce 写操作。
- 不调用生产业务 Workflow。
- 不修改生产 n8n 容器、配置、凭证或现有工作流。
- 不在仓库记录真实 Webhook token 或真实密钥。

测试 Webhook 必须与生产入口隔离，输入只能使用非敏感测试数据。

## 3. 调用前置条件

控制台调用 n8n 前必须：

1. 创建有效 `job_id`。
2. 校验对应 `module_id` 和 `workflow_id` 已注册、active 且合同完整。
3. 校验输入符合 Workflow Registry 中的 schema。
4. 记录发起操作和任务事件。
5. 对高风险动作完成 Review；空地基测试不得包含真实高风险外部写操作。

n8n 不得自行创建不受控的控制台 Job，也不得通过回调扩大原 Job 权限。

## 4. Webhook 请求合同

测试请求至少包含：

- `job_id`
- `workflow_id`
- 输入 schema 版本
- 幂等或关联标识
- 受控测试 payload
- callback 所需的非秘密引用信息

真实凭证不得出现在 payload、日志或 Artifact 中。超时、重试和签名验证方案由 F12 在不连接真实服务的前提下实现和验证。

## 5. Callback 合同

callback 必须携带 `job_id`，并能验证其工作流身份、结果状态和幂等性。

成功和失败都必须回写 Job Manager：

- 成功：记录 Job Event，校验输出，登记 Artifact，再按状态机完成 Job。
- 失败：记录 Job Event，登记 `system_errors`，按状态机将 Job 标记为失败或可重试。
- 状态冲突：拒绝非法转换并记录 Error 和 Operation Log。
- 重复 callback：按幂等规则返回一致结果，不重复创建产物或重复推进状态。
- 未知 `job_id`：拒绝处理并记录安全相关操作日志。

n8n 不得直接写 PostgreSQL，不得直接修改 Review、Artifact 或 Registry 状态。

## 6. 结果登记

n8n 返回结果后，控制台必须按实际情况登记：

- `artifacts`：成功产生的结构化结果或文件索引。
- `system_errors`：失败、超时、输出不合规或状态冲突。
- `memory_events`：对长期上下文有意义的结果事实。
- `operation_logs`：调用、callback、状态处理和最终结果。

上述对象应关联 `job_id`，并在适用时关联 `workflow_id`、`module_id` 和外部 execution reference。

不能因为 n8n HTTP 返回 2xx 就直接认定业务成功。输出 schema、Artifact、必要审核和审计条件未满足时，Job 不得进入成功状态。

## 7. 故障与回滚

- 超时必须形成明确 Job Event 和 Error，不能永久停留在无解释的运行中状态。
- 重试必须使用幂等控制，并保留原失败事实。
- n8n 不可用时，控制台仍应能展示已知状态和错误。
- callback 日志写入失败时不得报告处理成功。
- 外部副作用的补偿和不可回滚风险必须在 Workflow Registry 中声明。

## 8. 生产接入门槛

真实业务接入不属于空地基任务。只有 F13 验收封板后，才可以为具体业务单独设计 Module、Workflow、权限、Review、密钥管理、幂等、回滚和验收方案。

