# C12A Approval Schema Design

日期：2026-06-14 UTC

C12A 定义 C12 Approval System 的数据结构层：`ApprovalRequest`
schema。本阶段只做 schema design，不实现审批逻辑，不执行 sandbox，不创建 runtime
execution，不运行 docker / pytest，不修改 production 或 staging。

## 1. ApprovalRequest Schema

Python schema: `backend/app/schemas/approval.py`

```text
ApprovalRequest
  schema_version = c12.approval_request.v1
  approval_id
  execution_id
  module_key
  adapter_key
  action_key
  requester_id
  request_time
  risk_level
  execution_type
  status
  reason
  reviewer_id
  context_snapshot
  status_trace
```

Required C12A fields:

| 字段 | 类型 / 枚举 | 说明 |
| --- | --- | --- |
| `approval_id` | string | Approval Request 稳定唯一 ID。未来持久化层必须加唯一约束。 |
| `execution_id` | string | 必须绑定 C09 `ExecutionRequestContractV1.execution_id`。不得创建无 execution request 的 approval request。 |
| `module_key` | string | 来自 C09 execution request，并与 C07 module key 对齐。 |
| `adapter_key` | string | 来自 C09 execution request，并与 C08 adapter key 对齐。 |
| `action_key` | string | 来自 C09 execution request，并与 C08 action contract 对齐。 |
| `requester_id` | int | 发起审批请求的用户 ID，必须与 C09 execution request actor / requester 语义一致。 |
| `request_time` | datetime | 审批请求创建时间。 |
| `risk_level` | `low` / `medium` / `high` | C12 使用的风险等级，来源于 C11B/C11D 风险规则输出。 |
| `execution_type` | `mock` / `no_op` / `async` / `real` | C12 使用的执行类型，来源于 C11 execution type 分类。 |
| `status` | `pending` / `approved` / `rejected` / `auto_approved` | 当前审批请求状态。C12A 只声明状态，不执行状态迁移。 |
| `reason` | string | 请求审批的原因或阻断原因。不得包含 secret、token、credential、provider URL 或 raw payload。 |
| `reviewer_id` | int or null | 审批人 ID。`pending` 状态可以为空；`auto_approved` 可以为空。 |
| `context_snapshot` | `ApprovalContextSnapshot` | 审计快照，创建后不可变。 |

C12A 额外声明 `status_trace`，用于未来记录状态迁移轨迹；它不是审批逻辑。

## 2. Field Definition Explanation

`approval_id`

- Approval Request 的主标识。
- 数据库或持久化层必须保证全局唯一。
- 不得复用 C09 `execution_id` 作为 approval 主键。

`execution_id`

- Approval Request 必须绑定一个 C09 execution request。
- 它只表达审批对象，不触发 execution submit、queue、worker、webhook 或 provider call。

`module_key` / `adapter_key` / `action_key`

- 三者必须从 C09 execution request 继承。
- 这些字段让审批记录能回溯到 C07 module、C08 adapter 和 C08 action contract。

`requester_id`

- 表示请求审批的用户。
- C12A 不做权限校验；权限和 actor 合法性仍属于 C05/C06/C09 上游责任。

`request_time`

- 表示 approval request 创建时间。
- 用于审计排序和状态追踪，不代表 execution 开始时间。

`risk_level`

- 允许值为 `low`、`medium`、`high`。
- 来源是 C11B/C11D 风险规则输出；C12A 不计算 risk。

`execution_type`

- 允许值为 `mock`、`no_op`、`async`、`real`。
- 来源是 C11 execution type 分类；C12A 不决定 execution mode。

`status`

- 允许值为 `pending`、`approved`、`rejected`、`auto_approved`。
- 初始状态为 `pending`。
- 终态为 `approved`、`rejected`、`auto_approved`。
- C12A 只声明状态机，不提供 approve/reject/auto-approve 函数。

`reason`

