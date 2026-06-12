# C09 Execution Provider Plan

日期：2026-06-12 UTC

本文件记录 C09A：Execution Provider 审计与方案设计。

C09A 是只读审计和文档设计任务，不是功能实现任务。本轮不修改 backend runtime
代码，不修改 frontend runtime 代码，不新增 API，不新增 UI，不新增 migration，不发布
staging 或 production，不执行 safe release，不读取真实 env，不执行 adapter action，
不连接 live provider，不创建真实业务任务。

2026-06-12 C09B 补充：后端 Execution Provider contract / no-op provider
registry 已完成，归档在 `docs/C09_EXECUTION_PROVIDER_BACKEND.md`。C09B 新增后端
Execution Provider Contract v1 schema、Execution Request/Result/State schema 草案、
代码内静态 no-op/mock/contract-only/future provider registry、contract validation、
current-user provider access state，以及 authenticated read-only
`GET /execution-providers/registry` 和 `GET /execution-providers/me`。C09B 没有新增
execution submit API，没有新增 queue/worker/webhook/live provider，没有新增 migration，
没有新增前端 UI，没有执行 adapter action，没有读取 env，也没有创建真实任务。

## 一、C09A 结论

C09 可以开始。

C08 Module Adapter 已封板。当前 HEAD 为
`17b371a docs: seal C08 module adapter`，最近提交链确认 C08A-G 已完整承接：

- `1736b5c docs: add C08A module adapter plan`
- `b303ccb feat: add C08B module adapter backend registry`
- `5acb056 feat: add C08C module adapter frontend shell`
- `5bed836 test: add C08D module adapter verification`
- `5943191 docs: add C08E module adapter staging acceptance`
- `6cac036 docs: add C08F module adapter production release`
- `17b371a docs: seal C08 module adapter`

C09 的目标是 Execution Provider 标准。

C09A 只做方案，不实现功能。C09A 不接真实业务，不执行 adapter action，不接 live
provider。

本轮审计确认：

- C05 权限系统已封板，owner full access 全局通过，`super_admin` 不默认全局，
  `role_default_permissions` 不自动生效。
- C06 用户权限管理已封板，grant/update/revoke 写 `operation_logs`，`/users` 仍
  owner-only。
- C07 Module Manifest / Registry 已封板，`planned`、`adapter_pending`、
  `unavailable` 模块不可 executable。
- C08 Module Adapter 已封板，action contract 只声明，不执行，前端 action rows
  disabled，execution-required action 等待 C09，approval-required action 等待 C12。

## 二、为什么需要 Execution Provider

C08 已声明 `action_contract`，但不执行。

后续模块会有 action，例如：

- `run`
- `sync`
- `generate`
- `review`
- `export`
- `publish`

如果没有 Execution Provider，各模块会各自乱调 provider、乱写任务、乱写日志、
乱处理失败：

- action 可能绕过 C05/C06 permission check。
- high-risk action 可能绕过 C12 Approval Gate。
- provider dependency 可能绕过 C14 secret rules。
- n8n/webhook/queue 可能在 C15 前被直接 live connected。
- retry、cancel、timeout 和 failure 语义会分散到每个模块。
- operation log action、result summary、artifact reference 可能不可追踪。

C09 用于建立统一 execution request / provider contract。它让 C08 的 adapter action
先被提交为受控请求，再由后续 provider、queue、worker、webhook 或 n8n connector
按照统一状态机处理。

C09 是 C12 Approval Gate、C14 Secret Rules、C15 live provider 接入的前置标准之一。
C09 不替代这些阶段，只定义执行请求的安全提交、鉴权、阻断、排队、执行、记录、
回传状态、失败处理和审计归档合同。

## 三、Module Adapter 与 Execution Provider 的区别

Module Adapter 是模块接入控制台的合同。

Execution Provider 是 action 执行请求的提交、调度、状态和结果合同。

Adapter 说明“模块能做什么”。它声明 pages、surfaces、capabilities、actions、
action contracts、input/output contracts、permission bindings、operation log bindings
和 dependency declarations。

