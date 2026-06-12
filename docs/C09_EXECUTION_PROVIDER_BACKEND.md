# C09B Execution Provider Backend Registry

日期：2026-06-12 UTC

C09B 在 C09A Execution Provider 方案基础上，实现后端 Execution Provider
Contract v1、代码内静态 no-op/mock/contract-only/future provider registry、
contract validation、当前用户 access state 和 authenticated read-only API。

C09B 不是执行系统上线。本阶段不提交 execution request，不排队，不运行 action，
不连接 live provider，不写真实业务数据，不新增数据库表，不新增 migration，不新增
前端 UI，不实现 queue/worker/webhook execution，不实现 Module Switch、Approval Gate
或 Secret Rules。

## 实现范围

新增后端文件：

- `backend/app/schemas/execution_provider.py`
- `backend/app/core/execution_providers.py`
- `backend/app/services/execution_provider_registry.py`
- `backend/app/api/routes/execution_providers.py`
- `tests/backend/test_execution_providers_registry.py`

更新：

- `backend/app/main.py` include 新 router。
- `docs/C09_EXECUTION_PROVIDER_PLAN.md` 记录 C09B 状态。
- `README.md`、`CHANGELOG.md`、`backend/README.md` 记录 C09B。

## Execution Provider Contract v1

`ExecutionProviderContractV1` 是声明式 contract，字段包括：

- `provider_key`
- `provider_version`
- `provider_type`
- `provider_status`
- `lifecycle`
- `display_name`
- `description`
- `supported_execution_modes`
- `supported_action_types`
- `module_key`
- `adapter_key`
- `action_key`
- `execution_request_schema`
- `execution_result_schema`
- `execution_state_schema`
- `required_permissions`
- `risk_level`
- `approval_requirement`
- `secret_requirement`
- `scope_requirement`
- `idempotency_policy`
- `retry_policy`
- `timeout_policy`
- `cancellation_policy`
- `concurrency_policy`
- `rate_limit_policy`
- `operation_log_policy`
- `audit_event_policy`
- `artifact_policy`
- `callback_policy`
- `failure_policy`
- `fallback_behavior`
- `unavailable_behavior`
- `test_contracts`
- `docs_path`

C09B 还在 contract 中保留只读安全字段：

- `operation_log_action`
- `requires_execution_provider`
- `requires_approval`
- `executable`
- `can_request_execution`
- `live_provider_connected`
- `external_endpoint_declared`
- `credential_declared`

所有 provider 在 C09B 中：

- `executable=false`
- `can_request_execution=false`
- `live_provider_connected=false`
- `external_endpoint_declared=false`
- `credential_declared=false`

`ExecutionProviderRead` 是安全输出 schema。registry/API 不返回 secret、token、
password、Authorization header、env path、provider URL、webhook URL、credential
或 live endpoint。`secret_requirement` 只能声明 future C14 需求，不读取、不保存、
不返回任何 secret value。action binding 只声明 `module_key`、`adapter_key`、
`action_key`，不执行 action。

## Execution Request / Result / State Schema

C09B 定义 Pydantic 草案 schema，但不创建真实 request、不写数据库。

`ExecutionRequestContractV1` 字段包括：

- `execution_id`
- `request_id`
- `idempotency_key`
- `module_key`
- `adapter_key`
- `action_key`
- `actor_user_id`
- `target_scope`
- `input_payload`
- `sanitized_input_summary`
- `provider_key`
- `provider_type`
- `status`
- `risk_level`
- `required_permission`
- `approval_status`
- `secret_binding_status`
- `created_at`
- `accepted_at`
- `started_at`
- `finished_at`
- `cancelled_at`
- `timeout_at`
- `result_summary`
- `artifact_refs`
- `error_code`
- `error_message_safe`
- `operation_log_id`

`ExecutionResultContractV1` 只允许 safe result summary、safe artifact refs、
safe error code/message 和 optional operation log ref。

`ExecutionStateContractV1` 定义状态机声明。合法 lifecycle status 包括：

