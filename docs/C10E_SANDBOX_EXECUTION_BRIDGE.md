# C10E Sandbox ↔ Execution Provider Bridge

日期：2026-06-14 UTC

C10E 在 C10A-D 之后新增 Sandbox 与 C09 Execution Provider 的桥接层。
本阶段仍然是 mock-only，不进入 C10F，不执行真实 action，不连接 live provider，
不写 production/staging、数据库、operation log、audit event 或文件系统。

## 实现范围

新增：

- `backend/app/sandbox/bridge.py`
- `tests/backend/test_sandbox_execution_bridge.py`

更新：

- `backend/app/sandbox/types.py`
- `backend/app/sandbox/__init__.py`

## Bridge Architecture

核心对象：

- `SandboxExecutionBridge`
  - 接收 `ExecutionRequestContractV1`
  - 绑定 C10C `ExecutionContext`
  - 构造 C10 `SandboxRequest`
  - 生成 `provider_request_mapping`
  - 生成 `sandbox_request_mapping`
  - 将 provider side contract 转发给 `C09MockExecutionProviderInterface`
  - 调用 C10B `SandboxRunner` 产生 deterministic mock result

- `C09MockExecutionProviderInterface`
  - 仅为内存 mock interface
  - 只接收 redacted `C09MockProviderForwardRequest`
  - 只确认 bridge contract 已到达 provider boundary
  - 不选择、不调用 live provider
  - 不使用 queue、webhook、callback、network client

- `BridgeSafetyGuardReport`
  - 对 bridge request、provider mock forward、runner response 做安全核对
  - 所有安全字段保持 false side effect / true safe-result-only

## Bridge Contract Layer

C10E 定义四个必需 contract schema，并额外定义一个 redacted provider forward
envelope：

- `bridge_request`
  - Python model: `BridgeRequest`
  - 包含 C09 execution request、C10C execution context、C10 sandbox request、
    provider mapping、sandbox mapping 和 safety guard。

- `bridge_response`
  - Python model: `BridgeResponse`
  - 包含 provider mock forward response、C10B/C10D sandbox response、
    C09 safe result contract 和最终 C10E safety guard。

- `provider_request_mapping`
  - Python model: `ProviderRequestMapping`
  - 将 `ExecutionRequestContractV1` 映射到
    `C09MockExecutionProviderInterface`。
  - `live_provider_call_allowed=false`
  - `external_provider_call_allowed=false`
  - `network_access_allowed=false`
  - `db_write_allowed=false`
  - `filesystem_access_allowed=false`
  - `raw_input_payload_forwarded_to_provider=false`

- `c09_mock_provider_forward_request`
  - Python model: `C09MockProviderForwardRequest`
  - provider mock interface 实际接收的 redacted request envelope。
  - 不包含 `input_payload` 原文，只包含 identity、risk、permission 和
    `sanitized_input_summary`。

- `sandbox_request_mapping`
  - Python model: `SandboxRequestMapping`
  - 将 `ExecutionRequestContractV1` 和 C10C `ExecutionContext`
    映射到 `SandboxRequest`。
  - `context_bound=true`
  - `resource_control_delegated_to_c10d=true`
  - `runtime_execution_allowed=false`
  - `external_provider_call_allowed=false`
  - `db_write_allowed=false`
  - `filesystem_access_allowed=false`

## Execution Flow Diagram

```text
User Action
  -> C08 Module Adapter
  -> C09 Execution Provider
      emits ExecutionRequestContractV1
  -> C10 Sandbox Bridge
      binds ExecutionContext
      builds provider_request_mapping
      builds sandbox_request_mapping
      forwards redacted contract to C09MockExecutionProviderInterface
  -> C10 Sandbox Runner
      uses C10C ExecutionContext
      applies C10D ResourcePolicy
      simulates lifecycle in memory
  -> Mock result
      returns SandboxResponse
      returns C09 safe ExecutionResultContractV1
      returns BridgeResponse
```

## Bridge Mode Types

全部 mode 都是 mock-only：

- `passthrough_mock_mode`
  - bridge 透传 C09 contract 到 C10 sandbox runner 的 mock lifecycle。
  - provider side 只转发到 C09 mock interface。

- `dry_run_mode`
  - bridge 生成 mapping 和 safety guard，并让 runner 产生 dry-run mock result。
  - 不创建真实 runtime，不调用 provider。

- `simulation_mode`
  - bridge 显式标记 deterministic mock simulation。
  - lifecycle 仍由 C10B runner 在内存中模拟。

## Integration With C10B + C10C

C10E 不替换 C10B/C10C：

- C10C
  - `ExecutionContextFactory` 为每个 `ExecutionRequestContractV1`
    生成 deterministic request-scoped context。
  - bridge 将 `context_id`、`execution_context_ref`、memory/log/state scope
    绑定到 `SandboxRequestMapping` 和 `SandboxRequest`。

- C10B
  - `SandboxRunner.build_sandbox_request()` 仍负责把 C09 request 变成
    runner 可消费的 `SandboxRequest`。
  - `SandboxRunner.run()` 仍负责 deterministic mock lifecycle。

- C10D
  - `SandboxResourceEnforcer` 仍在 runner 内部附加 logical-only resource policy。
  - 网络、external API、OS enforcement、filesystem 越界能力继续被 mock policy 拦截。

C10B runner 自身仍返回 `next_stage_policy="wait_for_c10e"`；C10E 外层
`BridgeResponse` 返回 `next_stage_policy="wait_for_c10f"`。

## Safety Guarantees

C10E 保证：

- no real execution
- no subprocess / worker / container / shell runtime
- no external provider call
- no live provider connector
- no queue / webhook / callback
- no network client
- no production/staging access or mutation
- no database write
- no operation-log write
- no audit-event write
- no filesystem access by bridge
- no filesystem write by runner
- no raw input payload echo to provider response
- safe-result-only C09 result contract

这些保证由以下字段共同表达：

- `BridgeSafetyGuardReport.runtime_created=false`
- `BridgeSafetyGuardReport.external_provider_called=false`
- `BridgeSafetyGuardReport.live_provider_called=false`
- `BridgeSafetyGuardReport.network_access_performed=false`
- `BridgeSafetyGuardReport.db_write_performed=false`
- `BridgeSafetyGuardReport.filesystem_access_performed=false`
- `BridgeSafetyGuardReport.production_mutated=false`
- `BridgeSafetyGuardReport.staging_mutated=false`
- `ProviderRequestMapping.live_provider_call_allowed=false`
- `SandboxRequestMapping.runtime_execution_allowed=false`
- `SandboxResponse.result.safe_result_only=true`

## C10F Readiness

C10E implementation 已完成并声明 `wait_for_c10f`，但本任务没有进入 C10F。
是否进入 C10F：可以在 C10E review/acceptance 后进入；当前任务到 C10E 为止。