Execution Provider 说明“一个 action 如何被安全执行或被安全阻断”。它定义 execution
request、provider status、状态机、幂等、retry、cancel、timeout、result、artifact
reference、operation log 和 callback 策略。

C08 只展示 action contract。C09 设计 execution contract。C09A 不执行 action。

边界对照：

| 对象 | 负责 | 不负责 |
| --- | --- | --- |
| Module Adapter | 模块如何把页面、动作、状态、数据契约交给控制台。 | 不提交、不排队、不执行 action。 |
| Execution Provider | action 如何形成 execution request，如何被鉴权、阻断、调度、记录和产生状态/result。 | 不定义模块导航，不保存 secret，不审批 high-risk action。 |
| Approval Gate | high-risk / approval-required action 的审批策略和审批记录。 | 不负责 provider dispatch 或 worker 执行。 |
| Module Switch | 模块启停、feature flag、生效范围。 | 不负责 action execution 状态机。 |
| Secrets Rules | provider credential、secret binding、密钥读取和脱敏规则。 | 不负责提交 action 或执行 worker。 |

## 四、Execution Provider Contract v1 草案

Execution Provider Contract v1 是声明式合同。C09A 只设计字段，不实现 registry、
submit API、queue、worker、webhook 或 callback。

建议字段如下：

| 字段 | 说明 |
| --- | --- |
| `provider_key` | 稳定 provider key，例如 `{module_key}.{action_group}.execution_provider`。必须唯一。 |
| `provider_version` | provider contract version，例如 `1.0.0`。 |
| `provider_type` | provider 类型，例如 `no_op_provider`、`mock_provider`、`queue_provider`。 |
| `provider_status` | provider 可用状态，例如 `contract_only`、`available`、`unavailable`、`disabled`。 |
| `supported_execution_modes` | 支持模式，例如 `contract_only`、`no_op`、`sync_mock`、`queued`、`webhook`、`scheduled`。 |
| `supported_action_types` | 支持 action 类型，例如 `run`、`sync`、`generate`、`review`、`export`、`publish`。 |
| `module_key` | 必须绑定 C07 module registry 中存在的 module。 |
| `adapter_key` | 必须绑定 C08 adapter registry 中存在的 adapter。 |
| `action_key` | 必须来自 C08 adapter `action_contracts`。 |
| `execution_request_schema` | execution request schema ref。 |
| `execution_result_schema` | execution result / safe summary schema ref。 |
| `execution_state_schema` | 状态机和状态转换 schema ref。 |
| `required_permissions` | 执行前需要的 permission，必须继承 C08 `action_contract.required_permission`。 |
| `risk_level` | 必须继承 C08 `action_contract.risk_level`。 |
| `approval_requirement` | 是否要求 approval，必须继承或强化 C08 approval declaration。 |
| `secret_requirement` | provider secret 需求声明，只声明，不读取。 |
| `scope_requirement` | scope 需求声明；C18 前只能 pending/placeholder。 |
| `idempotency_policy` | `request_id`、`idempotency_key`、dedupe window、冲突处理规则。 |
| `retry_policy` | 最大重试次数、可重试错误、退避策略、是否需要人工恢复。 |
| `timeout_policy` | accepted/queued/running timeout 和超时状态转换。 |
| `cancellation_policy` | 可取消状态、取消请求记录、取消失败行为。 |
| `concurrency_policy` | 同一 actor/module/action/target 并发限制。 |
| `rate_limit_policy` | 请求速率限制和被限流状态/错误码。 |
| `operation_log_policy` | 哪些状态转换写 `operation_logs`，details 字段投影和脱敏规则。 |
| `audit_event_policy` | future C17 audit event 映射、严重级别和归档策略。 |
| `artifact_policy` | result/artifact ref 规则，只保存安全引用，不写任意全局状态。 |
| `callback_policy` | provider callback/correlation_id 策略，C09A 只预留。 |
| `failure_policy` | safe error code/summary、是否可 retry、是否归档。 |
| `fallback_behavior` | provider 缺失、scope 未完成、approval 未完成时的降级行为。 |
| `unavailable_behavior` | provider unavailable 时前后端表现。 |
| `test_contracts` | C09D 必须验证的 contract tests。 |
| `docs_path` | provider contract 文档路径。 |

