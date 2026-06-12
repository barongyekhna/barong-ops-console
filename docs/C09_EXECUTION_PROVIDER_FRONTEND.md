# C09C Execution Provider Frontend Shell

日期：2026-06-12 UTC

C09C 在 C09B 后端只读 Execution Provider registry 基础上，实现前端
Execution Provider 类型、只读 API client、execution status shell 和 action submit
disabled state。C09C 不是执行系统上线，不提交 execution request，不执行 adapter
action，不创建真实任务，不连接 live provider，不新增 migration，不发布 staging 或
production。

## 做了什么

C09C 新增前端只读模型：

- `frontend/src/lib/execution-provider.ts`
- `frontend/src/lib/execution-provider-api.ts`
- `frontend/src/components/execution-provider-status-shell.tsx`

并更新 C08C shell：

- `frontend/src/components/adapter-access-provider.tsx`
- `frontend/src/components/module-adapter-shell.tsx`

`AdapterAccessProvider` 现在并行读取 C08 adapter access state 和 C09 provider access
state。`ModuleAdapterShell` 仍展示 C08 `action_contract`，但 action row 会按
`module_key`、`adapter_key`、`action_key` 匹配 C09 provider status，形成
execution-aware but no-execute 的安全展示。

## 前端 Execution Provider 类型

`ExecutionProviderContract` 覆盖 C09B safe registry 字段：

- provider identity/status：`provider_key`、`provider_version`、
  `provider_type`、`provider_status`、`lifecycle`
- action binding：`module_key`、`adapter_key`、`action_key`
- capability/policy：`supported_execution_modes`、`supported_action_types`、
  `required_permissions`、`risk_level`、approval/secret/scope requirements、
  idempotency/retry/timeout/cancellation/operation-log/audit/artifact/callback/
  failure/fallback/unavailable policies
- safe display：`docs_path`、`no_execute_reason`、`safe_status_message`
- no-execute flags：`executable=false`、`can_request_execution=false`

`ExecutionProviderAccessState` 覆盖 C09B `/execution-providers/me` safe response：
provider/access status、visibility/hidden/locked/unavailable/blocked state、
required/missing permissions、approval/secret/scope status、execution mode、
operation log action、`no_execute_reason` 和 `safe_status_message`。

前端 normalize 层强制：

- `executable=false`
- `can_request_execution=false`
- unsafe string values are dropped before rendering
- raw runtime values are never surfaced

## 只读 API Client

`frontend/src/lib/execution-provider-api.ts` 只实现：

- `getExecutionProviderRegistry()` -> `GET /api/backend/execution-providers/registry`
- `getMyExecutionProviders()` -> `GET /api/backend/execution-providers/me`

client 不实现 POST，不实现 run/execute/submit/cancel/retry endpoint，不生成 request body、
request id、idempotency key、artifact ref 或 operation log write。

401/403/404/500 都被转换为 safe unavailable state：

- 401：提示重新登录后读取 provider status。
- 403：提示当前账号无权读取 provider status。
- 404：提示 Execution Provider API unavailable。
- 500+：提示 backend Execution Provider service unavailable。

client 不打印 Authorization header，不打印 token，不打印 env，不打印 backend URL，也不输出
raw error detail。

## Proxy Exact Allowlist

frontend backend proxy 只精确放行：

- `GET /api/backend/execution-providers/registry`
- `GET /api/backend/execution-providers/me`

没有加入宽通配，也没有加入 execution runtime path：

- no `/api/backend/execution-providers/*`
- no `/api/backend/executions/*`
- no `/api/backend/execution/*`
- no execute/run/submit/cancel/retry channel

未登录时，这两个路径仍透传后端 401。`/api/backend/execution-providers/not-allowed`、
`/api/backend/executions` 和 `/api/backend/executions/run` 不在 allowlist，返回 404 或等价拒绝。

## Execution Status Shell

`ExecutionProviderStatusShell` 展示只读状态：

- provider status label
- provider access state
- `no_execute_reason`
- `safe_status_message`
- disabled provider button

该组件不调用 API，不调用 `fetch()`，不调用 `apiRequest()`，不渲染 run/execute/submit/cancel/
retry 按钮。按钮只是 disabled 状态提示，label 为 provider unavailable 类安全文案。

