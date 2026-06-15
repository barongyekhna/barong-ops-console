# C14X-E Execution Prompt Generator

日期：2026-06-15 UTC

C14X-E 在 C14X-A/B/C/D 之后增加 Execution Prompt Generator（AI 执行 Prompt
生成器）。本阶段只生成 deterministic prompt、structured input context 和 C09-compatible
draft payload；不执行 AI，不调用模型，不调用外部 API，不创建 C09 execution request，不修改
production/staging，不运行 Docker/pytest，不提交 git commit。

## 1. Prompt Generation Engine Design

Prompt Template Engine 输入固定为：

```text
module_id
capability
model
key
context
```

模板输出分为：

```text
system_boundary
binding_injection
assembled_context
task_context
output_contract
safety_rules
```

实现位置：

- `backend/app/schemas/execution_prompt.py`
- `backend/app/services/execution_prompt_generator.py`
- `backend/app/api/routes/execution_prompts.py`

只读 inspection API：

```text
GET /execution-prompts/template-engine
GET /execution-prompts/validation
GET /execution-prompts/completion-status
```

生成规则：

- deterministic static template only。
- 缺少任何 binding 时 `reject_without_prompt`。
- context 必须是 safe structured context；包含 `.env`、token、credential、Authorization、
  URL、password、webhook/provider endpoint 或类似 runtime-sensitive value 时拒绝。
- prompt 本身是 contract-only artifact，不触发 runtime execution、model invocation 或
  external API call。

## 2. Binding Injection Model

C14X-E binding injection 顺序固定：

```text
C14X-A key binding
-> C14X-B model lock
-> C14X-C capability routing
-> C14X-D module allocation
```

必须注入：

- key binding：来自 C14X-A `AIExecutionBindingRecord`。
- model lock：来自 C14X-B `ModelLockRegistryRecord`。
- capability routing：来自 C14X-C `CapabilityBindingRecord`。
- module allocation：来自 C14X-D `ModuleAllocationRecord`。

强制规则：

- key 必须 exact match。
- model 必须 exact match。
- capability 必须 exact match。
- C14X-A key binding 与 C14X-C capability route 必须 `active`。
- C14X-D module allocation 必须 `active` 且 finite budget 覆盖 requested units。
- 不允许 fallback binding、auto routing、implicit capability access、shared capability
  pool、unlimited AI access。

只读 injection API：

```text
GET /execution-prompts/binding-injection
```

## 3. Execution Payload Structure

C14X-E 生成三个 contract-only 输出：

```text
AIExecutionPrompt
ExecutionPromptStructuredInputContext
C09CompatibleExecutionPromptPayload
```

`AIExecutionPrompt`：

```text
prompt_id
template_id
module_id
capability
key
model
prompt_text
prompt_is_contract_only = true
prompt_executes_ai = false
```

`ExecutionPromptStructuredInputContext`：

```text
context_id
module_context
capability_context
model_context
security_constraints
input_context
```

`C09CompatibleExecutionPromptPayload`：

```text
payload_id
c09_contract_shape = ExecutionRequestContractV1_compatible_draft
module_key = C14X-C routed module
adapter_key = c14x.e.prompt_generator.contract
action_key = c14x.e.generate_prompt_contract
provider_key = c14x.e.contract_only_prompt_provider
provider_type = contract_only_provider
status = draft
input_payload
sanitized_input_summary
execution_requested = false
can_submit_to_c09 = false
creates_execution_request = false
```

Important boundary:

- C09-compatible means field shape alignment for inspection.
- It is not an `ExecutionRequestContractV1` instance.
- It is not submitted to C09.
- It does not create request IDs for runtime execution.
- It does not write operation logs or artifacts.

只读 payload API：

```text
GET /execution-prompts/payload
```

该 API 只接受 query 参数用于 inspection。默认 C14X-A/B/C/D registries 为空，因此实际默认
状态会拒绝生成 prompt，原因是没有 explicit C14X-A key binding。

## 4. Context Assembly Rules

C14X-E context assembly 必须组合：

```text
module_context       <- C14X-D module allocation
capability_context   <- C14X-C capability routing
model_context        <- C14X-B model lock
key context          <- C14X-A key binding
security_constraints <- C14 final seal
input_context        <- sanitized request context
```

Module context 包含：

- C14X-D `module_id`。
- C14X-C routed `module`，用于 C09-compatible `module_key`。
- assigned capabilities。
- bound key/model。
- requested/current units。
- finite budget remaining/window。

Capability context 包含：

- capability。
- key。
- model。
- routed module。
- C14X-C routing path。

Model context 包含：

- key_id。
- requested model。
- C14X-B locked model。
- lock timestamp。

Security constraints 来自 C14 final seal：

- raw secret 不得进入 prompt/context。
- C09 不得直接访问 secret。
- C10 不得接收 raw secret。
- external dependency default decision = deny。
- unknown service decision = quarantine。
- runtime execution/model invocation/external API/production/staging change 全部禁止。

只读 assembly/security API：

```text
GET /execution-prompts/context-assembly
GET /execution-prompts/security-constraints
```

## 5. C14X-E Completion Status

C14X-E completed:

- Prompt Template Engine implemented.
- Binding Injection Model implemented.
- Execution Payload Builder implemented.
- Structured Context Assembly implemented.
- C14 security constraints injection implemented.
- C09-compatible draft payload structure implemented.
- Read-only backend API implemented.
- Frontend proxy exact GET allowlist updated.
- Static backend/frontend regression tests added but not executed per safety rule.

Safety limits preserved:

- no runtime execution
- no external API call
- no model invocation
- no production change
- no staging change
- no docker
- no pytest
- no git commit

C14X-E completion status: complete.

## 6. C14X System Fully Complete

C14X completion chain:

```text
C14X-A binding registry: complete
C14X-B model lock system: complete
C14X-C capability routing: complete
C14X-D module allocation: complete
C14X-E execution prompt generator: complete
```

C14X system fully complete: YES.