C08 `action_contract` 已经提供 action 的 identity、permission、risk、input/output
contract、operation_log_action、`requires_execution_provider`、`requires_approval`、
`idempotency_policy` 和 `timeout_policy` 的声明性起点。

C09 还需要补：

- execution request identity：`execution_id`、`request_id`、`idempotency_key`。
- execution request 状态机和状态转换规则。
- provider registry / provider status 的合同。
- permission、approval、secret、scope 的阻断状态。
- accepted / queued / running / result / failure / archived 的统一语义。
- retry / cancel / timeout / dedupe 的统一策略。
- result summary / artifact refs / safe error 的脱敏策略。
- operation log 事件、details 投影和审计归档策略。
- live provider、queue、webhook、n8n 的 future boundary。

## 五、Execution Provider 类型

C09 建议定义或预留以下 provider 类型：

| provider_type | 用途 | C09A/C09 初期边界 |
| --- | --- | --- |
| `no_op_provider` | 接受合同但不执行真实动作，用于验证阻断和日志策略。 | C09 第一版可从这里开始。 |
| `mock_provider` | 返回 mock/safe result，用于测试状态机和 UI。 | 只允许 mock，不调用 live provider。 |
| `local_backend_provider` | 未来后端本地同步/短任务执行。 | 不在 C09A 实现。 |
| `queue_provider` | 未来队列提交和 worker 消费。 | C09A 不实现真实队列。 |
| `webhook_provider` | 未来向外部 webhook 提交。 | C09A 不实现 webhook execution。 |
| `scheduled_provider` | 未来计划任务/延迟执行。 | C09A 只预留。 |
| `future_n8n_provider` | 未来 C15 n8n workflow 接入。 | 只作为 C15 预留，不 live connect。 |
| `future_ai_provider` | 未来 AI provider 调用。 | secret-bearing，必须等待 C14。 |
| `future_external_api_provider` | 未来 WooCommerce/SERP/WeCom/Google Sheets 等外部 API。 | secret-bearing，必须等待 C14/C15 或对应阶段。 |

C09 第一版可以从 `no_op_provider` / `mock_provider` / `contract-only provider`
开始。live provider 不在 C09A 做。

`future_n8n_provider` 只作为未来 C15 预留。secret-bearing provider 必须等待 C14。
high-risk action 必须等待 C12 Approval Gate 或显式审批策略，C09 不直接执行。

## 六、Execution Request 生命周期

Execution Request 生命周期建议如下：

| 状态 | 含义 | C09 初版 |
| --- | --- | --- |
| `draft` | 前端或后端组装请求草稿，未提交。 | 可预留。 |
| `requested` | 用户已提交 execution request，尚未完成校验/受理。 | 可实现。 |
| `blocked_permission` | permission check 未通过。 | 可实现。 |
| `blocked_approval_required` | action 需要 C12 approval，但 approval 未完成或 C12 未接入。 | 可实现为阻断。 |
| `blocked_provider_unavailable` | provider 缺失、disabled、contract-only 或 unavailable。 | 可实现为阻断。 |
| `accepted` | permission/provider 基础校验通过，request 被系统受理。 | no-op/mock 初版可实现。 |
| `queued` | request 已进入队列等待 worker。 | future contract。 |
| `running` | provider/worker 正在执行。 | future contract，mock 可模拟。 |
| `succeeded` | 执行成功，产生 safe result summary 和可选 artifact refs。 | no-op/mock 可模拟。 |
| `failed` | 执行失败，返回 safe error code/summary。 | 可实现。 |
| `cancelled` | 已取消，且取消被系统接受。 | future contract。 |
| `timed_out` | 执行超过 timeout policy。 | future contract。 |
| `retry_scheduled` | 失败后按 retry policy 安排重试。 | future contract。 |
| `skipped` | 幂等/dedupe 或前置条件导致跳过执行。 | 可预留。 |
| `rejected` | schema、状态转换或 policy 不允许受理。 | 可实现。 |
| `archived` | request 生命周期结束并归档。 | future contract。 |