## Action Submit Disabled State

所有 action submit entry point 都保持 disabled 或不渲染。C09C 不做 optimistic execution，
不写 operation logs，不创建 request id，不生成 idempotency key，不生成 artifact refs，不调用
任何 live provider。

`getActionContractState()` 和 `getExecutionProviderActionState()` 都强制：

- `executable=false`
- `can_request_execution=false`
- `disabled=true`

这不是 UI 级临时禁用，而是 C09C 阶段的产品边界：前端只能展示后端 C09B 的 safe read-only
状态，不提交执行意图。

## 接入 C08 Module Adapter Shell

C08 `action_contract` 的后端含义没有改变。C09C 只在前端显示层做增强：

1. `AdapterAccessProvider` 读取 C08 adapter access 和 C09 provider access。
2. `ModuleAdapterShell` 按 action 的 `module_key`、`adapter_key`、`action_key` 匹配 provider。
3. 找不到 provider 时显示 `provider_pending` / waiting for C09 Execution Provider。
4. provider hidden 时显示 hidden 安全文案或不暴露 provider metadata。
5. provider locked 时显示 locked，不允许点击执行。
6. provider unavailable/pending/disabled/deprecated 时显示 unavailable/pending，不允许点击执行。

## Required States

execution-required action：

- shows `waiting for C09 Execution Provider`
- uses `provider_pending` when no provider match exists
- remains disabled

approval-required action：

- shows `waiting for C12 Approval Gate`
- uses `blocked_approval_required`
- remains disabled

secret-required action：

- shows `waiting for C14 Secret Rules`
- uses `secret_rules_required`
- remains disabled

scope-required action：

- shows `waiting for C18 Scope Adapter`
- uses `scope_adapter_pending`
- remains disabled

## Why Executable Is Always False

C09B is contract/read-only provider registry, not execution runtime. C09C consumes that contract and
keeps every frontend provider/action state `executable=false` because C09C has no approved
execution submit API, no queue, no worker, no webhook execution, no Approval Gate result, no Secret
Rules binding, and no formal Scope Adapter.

## Why Can Request Execution Is Always False

`can_request_execution=false` prevents a frontend affordance from implying that a user can submit an
execution request. Until a later approved phase adds a real backend contract for execution requests,
the frontend cannot create request payloads, idempotency keys, request ids, task ids, operation logs
or artifact refs.

## Why No POST / Execute / Run / Submit

C09C is a status shell. Adding POST or execute/run/submit/cancel/retry endpoints here would skip the
C09D verification boundary and could bypass C12 Approval Gate, C14 Secret Rules, C15 live provider
rules, or C18 scope rules. Therefore C09C only uses two GET APIs.

## Why No Live Provider

C09C does not connect n8n, WooCommerce, MinIO, Filebrowser, AI provider, SERP, WeCom, webhooks or
any live provider. Provider dependency and secret-bearing behavior must wait for later approved
stages, especially C14 and C15.

## Sensitive Display Rule

Frontend public render types and shell output must not expose raw secret, token, password, env,
credential, provider URL, webhook URL, backend URL, Authorization header, or raw provider error
values. If a backend response accidentally includes unsafe strings in display fields, frontend
normalization drops them before render and falls back to safe unavailable text.

## Tests

C09C adds `tests/frontend/execution-provider.test.mjs` and updates
`tests/frontend/module-adapter.test.mjs` plus `frontend/scripts/verify-foundation.mjs`.

Coverage includes:

- exact API path markers for `execution-providers/registry` and `execution-providers/me`
- no unsafe wildcard allowlist
- no POST execution provider client
- no run/execute/submit/cancel/retry client path
- provider contract/access state types
- safe status fields
- sensitive value filtering
- `ExecutionProviderStatusShell`
- disabled action button state
- waiting C09/C12/C14/C18 display strategy
- no provider match -> `provider_pending`
- C08 adapter shell remains no-execute

## C09D Boundary

C09D should harden verify/test coverage around provider/action binding, exact proxy behavior,
no-live/no-secret/no-submit guarantees, permission/approval/secret/scope blocking, and C05/C06/C07/C08
regression. C09D should still not add runtime execution, queue, worker, webhook execution, live
provider, staging release, production release or real business tasks unless separately approved.
