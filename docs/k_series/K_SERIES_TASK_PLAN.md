# K Series Task Plan

Status: approved baseline for K01.

This plan is documentation only. It does not create business code, migrations, runtime configuration, provider connections, or deployment changes.

## Readiness Legend

- Yes: can be done under K isolation and `scope-adapter-pending`.
- Draft only: can be documented or mocked, but not wired into runtime or live services.
- No: blocked by C series completion, K prerequisite completion, or owner approval.

## K01-K33 Task Table

| ID | Task Name | Can Do Now | Waits For C Task | Output | Prohibited |
| --- | --- | --- | --- | --- | --- |
| K01 | K 系列基准文档与工程记忆落盘 | Yes | None | `docs/k_series/K_SERIES_MEMORY_BASELINE.md`, `K_SERIES_TASK_PLAN.md`, `K_SERIES_ISOLATION_RULES.md` | No business code, migrations, runtime changes, env reads, live services, Docker, Alembic, Postgres, staging/production scripts, or commits without owner approval |
| K02 | K worktree 与开发隔离 | Yes | None | Worktree isolation notes and verification checklist | Do not modify `/opt/barong-ops-console` main worktree or C series files |
| K03 | K allowlist and 禁止路径 | Yes | None | K allowlist / denylist documentation | Do not create business directories outside the approved K draft path family |
| K04 | K 数据库 schema 设计 | Draft only | None | Isolated schema design document for K table family | Do not create migrations, alter existing tables, or modify core user/role/permission/scope structures |
| K05 | K 后端 migration | No | None; requires K04 approval and owner approval | New isolated K migration file in future | Do not run Alembic, do not alter existing migrations, do not touch core tables |
| K06 | K 后端 CRUD API skeleton | Draft only | None | Disabled API skeleton using K Scope Shim in future | Do not enable API by default, do not bypass fallback access rules |
| K07 | K 前端基础 UI | Draft only | None | Hidden-by-default K UI shell in future | Do not add menu visibility for all users or modify unrelated frontend runtime |
| K08 | 产品字段体系 | Yes | None | Product field taxonomy and canonical data contract | Do not bind fields to Google Sheets as long-term source of truth |
| K09 | 单位存储与换算 | Yes | None | Unit model and conversion rules for dimensions, weight, and target markets | Do not store ambiguous units or overwrite original operator input |
| K10 | DeepSeek 翻译 / 结构化 mock adapter | Yes | None | Mock adapter contract and test fixtures in future | Do not call DeepSeek live service or read live provider secrets |
| K11 | DeepSeek live adapter | No | C14 for key rules; C09 for Execution Provider | Live DeepSeek V4 Pro provider adapter in future | Do not connect DeepSeek before C14/C09 completion and owner approval |
| K12 | 英文 canonical 审核界面 | Draft only | None | Operator review/edit UI for English canonical product data in future | Do not auto-approve unreviewed canonical data |
| K13 | 多语言检查界面 | Draft only | None for UI draft; C14/C09 for live translation | Multilingual review UI in future | Do not use ordinary machine translation as the final multilingual check |
| K14 | 卖点整理功能 | Draft only | None for rules/mock; C14/C09 for live provider | English selling-point refinement contract in future | Do not call live LLM providers without approved provider execution |
| K15 | 关键词调研按钮 skeleton | Draft only | None | Disabled keyword research button skeleton in future | Do not trigger live SERP/OpenAI/Claude/n8n calls |
| K16 | SERP provider adapter | Draft only | C14 for key rules; C09 for provider execution | SERP adapter interface/mock in future | Do not connect real SERP before C14/C09 completion and owner approval |
| K17 | ChatGPT 筛选 adapter | Draft only | C14 for key rules; C09 for provider execution | ChatGPT filtering adapter interface/mock in future | Do not connect OpenAI live service before C14/C09 completion and owner approval |
| K18 | Claude 二次筛选 adapter | Draft only | C14 for key rules; C09 for provider execution | Claude second-pass filtering adapter interface/mock in future | Do not connect Claude live service before C14/C09 completion and owner approval |
| K19 | 关键词写入与人工修改 | Draft only | None; depends on K schema/API approval | Main, secondary, and risk keyword persistence/editing in future | Do not let external workflow write directly into Barong database |
| K20 | 风险词提示与管理 | Draft only | None | Risk keyword hinting and management design/API/UI in future | Do not auto-block products without explicit review rules |
| K21 | K operation_logs 初步接入，不改 operation_logs 表结构 | Draft only | C17 for audit page display | K operation logging through existing contract in future | Do not modify `operation_logs` table structure |
| K22 | K review task / 审批占位，正式审批等 C12 | Draft only | C12 for formal approval gates | Review-task placeholder in future | Do not implement a parallel approval system |
| K23 | K feature flag fallback | Yes | None | K-specific fallback feature flag plan/implementation in future | Do not default-enable K APIs or menus |
| K24 | K module manifest 草案 | Draft only | None for draft; C07/C08/C13 for formal registration | Draft module manifest in future | Do not register as a formal module before C07/C08/C13 |
| K25 | 正式模块注册 | No | C07/C08/C13 | Formal module registration in future | Do not bypass Module Adapter or module-switch architecture |
| K26 | 正式 scope 接入 | No | C18 | Formal scope adapter integration in future | Do not invent a permanent K-only scope system |
| K27 | 密钥规则正式接入 | No | C14 | Formal provider-secret integration in future | Do not read production/staging env or ad hoc secret files |
| K28 | n8n / P 系列接入 | No | C15 plus stable K API | Formal P series integration using K API in future | Do not let n8n write the Barong database directly or modify P workflow JSON early |
| K29 | K staging 测试 | No | Requires K API/UI maturity and owner approval | Staging test evidence in future | Do not run staging scripts in K01 or without approval |
| K30 | K production dormant release | No | Requires K staging acceptance and owner approval; production release governance may depend on C16 | Production dormant release package in future | Do not enable K by default |
| K31 | K production enable | No | C07/C13/C18/C14/C16 plus owner approval | Controlled production enablement in future | Do not expose to all users or enable without owner approval |
| K32 | K 与 P 系列重构闭环 | No | C15 plus stable K API and P series readiness | K-to-P product knowledge data flow in future | Do not mutate n8n draft lane or P workflow JSON prematurely |
| K33 | K 验收与封板 | No | Completion of required K tasks and dependent C gates | Acceptance checklist, final docs, and seal in future | Do not seal with unresolved live-provider, scope, approval, or production risks |

## Required C Series Wait Points

- Formal module registration waits for C07/C08/C13.
- Formal scope integration waits for C18.
- Live provider secrets wait for C14.
- Provider execution waits for C09.
- Approval gates wait for C12.
- Formal n8n / P series integration waits for C15.
- Production enable waits for C16.
- Audit page display waits for C17.

## Sequencing Notes

- K01-K03 establish memory, worktree isolation, and allowlist / denylist control.
- K04-K10 can define isolated contracts and mocks before formal C adapters are complete.
- K11 and K16-K18 must not become live providers until C14 and C09 are complete and the owner approves.
- K21 may use existing operation logging contracts only; audit page display waits for C17.
- K22 may create placeholders only; formal approval waits for C12.
- K25-K27 are formal platform integration tasks and remain blocked until their C dependencies complete.
- K28-K32 connect K to P, staging, production, and downstream workflows only after the required C gates and owner approval.