C09 初版可以只实现 contract-only/no-op/mock 所需的 `requested`、blocked 状态、
`accepted`、`succeeded`/`failed` 的安全状态流。`queued`、`running`、`retry_scheduled`、
`cancelled`、`timed_out` 和 `archived` 可以先作为 contract 预留，直到真实 queue/worker/
provider 阶段。

## 七、Execution Request schema 草案

Execution Request 是一次 action 执行意图的可审计记录。它不是 C08 action 本身。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `execution_id` | 系统生成的 execution 唯一 ID。 |
| `request_id` | 客户端或边界层 request correlation ID，来自 header 或提交体。 |
| `idempotency_key` | 防重复提交 key，按 actor/module/action/target/input 摘要设计。 |
| `module_key` | C07 module key。 |
| `adapter_key` | C08 adapter key。 |
| `action_key` | C08 action contract key。 |
| `actor_user_id` | 提交用户。 |
| `target_scope` | 执行目标 scope；C18 前只能 adapter_pending/declared/placeholder。 |
| `input_payload` | 原始输入，必须按 schema 校验，未来落库前需脱敏策略。 |
| `sanitized_input_summary` | 脱敏输入摘要，用于日志和 UI。 |
| `provider_key` | 执行 provider key。 |
| `provider_type` | provider 类型。 |
| `status` | 当前 lifecycle status。 |
| `risk_level` | 继承 C08 action contract。 |
| `required_permission` | 继承 C08 action contract。 |
| `approval_status` | `not_required`、`required`、`pending`、`approved`、`rejected` 等 future 状态。 |
| `secret_binding_status` | `not_required`、`declared_only`、`missing`、`bound` 等 future 状态。 |
| `created_at` | 创建时间。 |
| `accepted_at` | 受理时间。 |
| `started_at` | 开始执行时间。 |
| `finished_at` | 结束时间。 |
| `cancelled_at` | 取消时间。 |
| `timeout_at` | 超时时间或超时 deadline。 |
| `result_summary` | 脱敏结果摘要。 |
| `artifact_refs` | 安全 artifact 引用数组。 |
| `error_code` | 稳定错误码。 |
| `error_message_safe` | 可给前端展示的安全错误摘要。 |
| `operation_log_id` | 关键 operation log 的 operation_id 或最终归档 ref。 |

Module Action 和 Execution Request 的区别：

- Module Action 是 adapter 声明的能力合同，稳定存在于 C08 registry。
- Execution Request 是用户对某个 action 的一次提交意图，带 actor、input、scope、
  provider、状态和审计记录。
- 一个 action 可以产生多次 execution request。
- C09 不允许直接把 action 当成执行结果，也不允许绕过 execution request 调 provider。

## 八、Permission / Approval / Scope 规则

action 执行前必须校验 C05/C06 permission。

规则：

- `required_permission` 必须来自 C08 adapter `action_contract`。
- execution request 必须继承 C08 `action_contract.required_permission`、
  `risk_level` 和 `operation_log_action`。
- owner full access 仍全局通过 permission check，但 high-risk action 仍可要求
  approval。
- `super_admin` 不默认全局。
- `role_default_permissions` 不自动生效。
- 非 owner 只能通过 enabled、未过期、registry enabled、scope 匹配的 explicit assignment
  获得有效 permission。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。

Approval 规则：

- C12 未完成前，`approval_required` action 不能自动执行。
- high-risk action 在 C09 是否直接执行：不直接执行，需要为 C12 Approval Gate 预留。
- `risk_level=high` 或 `risk_level=critical`、`requires_approval=true` 或 adapter
  approval requirement 命中时，Execution Provider 只能返回
  `blocked_approval_required`，除非未来 C12 提供明确 approved state。

Scope 规则：

