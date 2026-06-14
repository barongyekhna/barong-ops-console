# C13A Module Switch System Design

日期：2026-06-14 UTC

C13A 定义 Module Switch System 的架构层：模块开关 registry、switch state model、
ModuleSwitchGate，以及它在 execution flow 中的位置。

本阶段只做系统设计和架构记录，不实现 runtime execution，不修改 approval logic，
不修改 sandbox，不新增 API，不新增 migration，不运行 docker / pytest，不发布
staging 或 production。

## 1. ModuleSwitchRegistry Design

`ModuleSwitchRegistry` 是模块开关系统的唯一设计入口。它控制某个 `module_key`
是否可以从 C08 adapter action 继续进入后续 approval / execution flow。

C13A registry record:

```text
ModuleSwitchRegistry
  module_key
  state
  enabled
  disabled_reason
  updated_at
```

必需字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `module_key` | string | 模块稳定 key，必须与 C07 Module Registry / C08 Module Adapter 的 `module_key` 对齐。 |
| `state` | `ON` / `OFF` / `DEPRECATED` / `MAINTENANCE` | 模块开关状态。C13A 中只有 `ON` 可继续流转。 |
| `enabled` | boolean | 兼容性布尔读模型。必须满足 `enabled == (state == "ON")`。 |
| `disabled_reason` | string or null | 当 `enabled=false` 时必须给出安全原因摘要；不得包含 secret、token、credential、provider URL 或 raw payload。 |
| `updated_at` | datetime | registry record 最近一次更新的 UTC 时间。 |

Registry invariants:

- `module_key` 必须唯一。
- `module_key` 不存在时必须 fail closed，视为不可进入 execution flow。
- `enabled=true` 只允许出现在 `state=ON`。
- `enabled=false` 必须出现在 `OFF`、`DEPRECATED` 或 `MAINTENANCE`。
- `disabled_reason` 只能是安全摘要，不得成为业务输入、审批理由或 execution payload。
- `updated_at` 是审计元数据，不表示 action request 或 execution request 创建时间。

C13A 不创建数据库表。未来如果 C13B 需要持久化，应单独定义 migration、repository、
read-only / mutation API、权限边界和审计写入策略。

## 2. Switch State Model

C13A 定义四个 switch states：

| State | `enabled` | Gate 行为 | 语义 |
| --- | --- | --- | --- |
| `ON` | `true` | allow flow | 模块开关开启；允许从 C08 继续进入 C12。 |
| `OFF` | `false` | block request | 模块开关关闭；阻断 action request，不创建 approval / execution / sandbox flow。 |
| `DEPRECATED` | `false` | block request | 模块已废弃；C13A 下不可继续进入后续 flow。 |
| `MAINTENANCE` | `false` | block request | 模块维护中；C13A 下不可继续进入后续 flow。 |

最小状态规则：

```text
ON -> allow
OFF -> block
DEPRECATED -> block
MAINTENANCE -> block
missing registry -> block
invalid state -> block
```

C13A 明确实现用户要求的基础规则：

- `OFF` -> block request。
- `ON` -> allow flow。

`DEPRECATED` 和 `MAINTENANCE` 在 C13A 中采用保守默认：block request。未来若需要
read-only surface、maintenance bypass、owner-only override 或 planned sunset policy，
必须进入 C13B+ 单独设计，不能在 C13A 隐式放行。

## 3. ModuleSwitchGate

`ModuleSwitchGate` 是 execution flow 中的前置架构 gate。它不是 executor，不创建
approval request，不创建 execution request，不调用 sandbox。

Gate input:

```text
module_key
adapter_key
action_key
actor_user_id
switch_registry_snapshot
request_time
```

Gate output:

```text
ModuleSwitchGateDecision
  decision: allow | block
  module_key
  state
  enabled
  reason
  evaluated_at
```

Decision rules:

```text
if module_key is missing:
  block(module_switch_not_registered)

if state == ON and enabled == true:
  allow(module_switch_on)

if state == OFF:
  block(module_switch_off)

if state == DEPRECATED:
  block(module_switch_deprecated)

if state == MAINTENANCE:
  block(module_switch_maintenance)

otherwise:
  block(module_switch_invalid_state)
```

Gate guarantees:

- Blocked request stops before C12 Approval System.
- Blocked request does not create or mutate `ApprovalRequest`.
- Blocked request does not create C09 `ExecutionRequestContractV1`.
- Blocked request does not call C10 sandbox runtime or bridge.
- Blocked request does not write operation logs in C13A.
- Allowed request only means "may continue to C12"; it does not approve,
  execute, enqueue, run, dispatch, or unlock sandbox execution.

## 4. Gate Integration Flow

C13A 固定 integration position：

```text
C08 -> C13A -> C12 -> C09 -> C10
```

Expanded flow:

```text
C08 Module Adapter action contract
  -> C13A ModuleSwitchGate
      ON: allow flow
      OFF / DEPRECATED / MAINTENANCE / missing: block request
  -> C12 Approval System
      approval state remains approval-only
  -> C09 Execution Provider
      execution request contract remains no-op/mock/contract-only boundary
  -> C10 Sandbox System
      mock-only / disabled-execution sandbox remains locked
```

Position rules:

- C13A runs after C08 because it evaluates declared module/action intent.
- C13A runs before C12 because disabled modules must not create approval work.
- C13A runs before C09 because disabled modules must not create execution requests.
- C13A runs before C10 because disabled modules must never reach sandbox orchestration.
- C13A does not change C12 decision rules, reviewer permissions, persistence, API, or
  status transitions.
- C13A does not change C09 provider registry, request/result/state schemas, or
  no-execute guarantees.
- C13A does not change C10 mock sandbox, bridge, runtime, resource control, or
  final safety lock.

## 5. System Architecture Update

The module execution architecture now has a module switch gate between adapter
declaration and approval:

```text
Module Manifest / Registry
  -> C08 Module Adapter
  -> C13A Module Switch System
  -> C12 Approval System
  -> C09 Execution Provider
  -> C10 Sandbox System
```

Responsibility boundaries:

| Layer | Responsibility | C13A impact |
| --- | --- | --- |
| C07 Module Registry | Defines module identity/status/visibility. | C13A references `module_key`; it does not replace C07. |
| C08 Module Adapter | Declares pages, actions, contracts, and module/action intent. | C13A gates C08 action intent before approval/execution. |
| C13A Module Switch | Allows or blocks by module switch state. | New architecture layer; design-only in this stage. |
| C12 Approval | Handles approval requests, decisions, workflows, persistence, and permission boundary. | No logic change. Disabled module requests do not enter C12. |
| C09 Execution Provider | Defines execution provider/request/result/state contracts. | No provider or execution logic change. Disabled module requests do not enter C09. |
| C10 Sandbox | Keeps mock-only disabled execution boundary. | No sandbox change. Disabled module requests do not enter C10. |

C13A block semantics:

```text
blocked_by_module_switch
  -> no approval request
  -> no execution request
  -> no sandbox request
  -> no runtime execution
```

C13A allow semantics:

```text
allowed_by_module_switch
  -> continue to C12
  -> still subject to C12 approval
  -> still subject to C09 no-execute/provider boundaries
  -> still subject to C10 disabled-execution sandbox lock
```

## 6. Safety Rules

C13A safety rules are mandatory:

- no execution
- no approval logic change
- no sandbox change
- no runtime execution
- no C09 provider call
- no C10 sandbox call
- no adapter action dispatch
- no queue / worker / webhook / callback
- no external provider connection
- no secret / env read
- no production / staging change
- no migration
- no new API
- no frontend runtime UI
- no operation log write
- no audit event write

`ModuleSwitchGate` is a design contract in C13A. It does not provide a live
runtime gate until a later task explicitly implements it.

## 7. C13A Completion Status

C13A completed:

- `ModuleSwitchRegistry` design defined.
- Switch states `ON`, `OFF`, `DEPRECATED`, and `MAINTENANCE` defined.
- `ModuleSwitchGate` rules defined.
- Required integration position fixed as `C08 -> C13A -> C12 -> C09 -> C10`.
- System architecture update documented.
- Safety rules documented.

No backend runtime code was changed. No frontend runtime code was changed. No
approval logic was changed. No sandbox code was changed. No runtime execution
was introduced.

## 8. C13B Readiness

可以进入 C13B。

C13B 的合理范围可以是：

- backend schema / pure registry contract for `ModuleSwitchRegistry`
- static or persisted registry design
- read-only module switch API design
- permission boundary for switch mutation
- tests for fail-closed gate behavior
- frontend read-only switch status display

C13B 仍必须单独授权，并继续明确不得引入 runtime execution、approval bypass、sandbox
unlock、live provider call、queue / worker / webhook execution 或 production/staging
发布。
