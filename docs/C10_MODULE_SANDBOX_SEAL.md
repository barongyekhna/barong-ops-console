# C10 Module Sandbox Seal

日期：2026-06-14 UTC

C10F 将 C10A-C10E 收敛为完整但不可执行的 mock sandbox runtime
system。本阶段只做 finalization，不进入 C11+，不修改 production/staging，
不连接 external provider，不创建真实 runtime。

## C10A-C10F 全链路

- C10A Sandbox Architecture
  - 定义 sandbox boundary、isolation model、contract interface。
  - `runtime_execution_allowed=false`
  - `external_provider_call_allowed=false`

- C10B Execution Runner (mock)
  - `SandboxRunner` 接收 C09 execution request contract。
  - 生成 deterministic mock lifecycle 和 safe result contract。
  - 不创建进程、容器、worker、shell 或真实 runtime。

- C10C Execution Context System
  - `ExecutionContextFactory` 为每个 execution request 生成 request-scoped
    context。
  - memory/log/state scope 都是 mock-only，禁止共享和跨 context mutation。

- C10D Resource Control Layer
  - `SandboxResourceEnforcer` 附加 logical-only resource policy。
  - CPU、memory、timeout 只作为 contract policy，不做 OS-level enforcement。
  - network policy 固定为 `DENY_ALL`，file policy 固定为 `SANDBOX_ONLY`。

- C10E Sandbox Execution Bridge
  - `SandboxExecutionBridge` 连接 C09 contract 与 C10 mock sandbox。
  - provider side 只转发到 `C09MockExecutionProviderInterface`。
  - 不调用 live provider、queue、webhook、callback 或 network client。

- C10F Mock Sandbox Runtime Finalization
  - `SandboxRuntime` 统一 orchestrate C10B runner、C10C context、C10D
    resource layer 和 C10E bridge。
  - `FinalSafetyLock` 固定 `execution_locked=true`。
  - `SandboxFinalState` 固定：
    - `execution_capability="mock_only"`
    - `runtime_mode="disabled_execution"`
    - `isolation_status="fully_isolated"`
    - `provider_access="redacted"`

## Sandbox Runtime 设计

C10F 新增 `backend/app/sandbox/runtime.py`，核心对象：

- `SandboxRuntime`
  - final wrapper，不提供真实 execution entrypoint。
  - 默认并强制 `execution_locked=True`。
  - 集成：
    - C10B `SandboxRunner`
    - C10C `ExecutionContextFactory`
    - C10D `SandboxResourceEnforcer`
    - C10E `SandboxExecutionBridge`

- `SandboxRuntimeLifecycle`
  - 记录 final runtime lifecycle。
  - 每个 step 都声明：
    - `execution_locked=true`
    - `mock_only=true`
    - `runtime_created=false`
    - `external_provider_called=false`
    - `real_computation_executed=false`

- `FinalSafetyLock`
  - C10F 最终安全锁。
  - 对 bridge response、provider mock forward、sandbox response、
    execution context 和 resource policy 做最终 safety check。

- `SandboxFinalState`
  - C10 final state object。
  - 表示 sandbox runtime 已封口为 disabled execution / mock only。

## Runtime Lifecycle Model

C10F lifecycle controller 定义五个阶段：

```text
runtime_start
  -> runtime_prepare
  -> runtime_execute
  -> runtime_complete
  -> runtime_finalize
```

语义：

- `runtime_start`
  - 接收 C09 execution request contract。
  - 只记录 runtime controller 已接收 contract。

- `runtime_prepare`
  - 通过 C10E bridge 构造 `BridgeRequest`。
  - 绑定 C10C context，并声明 C10D resource-control delegation 与
    sandbox request mapping。

- `runtime_execute`
  - mock only。
  - 只调用 C10E `SandboxExecutionBridge.receive_execution_request()`。
  - 不创建真实 runtime，不执行 adapter action，不调用 provider。

- `runtime_complete`
  - 构建 `FinalSafetyLock`。
  - 如发现 runtime/provider/network/db/filesystem/env escape，则保持
    locked 并返回 `locked_with_violation`。

- `runtime_finalize`
  - 构建 `SandboxFinalState`。
  - 返回 `SandboxRuntimeResponse`。
  - `next_stage_policy="wait_for_c10g"`，不进入 C11+。

## Unified Execution Pipeline

最终统一 pipeline：

```text
User Action
  -> C08 Module Adapter
  -> C09 Execution Provider
  -> C10 Sandbox Runtime
  -> Mock Result
```

C10F 中这个 pipeline 是 contract-level orchestration：

- C08 只提供 adapter/action contract 与 permission/risk metadata。
- C09 只提供 `ExecutionRequestContractV1`。
- C10 runtime 只执行 mock orchestration。
- 输出只允许 safe mock result。

## Mock Execution System

C10 mock execution system 由以下对象组成：

- `ExecutionRequestContractV1`
- `ExecutionContext`
- `ResourcePolicy`
- `SandboxRequest`
- `BridgeRequest`
- `BridgeResponse`
- `SandboxRuntimeResponse`

mock execution 的含义：

- 模拟 lifecycle，不执行真实业务逻辑。
- 生成 deterministic IDs 和 safe summaries。
- 不回显 raw input payload。
- 不产生 artifact 文件。
- 不写 operation log 或 audit event。
- 不读 secret、credential、provider endpoint。
- 不触达 production/staging。

## Execution Forbidden Guarantee

C10F final safety lock 保证：

- `execution_locked=true`
- `no_side_effect_guarantee=true`
- `no_external_call=true`
- `no_real_computation_execution=true`
- `no_real_runtime_existence=true`
- `runtime_creation_allowed=false`
- `external_provider_call_allowed=false`
- `live_provider_call_allowed=false`
- `network_access_allowed=false`
- `db_write_allowed=false`
- `filesystem_write_allowed=false`
- `production_access_allowed=false`
- `staging_access_allowed=false`
- `subprocess_allowed=false`
- `docker_allowed=false`

任何 bridge/runner/context/resource 层报告 escape，C10F 都只会产生
`locked_with_violation`，不会解除 execution lock。

## No Real Runtime Existence

C10 到 C10F 结束时仍不存在真实 sandbox runtime：

- 没有 OS process isolation implementation。
- 没有 container runtime binding。
- 没有 subprocess/worker/shell execution。
- 没有 external provider connector。
- 没有 network client。
- 没有 production/staging access。
- 没有 database mutation。
- 没有 filesystem write。
- 没有真实 computation execution。

`SandboxRuntime` 是 final wrapper，不是 executor。C10F 的完成状态是：

```text
execution_capability = "mock_only"
runtime_mode = "disabled_execution"
isolation_status = "fully_isolated"
provider_access = "redacted"
```

## Implementation Summary

新增：

- `backend/app/sandbox/runtime.py`
- `tests/backend/test_sandbox_runtime_finalization.py`
- `docs/C10_MODULE_SANDBOX_SEAL.md`

更新：

- `backend/app/sandbox/types.py`
- `backend/app/sandbox/__init__.py`

## C10G Readiness

C10F 已完成 mock sandbox runtime finalization layer，并准备 seal 文档。
可以进入 C10G 做 review/seal acceptance。

禁止从 C10F 直接进入 C11+，也禁止把 C10F 解释为真实 execution runtime。