- C18 未完成前，scope 只能 `adapter_pending` / `declared` / `placeholder`。
- C09 不假装正式 company/factory/department scope 已完成。
- C09 不解释公司、工厂、部门归属，不用 scope 文案替代 C05/C06 effective permission
  判断。
- C18 完成后，Execution Request 的 `target_scope` 才能与正式 organization scope adapter
  对齐。

## 九、Operation Logs / Audit 规则

每次 execution request 至少应记录以下事件：

- `execution.requested`
- `execution.blocked`
- `execution.accepted`
- `execution.queued`
- `execution.started`
- `execution.succeeded`
- `execution.failed`
- `execution.cancelled`
- `execution.timed_out`

C09A 只设计，不实现。

`operation_logs.details` 建议包含：

- `actor_user_id`
- `module_key`
- `adapter_key`
- `action_key`
- `execution_id`
- `provider_key`
- `provider_type`
- `status_before`
- `status_after`
- `risk_level`
- `required_permission`
- `idempotency_key`
- `reason`
- `error_code`
- `safe_error_summary`
- `artifact_refs`
- `created_at`

日志规则：

- `operation_logs.action` 可以使用 `execution.requested` 等平台 action，也可以在
  details 中保留 C08 `operation_log_action`。
- action-specific execution success/failure 可通过 C08 `operation_log_action` 追加或映射，
  但不得丢失平台状态事件。
- failed/cancelled/timeout 必须写 `operation_logs`。
- details 必须经过脱敏，不写 password、token、secret、Authorization、API key、provider
  URL、webhook URL、credential。
- C17 才做审计日志页面，C09A 不新增 audit UI。

## 十、Idempotency / Retry / Cancel / Timeout 策略

Idempotency：

- `idempotency_key` 用于防重复提交。
- 建议 key 由 actor、module_key、adapter_key、action_key、target_scope、input payload
  canonical digest、client-provided request key 共同决定。
- 同一 dedupe window 内重复提交应返回既有 `execution_id` 或进入 `skipped`，不得重复
  调 live provider。
- `request_id` 用于 tracing，不等同于幂等 key。

Retry：

- retry 必须受 `retry_policy` 限制。
- 只有明确标记可重试的 safe error 才能进入 `retry_scheduled`。
- provider unavailable 不能静默重试真实服务。
- high-risk 或 approval-required action 的 retry 必须重新验证 approval 仍有效。

Cancel：

- cancel 只能对 `queued`、`running` 等允许状态。
- `succeeded`、`failed`、`timed_out`、`archived` 不应被取消。
- cancel request 必须记录 actor、reason、status_before/status_after 和 operation log。

Timeout：

- timeout policy 应定义 queue wait timeout、running timeout 和 overall timeout。
- timeout 必须写 `operation_logs`。
- timeout 后的 provider callback 如到达，必须按 future callback policy 处理，不得无条件
  覆盖终态。

Failure：

- failed error 只能返回 safe summary，不返回 secret。
- `error_code` 稳定可测试，`error_message_safe` 面向前端，内部 provider 原始错误不得外泄。

C09A 只设计，不实现。

## 十一、Artifact / Result 策略

execution 结果不应直接写任意全局状态。

规则：

- `result_summary` 必须脱敏，只包含 safe summary fields。
- `artifact_refs` 只保存安全引用，例如 artifact id、object id、future artifact subsystem ref。
- 大文件、provider 原始 output、外部响应体、文件上传结果，未来交给 artifact subsystem 或后续
  阶段。
- provider output 不得直接写跨模块状态，除非 C10/C18/C11 后续 contract 明确允许。
- `artifact_refs` 不包含 local filesystem path、provider URL、signed URL、secret-bearing URL
  或 credential。
- C09A 不写真实 artifact。

## 十二、Secrets / Provider Dependency 策略

C09 不读取 env。C09A 不连接 live provider。

规则：

