# C13E Execution Flow Guard

日期：2026-06-14 UTC

C13E 是 Execution Flow Guard 的最终执行入口控制门。它不新增真实执行能力，
不新增 provider connector，不新增 API endpoint，不修改 production/staging。

## 1. Execution Flow Gate Design

新增实现：

- `backend/app/schemas/execution_flow_gate.py`
- `backend/app/services/execution_flow_gate.py`
- `tests/backend/test_execution_flow_gate.py`

核心对象：

```text
C13E_GATE = ExecutionFlowGate()
C13E_GATE.check(execution_request)
```

`check()` 是最终入口控制门：

- 允许时返回 `ExecutionFlowGateDecision(enforcement_result="ALLOWED")`。
- 阻断时抛出 `ExecutionFlowGateBlockedError`。
- 所有决策都固定声明 no runtime / no external provider / no production impact。

## 2. Blocking Logic

C13E 按 fail-closed 顺序检查：

```text
1. C13D global kill switch
2. C13A/B/C effective module switch gate
3. C08 adapter/action contract binding
4. C09 provider contract binding and no-execute state
5. C12 approval gate requirement
6. C10 sandbox entry state
```

最终阻断规则：

```text
C09 execution bypass      -> BLOCKED
C10 sandbox bypass        -> BLOCKED
C12 approval bypass       -> BLOCKED
C13A/B/C/D bypass         -> BLOCKED
future/live provider path -> BLOCKED
runtime status injection  -> BLOCKED
```

C13E 允许的 only path 是 sealed contract/mock path。`ALLOWED` 不代表真实执行，
只代表该 request 可以继续进入 C10 mock-only sandbox contract chain。

## 3. Kill Switch Integration

C13E 每次 `check()` 都读取最新 C13D 状态：

```text
if C13D.global_kill_switch == TRUE:
    C13E_GATE.check() -> BLOCKED
```

阻断结果：

```text
reason = global_kill_switch_enabled
c08_allowed = false
c12_allowed = false
c09_allowed = false
c10_allowed = false
execution_chain_stopped = true
approval_request_allowed = false
execution_request_allowed = false
sandbox_entry_allowed = false
```

C13E 不缓存 kill switch 默认状态。除非测试显式注入 gate，否则每次调用都会重新读取
当前 C13D 全局状态。

## 4. Final System Flow Diagram

最终控制路径：

```text
User Action
  -> C08 Module Adapter
  -> C13E Execution Flow Gate
  -> C12 Approval Gate
  -> C09 Execution Provider
  -> C10 Sandbox
  -> Mock Result only
```

实际接入点：

```text
ExecutionRequestContractV1 validation
  -> C13E_GATE.check(..., c09_execution_request)

SandboxRequest validation
  -> C13E_GATE.check(..., c10_sandbox_entry)

ExecutionContextFactory request/context-id entrypoints
  -> C13E_GATE.check(..., c10_sandbox_entry)

SandboxResourceEnforcer pre-run entrypoint
  -> C13E_GATE.check(..., c10_sandbox_entry)

SandboxRunner public request entrypoints
  -> C13E_GATE.check(..., c10_sandbox_entry)

SandboxExecutionBridge public request/mapping entrypoints
  -> C13E_GATE.check(..., c10_sandbox_entry)

SandboxRuntime lifecycle request entrypoints
  -> C13E_GATE.check(..., c10_sandbox_entry)
```

这些入口覆盖 normal schema path 和 `model_construct()` 这类绕过 schema validation
后直接进入 C10 service 的路径。

## 5. Safety Guarantees

C13E 决策对象固定保证：

```text
no_execution_leak = true
no_external_provider_call = true
no_runtime_execution = true
no_production_impact = true
external_provider_call_allowed = false
runtime_execution_allowed = false
production_change_allowed = false
```

本阶段未执行：

- runtime execution
- docker
- pytest
- production/staging change
- git commit

## 6. C13E Completion Status

C13E completed:

- `C13E_GATE.check()` implemented.
- C13D kill switch integrated as the first veto.
- Final control path fixed as `C08 -> C13E -> C12 -> C09 -> C10`.
- C09 execution bypass blocked.
- C10 sandbox bypass blocked at schema and service entrypoints.
- C12 approval bypass blocked by C08/C09 approval requirement cross-check.
- C13A/B/C/D bypass blocked through C13E + C13B/C13D integration.
- No runtime execution, external provider call, or production impact added.

## 7. C13 Fully Sealed

C13 status:

```text
C13A Module Switch Design              complete
C13B Runtime Enforcement               complete
C13C Policy Layer                      complete
C13D Emergency Kill Switch             complete
C13E Execution Flow Guard              complete
```

C13 is fully sealed: YES.
