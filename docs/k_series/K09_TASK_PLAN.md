# K09 Task Plan

Status: K09A task plan, pending owner review.

Date: 2026-06-12.

## 1. K09 小任务表

| Task ID | Task name | Current status | Can do now? | Depends on | Allowed output | Forbidden actions |
| --- | --- | --- | --- | --- | --- | --- |
| K09A | 单位存储与换算基准文档落盘。 | doing now. | yes, docs only. | K04 unit model and K08 field system. | K09 baseline docs. | code, migration, runtime, Docker, Alembic, Postgres, staging, production. |
| K09B | 单位 payload contract 与 JSON 示例。 | next. | yes, docs only. | K09A. | `K09_UNIT_PAYLOAD_CONTRACT.md`, `K09_UNIT_PAYLOAD_EXAMPLES.md`. | code, DB, frontend. |
| K09C | 纯函数 unit conversion module skeleton。 | later. | yes after K09B. | K09A/K09B. | `backend/app/modules/k_series/product_knowledge/unit_conversion.py`. | DB, router registration, `main.py`, core config, core permissions, env, live services. |
| K09D | 单位换算 non-DB tests。 | later. | yes after K09C. | K09C. | `tests/backend/modules/k_series/product_knowledge/test_unit_conversion.py`. | Postgres, Alembic, staging, production. |
| K09E | dimensions / weight payload validation helper。 | later. | yes after K09C/D. | K09C/K09D. | module-local helper only. | modify K06 `schemas.py` unless separately approved. |
| K09F | K08 字段体系回补检查。 | later. | docs only after K09C/D. | K09C/K09D. | `K09_K08_FIELD_FEEDBACK.md`. | directly modifying K08 without owner approval. |
| K09G | K07 前端单位输入设计对齐。 | later. | docs only. | K09B/C or owner decision. | `K09_K07_UNIT_INPUT_GUIDE.md`. | frontend code, menu, route. |
| K09H | K10 / AI mock adapter 单位输出约束。 | later. | docs only. | K09B/C. | `K09_K10_AI_UNIT_OUTPUT_RULES.md`. | DeepSeek live, AI guessing facts. |
| K09I | K09 集成进入 K service / create-update 流程。 | blocked. | no. | K06 runtime strategy / owner approval. | future runtime integration. | service behavior changes. |
| K09J | K09 registered API / frontend 联动测试。 | blocked. | no. | K06F/K07. | future route/UI tests. | registered API tests. |
| K09-SEAL | K09 单位存储与换算封板。 | final. | no. | K09A-H review. | K09 seal docs. | premature seal. |

## 2. 当前建议

- 现在只做 K09A。
- K09A 后进入 K09B。
- 不建议直接 K09C。
- 不建议直接 K09I。
- 不建议直接接 frontend / API / staging / production。