- `secret_requirement` 只声明，不读取。
- C14 才做密钥规则。
- provider URL / token / credential 不得进入 adapter/execution public response。
- external provider live call 必须等待后续明确阶段。
- `secret_binding_status` 在 C09A 只能是 `not_required`、`declared_only` 或 future placeholder。
- secret-bearing provider 必须等 C14 定义 secret storage、binding、read permission、audit 和
  redaction 后才能执行。
- C15 才定义 n8n provider URL/webhook/workflow binding。C09A 只能预留
  `future_n8n_provider`，不得读取 n8n workflow JSON，不得调用 n8n。

Execution Provider 与 Secrets Rules 的区别：

- Execution Provider 定义执行请求如何流转。
- Secrets Rules 定义 provider credential 如何声明、绑定、读取、轮换、脱敏和审计。
- 没有 C14，C09 只能 contract-only/no-op/mock，不能 secret-bearing live execution。

## 十三、前端交互策略

C08C 现在只展示 disabled action contract。

C09 未来可让前端展示 execution request 状态，例如 requested、blocked、accepted、queued、
running、succeeded、failed、cancelled 和 timed_out。

C09A 不实现前端 UI。

前端规则：

- execution-required action 在 C09A 仍显示等待执行提供者。
- approval-required action 仍显示等待审批门。
- provider unavailable 时，前端显示 safe unavailable / blocked message，不显示内部 provider
  配置。
- 后端 provider unavailable 时，应返回 `blocked_provider_unavailable` 或等价 safe error，不创建
  live task，不静默调用 provider。
- `error_message_safe` 不暴露内部信息。
- action 提交入口要等 C09C 或后续阶段，不在 C09A 做。
- 前端权限检查仍只是 UX，后端 permission check 才是安全边界。

## 十四、C09 与后续阶段边界

C09 边界：

- C09：Execution Provider contract / request / provider abstraction。
- C10：模块沙箱，不在 C09A 做。
- C11：模块验收标准，不在 C09A 完整实现。
- C12：Approval Gate，不在 C09A 做。
- C13：Module Switch，不在 C09A 做。
- C14：Secret Rules，不在 C09A 做。
- C15：live n8n 接入规范，不在 C09A 做。
- C17：审计日志页面，不在 C09A 做。
- C18：正式组织结构 / scope，不在 C09A 做。

Execution Provider 和 Approval Gate 的区别：

- Execution Provider 受理和调度 execution request。
- Approval Gate 决定 high-risk / approval-required action 是否被批准。
- C09 在 C12 前必须阻断 approval-required action，不得自建隐式审批。

Execution Provider 和 Module Switch 的区别：

- Execution Provider 处理单次 action execution request。
- Module Switch 处理模块或能力是否启用。
- provider 不能绕过 disabled module/switch；C13 前只使用 C08/C07 pending/disabled
  contract。

Execution Provider 和 live n8n / webhook / queue 的边界：

- Execution Provider 是标准合同，不等于真实 queue、worker、webhook 或 n8n connector。
- C09A 不实现真实队列。
- C09A 不实现真实 worker。
- C09A 不实现 webhook execution。
- C09A 不实现 n8n execution。
- C15 才定义 n8n live 接入规范。

## 十五、C09 建议拆分

### C09A：Execution Provider 审计与方案设计

目标：

- 只读审计 C08 adapter contract、C07 module registry、C05/C06 permission 和
  `operation_logs` 基础。
- 设计 Execution Provider Contract v1。
- 产出 `docs/C09_EXECUTION_PROVIDER_PLAN.md`。
- 更新 README / CHANGELOG / 前后端 README 引用。

允许：

- 只读审计。
- 写文档。
- 跑现有 verify/build/test/smoke/status。

禁止：

- 不新增 API/UI/migration。
- 不改 backend/frontend runtime 代码。
- 不接真实业务。
- 不执行 adapter action。
- 不接 live provider。
- 不发布 staging/production。
- 不 git commit。

验收产物：

- C09A 方案文档。
- README/CHANGELOG 引用。
- 检查命令记录。

### C09B：后端 Execution Provider contract / no-op provider registry

目标：

