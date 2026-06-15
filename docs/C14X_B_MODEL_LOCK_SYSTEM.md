# C14X-B Model Lock System

日期：2026-06-15 UTC

C14X-B 在 C14X-A AI Execution Binding Registry 之后增加 Model Lock System（模型
锁定系统）。本阶段只定义静态 lock registry、enforcement logic、request validation
和 C14X-A integration；不执行 AI，不调用模型，不调用外部 API，不修改 production 或
staging，不运行 Docker/pytest，不提交 git commit。

## 1. Model Lock Registry Design

核心结构：

```text
ModelLockRegistryRecord
  key_id: string
  model_id: string
  locked: true
  lock_timestamp: UTC ISO-8601 seconds
  lock_reason: string
```

实现位置：

- `backend/app/schemas/model_lock.py`
- `backend/app/core/model_locks.py`
- `backend/app/services/model_lock_registry.py`
- `backend/app/api/routes/model_locks.py`

默认注册表：

```text
MODEL_LOCKS_V1 = ()
```

默认状态没有 model lock，因为 C14X-A 当前默认没有 AI execution binding，也没有
active route。

每条 lock record 固定以下安全字段：

- `one_key_one_model_required = true`
- `model_change_allowed = false`
- `runtime_model_switching_allowed = false`
- `fallback_model_selection_allowed = false`
- `implicit_routing_override_allowed = false`
- `registry_executes_ai = false`
- `runtime_execution_allowed = false`
- `model_invocation_allowed = false`
- `external_api_call_allowed = false`
- `production_change_allowed = false`
- `staging_change_allowed = false`

## 2. Enforcement Logic

C14X-B 强制：

```text
key_id -> model_id
```

规则：

- `key_id` 在 lock registry 内唯一。
- `model_id` 在 lock registry 内唯一，避免同一 model 被多个 lock alias 复用。
- `locked` 必须为 `true`。
- `lock_timestamp` 必须是 UTC ISO-8601 seconds，例如 `2026-06-15T00:00:00Z`。
- `key_id` 必须存在于 C14X-A binding registry。
- `model_id` 必须等于 C14X-A 对应 binding 的 `model`。
- 同一个 `key_id` 一旦绑定到 `model_id`，不能漂移到其他 model。

禁止项：

- runtime model switching。
- fallback model selection。
- implicit routing override。
- orphan model lock。
- C14X-A binding 没有 C14X-B lock。
- lock record 中携带 endpoint、token、credential、Authorization、URL 或其他
  runtime-sensitive value。

## 3. Validation Rules

请求校验逻辑：

```text
declared key_id + requested model_id
-> exact C14X-B lock lookup by key_id
-> requested model_id must equal locked model_id
-> mismatch or missing lock => reject execution
-> match => validation pass only, no runtime execution grant
```

不匹配时返回：

```text
valid = false
lock_validation_passed = false
execution_rejected = true
rejection_code = c14x_b_model_lock_mismatch
```

缺失 lock 时返回：

```text
rejection_code = c14x_b_model_lock_missing
fallback_model_selection_blocked = true
```

匹配时只表示 lock validation 通过：

```text
valid = true
lock_validation_passed = true
execution_rejected = false
runtime_execution_allowed = false
model_invocation_allowed = false
external_api_call_allowed = false
```

只读 API：

```text
GET /model-locks/registry
GET /model-locks/rules
GET /model-locks/enforcement
GET /model-locks/validation
GET /model-locks/request-validation
GET /model-locks/integration
GET /model-locks/completion-status
```

`/model-locks/request-validation` 只做 key/model lock 检查；它不创建 execution request，
不调用 provider，不进入 sandbox。

## 4. Integration With C14X-A

集成关系：

```text
ModelLockRegistryRecord.key_id == AIExecutionBindingRecord.key
ModelLockRegistryRecord.model_id == AIExecutionBindingRecord.model
```

C14X-B 不创建 C14X-A binding，也不修改 C14X-A registry。它只在 C14X-A 已声明的
binding 之后增加不可变 model lock。

一致性要求：

- 每个 C14X-A binding 必须有对应 C14X-B model lock。
- 每个 C14X-B model lock 必须对应一个 C14X-A binding。
- C14X-A/C14X-B key 匹配但 model 不匹配时，registry validation 失败。
- request model 与 locked model 不匹配时，execution 被拒绝。

## 5. C14X-B Completion Status

C14X-B completed:

- Model lock registry structure implemented.
- Immutable `key_id -> model_id` lock mechanism implemented.
- Runtime model switching block implemented.
- Fallback model selection block implemented.
- Implicit routing override block implemented.
- Request validation implemented.
- C14X-A integration validation implemented.
- Read-only backend API implemented.
- Frontend proxy exact GET allowlist updated.
- Static backend/frontend regression tests added but not executed per safety rule.

Safety limits preserved:

- no runtime execution
- no model invocation
- no external API call
- no production change
- no staging change
- no docker
- no pytest
- no git commit

C14X-B completion status: complete.

## 6. Readiness For C14X-C

Can proceed to C14X-C: YES.

Condition:

- C14X-C must remain downstream of C14X-A/C14X-B.
- C14X-C must not treat a model lock validation pass as runtime execution permission.
- C14X-C must not introduce runtime model switching, fallback model selection, implicit
  routing override, model invocation, external API calls, production/staging changes,
  Docker, pytest, or git commit unless separately approved.