- 记录为什么需要审批、为什么阻断或为什么进入某个状态。
- 必须是安全摘要，不能包含敏感凭据或原始业务输入。

`reviewer_id`

- 手动审批时记录 reviewer。
- `pending` 和 `auto_approved` 可为空。
- C12A 不校验 reviewer 权限。

`context_snapshot`

- 审计用途字段。
- 捕获 approval request 创建时的 execution identity、risk、execution type、source refs
  和脱敏事实。
- 创建后不可变；如果上游 context 改变，应创建新的 approval request 或未来追加审计事件，
  不得修改既有 snapshot。

## 3. Schema Rules

- Approval request 必须绑定 C09 execution request。
- `context_snapshot` 用于审计，必须只包含脱敏上下文和 source refs。
- `execution_type` 来自 C11 execution type 分类，C12A 不推导、不覆盖。
- `risk_level` 来自 C11B/C11D，C12A 不计算、不升级、不降级。
- C12A 不写 operation log、不写 audit event、不创建 database table、不新增 API。
- C12A 不读取 env、不读取 secret、不连接 provider、不触发 adapter action。

## 4. Data Constraints

`approval_id` uniqueness:

- `approval_id` 必须唯一。
- 未来持久化层应使用 unique index / unique constraint。

Traceable status state machine:

```text
pending -> approved
pending -> rejected
pending -> auto_approved
```

- `pending` 是唯一初始状态。
- `approved`、`rejected`、`auto_approved` 是终态。
- 状态迁移必须可追踪；C12A 通过 `ApprovalStatusTraceEntry` 定义 trace 结构。
- C12A 不实现迁移逻辑，C12B 之后才能实现状态写入和权限校验。

Immutable context snapshot:

- `ApprovalContextSnapshot` 是 frozen schema。
- `facts` 和 `source_refs` 使用 tuple，避免 in-place mutation。
- snapshot 只保存脱敏事实和引用，不保存 raw input、secret、token、credential、provider URL
  或 webhook URL。

## 5. Relationship To C09 Execution

C12A 依赖 C09，但不执行 C09。

关系规则：

- `ApprovalRequest.execution_id` references C09 `ExecutionRequestContractV1.execution_id`。
- `module_key`、`adapter_key`、`action_key`、`requester_id`、`risk_level` 必须与 C09
  request 上下文一致。
- C09 中 `blocked_approval_required` 的 execution request 可以生成 C12 approval request。
- Approval Request 不是 execution request 的替代品；不能绕过 C09 直接执行 action。
- C12A 不新增 `/executions`、`/execution/submit`、`approve`、`reject` 或任何 mutation
  endpoint。

Cardinality:

- 一个 C09 execution request 最多应有一个 active approval request。
- `approved` / `rejected` / `auto_approved` 终态之后，未来如需重新审批，应创建新的
  approval request 或新的 execution request，而不是改写旧 snapshot。

## 6. Relationship To C10 Sandbox

C12A 不进入 C10 runtime。

边界规则：

- C10 仍是 mock-only sandbox runtime finalization。
- C12A 不调用 `SandboxRuntime`、`SandboxExecutionBridge`、runner、resource enforcer 或
  execution context factory。
- `context_snapshot` 可以记录来自 C10 contract 的脱敏 source ref，但不得触发 sandbox run。
- Approval status 不解除 C10 execution lock。
- C12A 不创建 subprocess、container、worker、shell、queue、webhook、callback、network
  client、database write 或 filesystem write。

## 7. C12B Readiness

可以进入 C12B。

C12B 的合理下一步是审批请求的数据持久化 / 服务边界设计，但仍必须单独明确：

- 是否创建数据库表和 migration。
- 是否增加 read-only 或 mutation API。
- 状态迁移如何鉴权和记录 operation log / audit event。
- 如何继续阻断 execution，直到后续阶段显式允许。

C12A 本身完成的是 schema design，不包含审批逻辑、sandbox execution、runtime
execution、docker / pytest、production/staging 修改。