- 新增后端 Execution Provider contract schema。
- 新增 static/no-op/mock provider registry。
- 校验 provider 绑定 C08 adapter action contract。
- 明确 no-op provider 不执行真实动作。

状态：

- 已完成，记录文件为 `docs/C09_EXECUTION_PROVIDER_BACKEND.md`。
- 新增 `backend/app/schemas/execution_provider.py`，定义
  `ExecutionProviderContractV1`、Execution Request/Result/State schema 草案、
  registry response 和 access-state safe output schema。
- 新增 `backend/app/core/execution_providers.py`，提供 8 个代码内静态 provider：
  `core.no_op_provider`、`core.mock_provider`、`core.contract_only_provider`、
  `future.local_backend_provider`、`future.queue_provider`、
  `future.webhook_provider`、`future.scheduled_provider`、
  `future.live_provider`。
- 新增 `backend/app/services/execution_provider_registry.py`，集中校验 provider key、
  version、type、status、lifecycle、execution mode、action type、C07 module binding、
  C08 adapter/action_contract binding、permission/risk/operation_log 继承、approval /
  execution / secret / no-live / no-write 安全边界和 schema 可序列化。
- 新增 `backend/app/api/routes/execution_providers.py`，提供 authenticated read-only
  `GET /execution-providers/registry` 和 `GET /execution-providers/me`。
- 所有 provider 在 C09B 中 `executable=false`、`can_request_execution=false`。
- `operation_log_policy` 只声明，不写 operation logs。
- `secret_requirement` 只声明，不读取 secret，不返回 credential。
- future local/queue/webhook/scheduled/live provider 均为 provider_pending 或 disabled，
  不连接任何 live provider。

允许：

- 新增后端 contract/schema/validation 代码。
- 新增 no-op/mock registry。
- 新增后端 contract tests。

禁止：

- 不新增 live execution endpoint，除非明确限制为 contract/no-op submit。
- 不实现真实 queue。
- 不实现 worker。
- 不实现 webhook/n8n execution。
- 不读取 env。
- 不接 live provider。
- 不新增 migration，除非另行批准。

验收产物：

- backend Execution Provider schema/registry。
- no-op/mock provider validation。
- C05/C06/C07/C08 回归。

### C09C：前端 execution status shell / action submit disabled state

目标：

- 前端识别 provider status 和 execution-required action 状态。
- 建立 execution status shell / disabled submit placeholder。
- 保持 action submit 不可真实执行，除非 C09B 明确提供 no-op contract submit。

允许：

- 修改前端 helper、provider、placeholder shell、tests。
- 显示 safe execution status。

禁止：

- 不新增真实业务 UI。
- 不连接 live provider。
- 不执行 adapter action。
- 不放宽 proxy 到 `/execution/*` 宽通配。

验收产物：

- execution status placeholder。
- action submit disabled/no-op 状态。
- frontend tests。

### C09D：Execution Provider verify/test 体系

目标：

- 固化 provider key/action binding/idempotency/no-live/no-secret/permission/approval
  tests。
- 验证 C05/C06/C07/C08 不回退。

允许：

- 新增后端 tests。
- 新增前端 Node tests。
- 增强 verify script。

禁止：

- 不新增 runtime feature。
- 不发布。
- 不连接 provider。

验收产物：

- provider_key 唯一测试。
- action_key 必须来自 C08 adapter action_contract 测试。
- no-op/mock 不执行真实动作测试。
- C05/C06/C07/C08 回归。

### C09E：staging Execution Provider 验收

目标：

- 将 C09B/C09C/C09D 的 contract/no-op/mock runtime 发布到 staging。
- 做 staging 只读或 no-op 验收。

允许：

- 按 OPS01 safe release 发布 staging backend/frontend。
- 验证 provider registry、status shell、proxy、tests。

禁止：

- 不发布 production。
- 不接真实业务。
- 不读 env。
- 不操作 postgres。
- 不创建真实任务。
- 不调用 live provider。

验收产物：

- staging acceptance 文档。
- smoke/status 记录。
- provider no-live evidence。

