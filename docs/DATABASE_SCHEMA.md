# 数据库 Schema 草案

## 1. 总则

PostgreSQL 是 Barong Ops Console 的状态真相源。本文定义逻辑设计草案，不是 migration，也不锁定最终字段类型、索引名或 Alembic revision。

通用约定：

- 主键建议使用不可猜测的稳定标识。
- 时间字段使用带时区的 UTC 时间。
- 重要记录默认保留历史，禁止通过物理删除破坏审计链。
- JSON 字段必须有对应 schema 版本和应用层校验，不能成为无约束数据桶。
- 外键、唯一约束、非空约束和状态检查由后续 migration 明确实现。

“空地基必需”表示 F13 封板前应存在；“预留”表示设计必须确定，但可按任务顺序延后落表。

## 2. `users`

**用途：** 保存控制台用户和认证状态。第一版仅启用 `owner`。

**关键字段草案：** `id`、`username`、`password_hash`、`role`、`is_active`、`created_at`、`updated_at`、`last_login_at`。

**最低约束：** `username` 唯一且非空；`password_hash` 非空且禁止保存明文；`role` 使用受控枚举；`is_active` 非空；首个有效账号必须为 `owner`。

**空地基必需：** 是。

## 3. `module_registry`

**用途：** 登记模块职责、边界、schema、权限、风险、版本、状态、依赖和治理规则。

**关键字段草案：** `id`、`module_id`、`name`、`responsibilities`、`non_responsibilities`、`input_schema`、`output_schema`、`permissions`、`risk_level`、`version`、`status`、`dependencies`、`artifact_types`、`review_types`、`error_codes`、`healthcheck_config`、`rollback_policy`、`created_at`、`updated_at`。

**最低约束：** `module_id` 唯一且不可为空；版本和状态非空； schema 可验证；active 前合同项必须完整。

**空地基必需：** 是。

## 4. `agent_registry`

**用途：** 登记 Agent 的职责、工具、权限、风险、版本、状态及可调用能力。

**关键字段草案：** `id`、`agent_id`、`name`、`responsibilities`、`non_responsibilities`、`input_schema`、`output_schema`、`permissions`、`risk_level`、`version`、`status`、`allowed_module_ids`、`allowed_workflow_ids`、`dependencies`、`artifact_types`、`review_types`、`error_codes`、`healthcheck_config`、`rollback_policy`、`created_at`、`updated_at`。

**最低约束：** `agent_id` 唯一且非空；引用的 Module 和 Workflow 必须存在；Agent 不得拥有未声明权限；active 前合同完整。

**空地基必需：** 是。

## 5. `workflow_registry`

**用途：** 登记工作流入口、执行引擎、输入输出、回调、超时、重试、风险和生命周期。

**关键字段草案：** `id`、`workflow_id`、`name`、`engine`、`endpoint_ref`、`input_schema`、`output_schema`、`callback_contract`、`permissions`、`risk_level`、`version`、`status`、`dependencies`、`artifact_types`、`review_types`、`error_codes`、`timeout_seconds`、`retry_policy`、`healthcheck_config`、`rollback_policy`、`created_at`、`updated_at`。

**最低约束：** `workflow_id` 唯一且非空；`engine` 和状态非空；不得保存真实密钥；active 前 callback、超时和错误合同完整。

**空地基必需：** 是。

## 6. `automation_jobs`

**用途：** 保存每次受控执行实例及其当前状态。

**关键字段草案：** `id`、`job_id`、`module_id`、`agent_id`、`workflow_id`、`parent_job_id`、`requested_by_user_id`、`status`、`risk_level`、`input_payload`、`input_schema_version`、`idempotency_key`、`correlation_id`、`created_at`、`started_at`、`finished_at`、`updated_at`。

**最低约束：** `job_id` 唯一且非空；至少关联一个已注册 Module；状态使用受控状态机；幂等键在约定范围唯一；成功状态必须满足产物和日志规则。

**空地基必需：** 是。

## 7. `job_events`

**用途：** 追加记录 Job 生命周期和状态变化。

**关键字段草案：** `id`、`job_id`、`event_type`、`from_status`、`to_status`、`actor_type`、`actor_id`、`details`、`created_at`。

**最低约束：** 必须关联有效 `job_id`；事件类型和状态转换合法；事件只追加不覆盖；同一转换应支持幂等去重。

**空地基必需：** 是。

## 8. `artifacts`

**用途：** 登记任务产物的类型、位置、版本、来源、完整性和可用状态。

**关键字段草案：** `id`、`artifact_id`、`job_id`、`module_id`、`artifact_type`、`name`、`storage_provider`、`storage_ref`、`content_hash`、`schema_version`、`version`、`status`、`metadata`、`created_at`、`updated_at`。

