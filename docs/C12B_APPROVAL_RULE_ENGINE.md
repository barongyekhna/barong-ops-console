# C12B Approval Rule Engine

日期：2026-06-14 UTC

C12B 在 C12A `ApprovalRequest` schema 之后新增 Approval Decision Engine。
本阶段只做内存规则评估：输入 `ApprovalRequest`，输出 `ApprovalDecision`。

本阶段不执行 sandbox，不触发 C09 execution，不修改 runtime，不写 DB，不调用 external
API，不 git commit。

## 1. ApprovalRuleEngine Implementation

新增：

- `backend/app/services/approval_rule_engine.py`
- `ApprovalRuleEngine.evaluate(request) -> ApprovalDecision`

更新：

- `backend/app/schemas/approval.py`
  - 新增 `ApprovalDecision`
  - 新增 `ApprovalDecisionStatus`
  - 新增 `ApprovalDecisionSource`

`ApprovalDecision` 字段：

| 字段 | 取值 | 说明 |
| --- | --- | --- |
| `status` | `approved` / `rejected` / `auto_approved` / `pending` | 规则引擎输出的审批决策状态。 |
| `reason` | string | 安全原因摘要。 |
| `decision_source` | `risk` / `execution` / `module` / `user` / `global` | 产生最终决策的主规则来源。 |

## 2. Decision Flow

```text
ApprovalRequest
  -> validate request/context_snapshot identity consistency
  -> short-circuit terminal request status
  -> infer requester role from context_snapshot facts
  -> classify module namespace
  -> evaluate user rule
  -> evaluate module rule
  -> evaluate execution_type rule
  -> evaluate risk_level rule
  -> merge decisions by precedence
  -> ApprovalDecision
```

The engine accepts either an `ApprovalRequest` object or mapping data that can be
validated into `ApprovalRequest`.

Requester role source:

- Read from `context_snapshot.facts` keys:
  - `requester_role`
  - `actor_role`
  - `user_role`
  - `role`
- `owner` maps to relaxed owner rules.
- `guest` / `anonymous` / `public` / `unauthenticated` maps to guest rules.
- Missing or other roles map to `non_owner` and use strict rules.

Module namespace classification:

- `admin.*` -> admin profile.
- `system.*` -> system profile.
- `business.*` -> business profile.
- Anything else -> unknown profile and manual review by default.

## 3. Rule Logic

Risk level rules:

- `low` -> `auto_approved`
- `medium` -> `pending` by default
- `medium` + owner + safe execution + non-admin/system -> `auto_approved`
- `high` -> `pending` manual approval required

Execution type rules:

- `mock` -> `auto_approved`
- `no_op` -> `auto_approved`
- `async` -> conditional:
  - owner + low risk + non-admin/system -> `auto_approved`
  - otherwise -> `pending`
- `real` -> `pending` manual approval required

Module rules:

- `admin.*` -> `pending`, stricter manual approval required
- `system.*` -> `pending`, treated as high-risk
- `business.*` -> medium-risk handling:
  - owner + low + safe/async requests can auto-approve
  - owner + medium + safe execution can auto-approve
  - non-trivial requests remain `pending`

Requester rules:

- owner -> relaxed for non-real, non-admin/system, low/medium requests
- non-owner -> strict; only low-risk safe execution outside admin/system can auto-approve
- guest -> rejected for high-friction requests; otherwise `pending`

## 4. Rule Precedence

Hard guards:

1. Request/context snapshot identity drift -> `rejected`, `decision_source=global`.
2. Existing terminal request status returns a matching decision:
   - `approved` -> `approved`
   - `rejected` -> `rejected`
   - `auto_approved` -> `auto_approved`

Merge precedence:

```text
rejected > pending > approved > auto_approved
```

Tie-breaker source precedence:

```text
user > module > execution > risk > global
```

This means an auto-approval rule never overrides a manual-review or rejection
rule. Owner relaxation can lower only eligible risk/execution paths; it cannot
override `admin.*`, `system.*`, `high`, `real`, guest rejection, or snapshot
drift.

## 5. Safety Guarantee

C12B guarantees:

- No sandbox execution.
- No C09 execution provider call.
- No C10 sandbox runtime or bridge call.
- No runtime mutation.
- No database write.
- No operation log write.
- No audit event write.
- No external API call.
- No provider endpoint call.
- No filesystem write by the rule engine.
- No git commit.

`ApprovalRuleEngine` is a pure in-memory evaluator. It returns an
`ApprovalDecision` and does not mutate `ApprovalRequest`.

## 6. C12C Readiness

可以进入 C12C。

C12C 可以继续做 approval state transition / approval service boundary，但必须单独设计：

- `pending -> approved/rejected/auto_approved` 的写入边界。
- reviewer 权限校验。
- operation log / audit event 是否写入以及如何脱敏。
- 是否引入 DB table / migration。
- 如何继续阻断 C09/C10 execution，直到后续阶段明确允许。

C12B 本身不提供 approve/reject endpoint，不创建审批记录，不执行 action。