- `draft`
- `requested`
- `blocked_permission`
- `blocked_approval_required`
- `blocked_provider_unavailable`
- `accepted`
- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`
- `timed_out`
- `retry_scheduled`
- `skipped`
- `rejected`
- `archived`

C09B 只声明 schema；`execution_request_schema`、`execution_result_schema`、
`execution_state_schema` 均为 `contract_only_no_persistence`。

## Provider Type / Lifecycle

合法 provider type：

- `no_op_provider`
- `mock_provider`
- `contract_only_provider`
- `local_backend_provider`
- `queue_provider`
- `webhook_provider`
- `scheduled_provider`
- `future_live_provider`

合法 `provider_status` / `lifecycle`：

- `draft`
- `contract_ready`
- `test_ready`
- `provider_pending`
- `provider_unavailable`
- `disabled`
- `deprecated`
- `sealed`

规则：

- `no_op_provider`、`mock_provider`、`contract_only_provider` 只用于 contract
  测试和 access-state 验证，不能执行真实业务动作。
- `local_backend_provider`、`queue_provider`、`webhook_provider`、
  `scheduled_provider`、`future_live_provider` 在 C09B 只能是 future /
  `provider_pending` / `disabled` / unavailable 状态。
- `disabled`、`deprecated`、`provider_unavailable` 不可 executable。
- `contract_ready` 只代表 contract 可读，不代表可执行。
- `test_ready` 只代表测试可验证，不代表 production 可执行。
- `sealed` 表示 provider contract 封板。
- C09B 不做 C13 Module Switch，不做 C12 Approval Gate，不做 C14 Secret Rules。

## Static Provider Registry

C09B 第一版使用代码内静态 registry，不新增数据库表，不新增 migration。

初始 provider：

- `core.no_op_provider`
  - `provider_type=no_op_provider`
  - 绑定 `business.products.placeholder.adapter` /
    `business.products.placeholder.prepare`
  - 继承 `products.read`、`medium`、`business.products.placeholder.prepare`
  - 用于 execution-required action 的 no-op contract 阻断验证。
- `core.mock_provider`
  - `provider_type=mock_provider`
  - 绑定 `admin.users.adapter` / `admin.users.read`
  - 继承 `users.read`、`medium`、`user.read`
  - 声明 C18 scope pending，用于 access-state shell 测试。
- `core.contract_only_provider`
  - `provider_type=contract_only_provider`
  - 绑定 `admin.permissions.adapter` / `admin.permissions.manage`
  - 继承 `permissions.manage`、`critical`、
    `permission.assignment.manage`
  - `requires_approval=true`，等待 C12。
- `future.local_backend_provider`
  - `provider_type=local_backend_provider`
  - `provider_status=provider_pending`
  - 不可执行。
- `future.queue_provider`
  - `provider_type=queue_provider`
  - `provider_status=provider_pending`
  - 不创建真实 queue。
- `future.webhook_provider`
  - `provider_type=webhook_provider`
  - `provider_status=disabled`
  - 不连接 external endpoint。
- `future.scheduled_provider`
  - `provider_type=scheduled_provider`
  - `provider_status=disabled`
  - 不创建 scheduler。
- `future.live_provider`
  - `provider_type=future_live_provider`
  - `provider_status=provider_pending`
  - 声明 future secret requirement，等待 C14，不接 live provider。

没有注册任何 live provider，没有注册 provider URL，没有注册 webhook URL，没有注册
credential，没有注册 secret，没有任何 provider action `executable=true`。

## API

C09B 新增两个 authenticated read-only API：

- `GET /execution-providers/registry`
- `GET /execution-providers/me`

两个 API 都要求登录，未登录返回 401。

`GET /execution-providers/registry` 返回安全 provider registry metadata。

`GET /execution-providers/me` 基于当前用户、C05/C06 effective permissions、
C07 module access、C08 adapter access 和 C08 action contract，返回当前用户对
provider/action contract 的可见性和阻断原因。

Access state 字段包括：

- `provider_key`
- `provider_type`
- `provider_status`
- `provider_access_state`
- `module_key`
- `adapter_key`
- `action_key`
- `visible`
- `hidden`
- `locked`
- `unavailable`
- `blocked`
- `block_reason`
- `required_permission`
- `missing_permissions`
- `risk_level`
- `requires_approval`
- `approval_status`
- `requires_secret`
- `secret_binding_status`
- `requires_scope`
- `scope_status`
- `execution_mode`
- `can_request_execution`
- `executable`
- `no_execute_reason`
- `operation_log_action`
- `safe_status_message`

Owner full access 可见 admin provider metadata，但 high-risk /
approval-required action 仍返回 `blocked_approval_required`，不可执行。
Non-owner 不看到 admin execution surface，或得到 `provider_access_state=hidden`。
Business action 无权限时返回 locked/show_locked。`provider_pending`、disabled、
deprecated、unavailable 都不可 executable。

## C08 Action Binding

每个 provider 绑定一个 C08 `action_contract`：

- `module_key` 必须存在于 C07 module registry。
- `adapter_key` 必须存在于 C08 adapter registry。
- `action_key` 必须来自 C08 adapter `action_contracts`。
- `required_permissions` 必须等于 C08
  `action_contract.required_permission`。
- `risk_level` 必须等于 C08 `action_contract.risk_level`。
- `operation_log_action` 必须等于 C08
  `action_contract.operation_log_action`。
- `requires_execution_provider` 必须继承 C08 action contract。
- `requires_approval` 必须继承 C08 action contract，且 high/critical risk
  action 在 C09B 也会被视为等待 C12。

Provider 不能绕过 C05/C06 permission、C07 module isolation 或 C08 adapter
no-execute 规则。

## No-execute Safety Boundary

C09B 的安全边界：

- 不新增 `POST /executions`。
- 不新增 action execution endpoint。
- 不执行 adapter action。
- 不创建 task/job/artifact/request。
- 不写 operation_logs。
- 不实现 queue。
- 不实现 worker。
- 不实现 webhook execution。
- 不实现 live provider execution。
- 不读取 env。
- 不连接 n8n/WooCommerce/MinIO/Filebrowser/live provider。
- 不做 C12 Approval Gate。
- 不做 C13 Module Switch。
- 不做 C14 Secret Rules。
- 不做 C18 formal scope。

`operation_log_policy` 只声明 future log action、details projection 和 redaction
policy，不写真实 `operation_logs`。`artifact_policy` 只声明 safe reference rule，
不创建 artifact。`callback_policy` 不连接 callback。`failure_policy` 只声明 safe error
contract。

## Validation

`validate_execution_provider_contracts()` 覆盖：

- provider key 唯一和命名合法。
- provider version/type/status/lifecycle 合法。
- execution mode/action type 合法。
- C07 module、C08 adapter、C08 action contract 绑定存在。
- required permission、risk level、operation log action 继承 C08。
- approval-required action 不可 executable。
- execution-required action 在 C09B 不可 executable，且只能 no-op 或 pending /
  disabled / unavailable。
- secret requirement 不包含 secret value，不能读取 secret，必须等待 C14。
- 不声明 external endpoint、callback endpoint、credential 或 live provider。
- request/result/state schema 可 JSON 序列化。
- retry/timeout/cancel/idempotency/operation log policy 都存在但 declared-only。
- C05/C06/C07/C08 回归不破坏。

## 测试

新增 `tests/backend/test_execution_providers_registry.py`，覆盖：

- `/execution-providers/registry` 未登录 401。
- `/execution-providers/me` 未登录 401。
- owner 可访问两个只读 API。
- provider key/version/type/status/lifecycle/mode/action type 校验。
- C07 module、C08 adapter、C08 action contract 绑定校验。
- permission/risk/operation log action 继承校验。
- request/result/state schema 可序列化。
- no secret/token/password/env/provider URL/webhook URL/credential。
- approval/execution/secret/scope blocking。
- owner/non-owner/super_admin/role defaults access-state。
- all providers `executable=false`、`can_request_execution=false`。
- `/execution-providers` 只暴露 GET read-only APIs。
- read-only provider registry calls 不写 operation_logs，不创建 jobs/artifacts。
- `/module-adapters/*`、`/modules/*`、`/permissions/me`、C06B assignment API、
  `/users` owner-only、`/auth/register` 404 回归。

## 下一步

C09C 做前端 execution status shell / action submit disabled state。C09C 可以消费
C09B 的 read-only provider registry 和 `/execution-providers/me` access-state，但仍不得
提交真实 execution request，不得执行 adapter action，不得接 live provider。
