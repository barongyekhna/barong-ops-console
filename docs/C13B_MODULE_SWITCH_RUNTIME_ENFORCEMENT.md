# C13B Module Switch Runtime Enforcement

日期：2026-06-14 UTC

C13B 在 C13A 的设计基础上实现 Module Switch 运行时强制执行层。实现范围只包括
只读静态 registry、runtime gate、入口前置检查和测试覆盖；不新增 API、migration、
production/staging 操作或真实执行能力。

## 1. Runtime Gate Implementation

新增实现：

- `backend/app/schemas/module_switch.py`
- `backend/app/core/module_switches.py`
- `backend/app/services/module_switch_runtime_gate.py`

`ModuleSwitchRuntimeGate` 提供：

```text
check(module_key) -> ON | OFF
decision(module_key) -> ModuleSwitchRuntimeDecision
enforce(module_key) -> allow or raise ModuleSwitchRuntimeBlockedError
```

当前 C13B registry 为静态只读 `MODULE_SWITCH_REGISTRY_V1`，覆盖所有 C07
`MODULE_MANIFESTS_V1` module key。所有已注册 module 初始为 `ON`，未注册、
重复、invalid record 均 fail closed 为 `OFF` / `BLOCKED`。

## 2. Enforcement Integration Points

C13B 插入以下检查点：

| Checkpoint | Implementation |
| --- | --- |
| before C08 module resolution | `build_adapter_access_state()` 先调用 `enforce_module_switch_before_c08_module_resolution()`，OFF 时不解析 module action flow。 |
| before C12 approval request | `ApprovalRequestCreate` / `ApprovalRequest` / `ApprovalContextSnapshot` schema validation 调用 `enforce_module_switch_before_c12_approval_request()`。 |
| before C09 execution request | `ExecutionRequestContractV1` schema validation 调用 `enforce_module_switch_before_c09_execution_request()`。 |
| before C10 sandbox entry | `SandboxRequest` schema validation 调用 `enforce_module_switch_before_c10_sandbox_entry()`，并校验 sandbox module key 与 C09 request module key 一致。 |

## 3. Blocking Flow

当 module switch 为 `OFF`，或 registry missing / invalid：

```text
ModuleSwitchRuntimeGate.check(module_key) -> OFF
ModuleSwitchRuntimeGate.enforce(...) -> BLOCKED
execution_chain_stopped = true
approval_request_allowed = false
execution_request_allowed = false
sandbox_entry_allowed = false
```

阻断结果：

- 不创建 C12 approval request。
- 不生成 C09 execution request contract。
- 不生成 C10 sandbox request。
- 不进入 sandbox bridge/runtime。
- 不触发 external provider、network、queue、worker、webhook 或 callback。

## 4. Allow Flow

当 module switch 为 `ON`：

```text
ModuleSwitchRuntimeGate.check(module_key) -> ON
ModuleSwitchRuntimeGate.enforce(...) -> ALLOWED
```

允许结果：

- request 可继续进入 C12。
- C12 approval 仍然必须按原规则执行。
- C09 execution request 仍受 C09 no-execute/provider contract 边界约束。
- C10 sandbox 仍受 mock-only / disabled-execution / safety lock 约束。
- `ON` 不代表已审批、不代表可执行、不解锁 sandbox。

## 5. Safety Guarantees

C13B 保证：

- no bypass allowed through normal schema/service entrypoints。
- no partial execution request generation when switch is OFF。
- no hidden execution path is added。
- no external call。
- no production or staging change。
- no API or migration。
- no docker run in this task。
- no git commit。
- C12 / C09 / C10 business logic remains unchanged; C13B only adds pre-entry
  enforcement checks and schema-level guards.

## 6. Verification

新增测试：

- `tests/backend/test_module_switch_runtime_gate.py`

更新测试 fixtures，使 C10/C12 mock requests 使用已注册 C07 module keys：

- `tests/backend/test_approval_api.py`
- `tests/backend/test_approval_workflow_engine.py`
- `tests/backend/test_sandbox_execution_context.py`
- `tests/backend/test_sandbox_execution_bridge.py`
- `tests/backend/test_sandbox_runtime_finalization.py`

本地验证状态：

- `python3 -m compileall backend/app`：通过。
- pytest 测试用例未执行：当前可用 Python 环境没有安装 `pytest` / project
  dependencies，定向 pytest 命令在 test collection 前失败；C13B 禁止 docker，不进行
  网络安装。

## 7. C13B Completion Status

C13B runtime enforcement layer 已完成：

- runtime gate implementation：完成。
- enforcement integration points：完成。
- blocking flow：完成。
- allow flow：完成。
- safety guarantees：完成。

可以进入 C13C，前提是 C13C 继续保持 no-production-change 边界，并明确是否要新增
read-only switch API、持久化 registry、UI 或 mutation policy。