### C09F：production Execution Provider 发布归档

目标：

- 将已验收的 contract/no-op/mock Execution Provider runtime 安全发布到 production。
- 归档 production evidence。

允许：

- 按 OPS01 safe release 发布 production backend/frontend。
- 做只读 production 验收。

禁止：

- 不创建 production 测试账号。
- 不执行真实 action。
- 不操作 production postgres。
- 不读 env。
- 不接 provider。

验收产物：

- production release 文档。
- smoke/status 记录。
- no-live / no-secret / no-action evidence。

### C09G：C09 Execution Provider 封板

目标：

- 归档 C09A-F 完成范围、最终 contract、验收证据和后续边界。

允许：

- 文档封板。

禁止：

- 不新增功能。
- 不发布。
- 不接真实业务。

验收产物：

- C09 final seal 文档。
- 下一阶段进入 C10/C11/C12 等明确任务，而不是真实业务 runtime。

## 十六、测试与验收策略

未来 C09D/C09E/C09F 必须验证：

- execution provider key 唯一。
- action_key 必须来自 C08 adapter action_contract。
- execution_required action 不能绕过 provider。
- approval_required action 不能绕过 C12。
- permission check 必须在 execution 前。
- required_permission / risk_level / operation_log_action 必须继承 C08 action_contract。
- no-op/mock provider 不执行真实动作。
- provider dependency 不包含 secret/token/env/url。
- failed/cancelled/timeout 必须写 operation_logs。
- result_summary 不泄露 secret。
- idempotency_key 防重复。
- request_id 可追踪但不替代 idempotency_key。
- provider unavailable 返回 safe blocked state，不静默重试真实服务。
- retry/cancel/timeout 只能按 policy 状态转换。
- C05/C06/C07/C08 不被破坏。
- `/users` 仍 owner-only。
- `/auth/register` 仍 404。
- `super_admin` 不默认全局。
- `role_default_permissions` 不自动生效。
- dependency declarations 和 provider contract 不包含 provider URL、webhook URL、
  API key、credential 或 Authorization header。
- C09A/C09D 不读取 `.env.production` 或 `.env.staging`。

C09A 本轮建议运行：

- `git status --short --untracked-files=all`
- `git diff --check`
- frontend `npm run verify`
- frontend `npm run typecheck`
- frontend `npm run build`
- frontend Node tests
- backend C08/C07/C05/C06 Docker tests，如环境允许
- production/staging smoke/status 只读脚本

任何因环境原因不可运行的检查必须如实记录，不伪造通过。

## 十七、风险与暂缓项

C09A 明确暂缓：

- 不接真实业务。
- 不执行 adapter action。
- 不接 live provider。
- 不接 n8n。
- 不接 WooCommerce。
- 不接 MinIO/Filebrowser。
- 不实现 Approval Gate。
- 不实现 Module Switch。
- 不实现 Secrets Rules。
- 不实现 formal scope。
- 不读取 env。
- 不创建真实任务。
- 不实现真实队列。
- 不实现真实 worker。
- 不实现 webhook execution。
- 不实现 n8n execution。
- 不新增 API。
- 不新增 UI。
- 不新增 migration。
- 不发布 staging。
- 不发布 production。

主要风险：

- Execution Provider 过早 live 化，会绕过 C12/C14/C15。
- Execution Request 过早写真实任务，会把 contract 阶段误变成业务接入阶段。
- high-risk action 如果在 C12 前执行，会破坏审批边界。
- secret-bearing provider 如果在 C14 前接入，会造成凭据泄露和审计缺口。
- n8n/webhook/queue 如果在 C15 或队列阶段前实现，会形成不可控外部执行路径。

控制策略：

- C09A 只做文档。
- C09B 只做 backend contract/no-op provider registry。
- C09C 只做 frontend status shell / disabled state。
- C09D 固化 no-live/no-secret/no-bypass tests。
- C09E/C09F 仅验收 contract/no-op/mock runtime，不接真实业务。
- C09G 封板后再进入后续明确阶段。
