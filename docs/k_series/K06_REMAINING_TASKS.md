# K06 Remaining Tasks

Status: K06 deferred task list created, pending owner review.

Date: 2026-06-12.

## 1. K06 剩余任务表

| Task ID | Task name | Current status | Can do now? | Depends on | Allowed output | Forbidden actions |
| --- | --- | --- | --- | --- | --- | --- |
| K06-Deferred | K06 高危 runtime registration 冻结记录。 | doing now. | yes, docs only. | K06B/K06C/K06D/K06E current records. | `docs/k_series/K06_*.md` freeze records and review checklist. | No Python code, router registration, core touchpoints, frontend, tests, migration, Docker/Alembic/Postgres/staging/production, env read, or live service. |
| K06-REM-01 | C07G baseline sync / merge readiness review。 | deferred. | later, docs only. | C07G final commit / C main clean state. | Sync readiness review document only. | No merge/rebase, no runtime edits, no C-series doc/runtime edits without approval. |
| K06-REM-02 | K branch 与 C07G 主线同步 / rebase 计划。 | deferred. | no. | K06-REM-01 review and owner approval. | Owner-approved sync/rebase plan only. | No rebase/merge execution, no conflict resolution, no core edits without separate approval. |
| K06-REM-03 | 同步后 K06 regression check。 | deferred. | no. | K06-REM-02. | Regression evidence including py_compile, K06C import smoke, K06E tests, Alembic heads/down_revision check. | No staging/production, no live service, no env read, no router registration, no migration changes. |
| K06-REM-04 | Router registration implementation plan。 | deferred. | later docs only. | K06-REM-01/K06-REM-03 and owner approval. | Implementation plan and rollback plan only. | No main.py/router registry/config/permissions/deps edits, no frontend exposure, no live provider. |
| K06F | Minimal disabled router registration。 | blocked. | no. | K06-REM-04, C07 pattern confirmed, C08/C13/C18 status reviewed, owner explicit approval. | Minimal disabled registration patch only if approved. High-risk files: main.py or router registry. | No start without owner explicit approval, no frontend menu, no live provider, no staging/production, no permission widening. |
| K06G | Core config / permission / feature flag integration decision。 | blocked. | no. | C13 and owner approval. | Decision record or approved core integration patch in a separate task. | No config, permissions, auth/deps, module switch, or scope edits without separate approval. |
| K06H | Registered route disabled-state tests。 | blocked. | no. | K06F. | Tests proving registered routes remain disabled/default-deny if K06F is approved. | No tests before registration exists, no runtime widening, no live service, no staging/production. |
| K06-SEAL | K06 backend CRUD API skeleton final seal。 | blocked. | no. | K06F/G/H or explicit decision to seal K06 with registration deferred. | Final seal report and review checklist. | No seal that hides unresolved runtime, scope, permission, adapter, or rollback risks. |

## 2. 当前建议

- 现在不做 K06F。
- 现在先完成 K06-Deferred。
- K06-Deferred 后可以跳过 K06 高危 runtime registration，继续 K08/K09/K10 等低风险可隔离任务。
- K06F/G/H 以后等 C 系列总控能力更完整后补做。