**最低约束：** `artifact_id` 唯一；必须关联来源 Job；类型和状态受控；稳定产物必须有完整性标识；不得把未完成临时路径标记为可消费。

**空地基必需：** 是。

## 9. `review_items`

**用途：** 保存人工审核请求、结论、意见和高风险动作放行状态。

**关键字段草案：** `id`、`review_id`、`job_id`、`artifact_id`、`review_type`、`risk_level`、`status`、`requested_by`、`assigned_to`、`decided_by`、`decision`、`comment`、`created_at`、`decided_at`、`updated_at`。

**最低约束：** `review_id` 唯一；必须关联 Job 或 Artifact；高风险结果执行前必须 approved；生成方不得自批；决定后保留历史。

**空地基必需：** 是。

## 10. `system_errors`

**用途：** 集中记录系统、模块、Agent、Workflow 和外部调用错误。

**关键字段草案：** `id`、`error_id`、`error_code`、`severity`、`status`、`message`、`details`、`job_id`、`module_id`、`agent_id`、`workflow_id`、`correlation_id`、`occurred_at`、`acknowledged_by`、`resolved_at`。

**最低约束：** `error_id` 唯一；错误码和严重级别受控；至少关联一个来源或追踪标识；关闭错误不得删除原始事实。

**空地基必需：** 是。

## 11. `memory_events`

**用途：** 记录对长期上下文有意义的结构化事实和状态变化。

**关键字段草案：** `id`、`memory_event_id`、`event_type`、`subject_type`、`subject_id`、`job_id`、`payload`、`schema_version`、`importance`、`created_by_type`、`created_by_id`、`created_at`。

**最低约束：** `memory_event_id` 唯一；事件类型、主体和 schema 版本非空；只记录必要信息；敏感数据遵循最小化原则；记录只追加。

**空地基必需：** 是。

## 12. `operation_logs`

**用途：** 审计用户、系统、Module、Agent 和 Workflow 的重要操作及结果。

**关键字段草案：** `id`、`operation_id`、`actor_type`、`actor_id`、`action`、`target_type`、`target_id`、`job_id`、`result`、`error_code`、`request_id`、`ip_address`、`user_agent`、`details`、`created_at`。

**最低约束：** `operation_id` 唯一；动作、主体、目标、结果和时间非空；只追加；重要写操作必须有日志；日志不得保存密码、token 或真实密钥。

**空地基必需：** 是。

## 13. `context_packets`

**用途：** 保存跨模块或 Agent 交付的最小化、版本化、可授权上下文。

**关键字段草案：** `id`、`context_packet_id`、`source_job_id`、`source_module_id`、`target_module_id`、`target_agent_id`、`schema_version`、`payload`、`artifact_refs`、`access_scope`、`expires_at`、`created_at`。

**最低约束：** `context_packet_id` 唯一；来源和目标明确；payload 通过 schema 校验；权限范围和有效期明确；不得包含未授权或不必要敏感数据。

**空地基必需：** 是，用于建立受控协作边界。

## 14. `memory_summaries`

**用途：** 保存由多个 Memory Event 生成的可追溯摘要，降低长期上下文读取成本。

**关键字段草案：** `id`、`memory_summary_id`、`subject_type`、`subject_id`、`summary`、`source_event_ids`、`schema_version`、`version`、`valid_from`、`valid_until`、`created_at`。

**最低约束：** `memory_summary_id` 唯一；必须引用来源事件；摘要不能覆盖或删除原始事件；版本可追踪。

**空地基必需：** 预留，可在 Memory 基础 API 后按实际需要落表。

## 15. `agent_memory_access_logs`

**用途：** 审计 Agent 对 Memory Event、Memory Summary 和 Context Packet 的读取与使用。

**关键字段草案：** `id`、`access_id`、`agent_id`、`job_id`、`resource_type`、`resource_id`、`purpose`、`access_scope`、`result`、`denial_reason`、`created_at`。

**最低约束：** `access_id` 唯一；必须关联已注册 Agent 和明确目的；允许和拒绝访问均记录；不得记录被访问资源的完整敏感内容。

**空地基必需：** 预留，Agent 实际获得 Memory 读取能力前必须落表。

## 16. 关系与一致性底线

- Registry 记录是 Job 创建的前置条件。
- `automation_jobs` 是执行实例主记录，`job_events` 是其追加式状态历史。
- Artifact、Review、Error、Memory Event 和 Operation Log 应通过 `job_id` 或稳定主体标识建立追踪链。
- n8n execution id 只能作为外部引用，不能替代 `job_id`。
- 日志、错误和审核历史不能因 Registry 停用或 Job 归档而丢失。
- 具体外键删除策略、索引和状态枚举由 F06/F07 在 migration 设计中确认。

