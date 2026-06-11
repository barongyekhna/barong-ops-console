# K03 Allowlist And Denylist

Status: K03 allowlist / denylist control draft, pending owner review.

Date: 2026-06-11.

## 1. K03 目标

K03 only defines the path boundary for later K series development. It records which paths may be used in future K04/K05/K06/K07 and later tasks, and which paths and actions are forbidden.

K03 does not write business code, does not create business code directories, does not create migrations, does not modify runtime behavior, does not enable any feature, does not connect live services, and does not change staging or production configuration.

## 2. K 系列当前状态

- K series = Knowledge / 产品知识库 / 白苏婉 2.0.
- K series is not C07.
- K series is not P series.
- K series is currently `scope-adapter-pending`.
- K Scope Shim uses:
  - `workspace_key = default_independent_store`
  - `business_context = independent_store`
  - `scope_mode = adapter_pending`
- API default is disabled.
- Frontend menu default is hidden.
- Fallback access allows only owner or K-prefixed permissions.
- Formal adapter waits for C07/C08/C13/C18.

## 3. 后续允许路径总表

The following paths are the future K allowlist. K03 defines these paths only; it does not create business code directories, migrations, or runtime files.

```text
docs/k_series/K_*
docs/k_series/K0*
docs/k_series/K1*
docs/k_series/K2*
docs/k_series/K3*
```

Allowed documentation path family for K series task documents, plans, checklists, schema drafts, contracts, review notes, and owner-approved K control documents.

```text
backend/app/modules/k_series/product_knowledge/**
```

Future backend module path for isolated Product Knowledge code. This path may be used only by approved later K tasks and must keep API disabled by default until explicitly approved.

```text
tests/backend/modules/k_series/product_knowledge/**
```

Future backend test path for the isolated Product Knowledge module. Tests must target K module behavior and must not require live providers, production/staging env, or direct production services.

```text
frontend/src/modules/k-series/product-knowledge/**
```

Future frontend module path for Product Knowledge UI. The menu must remain hidden by default and must not become visible to all users by default.

```text
backend/alembic/versions/*k_series*product*knowledge*.py
```

Future isolated migration filename pattern for K Product Knowledge table-family creation only. It must wait for K04 review and owner approval before K05 may create it.

## 4. 后续允许路径分阶段说明

K04 allowed:

- Write schema design documentation only.
- Prefer `docs/k_series/K04_*`.
- Do not create migrations.
- Do not alter existing tables.
- Do not modify runtime code.

K05 future allowed:

- `backend/alembic/versions/*k_series*product*knowledge*.py`
- Must wait for K04 review and owner approval.
- May only create the K table family.
- Must not alter core tables.
- Must not modify existing Alembic migrations.
- Must not run Alembic unless separately approved in a future task.

K06 future allowed:

- `backend/app/modules/k_series/product_knowledge/**`
- `tests/backend/modules/k_series/product_knowledge/**`
- API must be disabled by default.
- K06 must use K Scope Shim.
- K06 must not bypass fallback access rules.
- K06 must not modify core users, roles, permissions, organizations, or formal scope runtime.

K07 future allowed:

- `frontend/src/modules/k-series/product-knowledge/**`
- Frontend menu must be hidden by default.
- K07 must not default the feature into all-user navigation.
- K07 must not modify unrelated frontend runtime.

K10-K18 future allowed:

- Provider adapter mock and contract files may be placed under the K module directory.
- Mock DeepSeek can be drafted in K10.
- Live providers must wait for C14/C09 and owner approval.
- No live DeepSeek, OpenAI, Claude, SERP, WooCommerce, n8n, Google Sheets, WeCom, MinIO, Filebrowser, or other live-service call may be added early.

K21 future allowed:

- Use existing `operation_logs` API or service.
- Do not modify the `operation_logs` table structure.
- Audit page display waits for C17.

K22 future allowed:

- Review task placeholder / draft contract.
- Formal approval must wait for C12.
- Do not implement a parallel approval system.

K24 future allowed:

- K module manifest draft.
- Formal module registration must wait for C07/C08/C13.
- Do not bypass the Module Adapter or module-switch architecture.

K25/K26/K27/K28/K30/K31:

- These tasks may enter only after their corresponding C tasks are complete and the owner approves.
- K25 formal module registration waits for C07/C08/C13.
- K26 formal scope integration waits for C18.
- K27 provider-secret integration waits for C14.
- K28 n8n / P series integration waits for C15 and stable K API.
- K30 production dormant release waits for staging acceptance, release governance, and owner approval.
- K31 production enable waits for C07/C13/C18/C14/C16 and owner approval.

## 5. 禁止路径总表

The following paths and path families are forbidden for K work unless a future owner instruction explicitly changes the boundary:

```text
/opt/barong-ops-console
```

- Main worktree. K series must not be developed there.

```text
Any C01-C20 docs
```

- Forbidden unless the owner approves adding index links only.
- K series must not occupy or rewrite C series numbering.

```text
backend/app/users*
backend/app/roles*
backend/app/permissions*
backend/app/auth*
backend/app/organizations*
backend/app/scope*
```

- Core user, role, permission, auth, organization, and scope runtime paths are forbidden.

```text
core permission assignment runtime
operation_logs table structure
existing Alembic migrations
```

- K series must not change core permission assignment behavior.
- K21 may use existing operation logging contracts only.
- K05 may create a new K migration only after approval; it must not modify existing migrations.

```text
.env.production
.env.staging
any production/staging config
Docker production config
```

- K series must not read or modify production/staging env or release configuration.

```text
n8n draft lane
P-series workflow JSON
inbox/ workflow source files
workflows_modified/
workflows_sanitized/
```

- K series must not mutate P-series or workflow assets early.

```text
real provider credential files
real secrets/tokens/passwords
any live service integration
```

- K series must not read, write, store, or connect with real provider secrets or live services.

## 6. 禁止动作总表

- Do not read production or staging env.
- Do not connect live DeepSeek, OpenAI, Claude, SERP, WooCommerce, n8n, Google Sheets, WeCom, MinIO, Filebrowser, or any other live service.
- Do not run Docker, Alembic, Postgres, staging, or production commands.
- Do not go online by default.
- Do not make K visible to all users by default.
- Do not let n8n write directly to the Barong database.
- Do not keep Google Sheets as the long-term source of truth for Product Knowledge.
- Do not develop K concurrently in the main worktree with C series work.
- Do not bypass K Scope Shim.
- Do not invent a formal scope system.
- Do not modify core users, roles, permissions, or organizations.
- Do not modify C01-C20 documents unless the owner approves adding index links only.
- Do not modify P-series workflow JSON.
- Do not modify n8n draft lane files.
- Do not create business code directories during documentation-only tasks.
- Do not create migrations before K05 owner approval.
- Do not modify existing Alembic migrations.

## 7. K 数据库表族命名规则

Future K table-family names should use this prefix:

```text
k_product_knowledge_
```

Future table names may be drafted as examples only:

- `k_product_knowledge_products`
- `k_product_knowledge_attributes`
- `k_product_knowledge_translations`
- `k_product_knowledge_keywords`
- `k_product_knowledge_risk_terms`
- `k_product_knowledge_research_runs`
- `k_product_knowledge_ai_events`
- `k_product_knowledge_versions`

K03 does not create a migration.

K05 may create only the K table family after K04 review and owner approval.

K series must not alter:

- `users`
- `roles`
- `permissions`
- `organizations`
- `operation_logs`

## 8. K 权限前缀规则

Future K permissions must use K-prefixed names, for example:

```text
k.product_knowledge.read
k.product_knowledge.create
k.product_knowledge.update
k.product_knowledge.delete
k.product_knowledge.translate
k.product_knowledge.keyword_research.run
k.product_knowledge.keyword_research.approve
k.product_knowledge.risk_terms.manage
k.product_knowledge.review
k.product_knowledge.export
```

Overbroad permission names are forbidden, for example:

```text
product.read
product.update
admin.product.*
```

K permissions must not reuse generic product permissions and must not broaden access to unrelated modules.

## 9. Provider adapter 边界

- K10 mock DeepSeek can be drafted first.
- K11 DeepSeek live must wait for C14/C09 and owner approval.
- K16 SERP live must wait for C14/C09 and owner approval.
- K17 ChatGPT live must wait for C14/C09 and owner approval.
- K18 Claude live must wait for C14/C09 and owner approval.
- All provider keys are governed by future C14 secret rules.
- K series must not read env files.
- K series must not save secrets.
- K series must not store real provider credentials, tokens, or passwords.
- K series must not connect live providers before the relevant C gates and owner approval.

## 10. K 与 P 系列边界

- K series first builds Product Knowledge.
- P series may later call K through Barong backend API only after the required K and C gates are complete.
- K03 does not modify any P workflow.
- K03 does not read or process P workflow JSON.
- n8n must not write directly to the Barong database.
- Google Sheets must not remain the long-term source of truth for Product Knowledge.
- K to P integration waits for C15, stable K API, and owner approval.

## 11. K03 完成后的下一步

- After K03 is complete, wait for owner review.
- Commit only after the owner approves.
- K04 is database schema design and remains documentation only.
- K04 must not write migrations.
- K05 may create a migration only after K04 review and owner approval.
- K05 may only create the isolated K table family and must not alter core tables.

## 12. Preflight checklist

Before each K04/K05/K06/K07 task starts, run:

```bash
pwd
git branch --show-current
git rev-parse HEAD
git worktree list
git status --short --untracked-files=all
git diff --name-only
git diff --check
```

Required confirmations:

- Current path is `/opt/barong-ops-console-worktrees/k-series-product-knowledge`.
- Branch is `feature/k-series-product-knowledge`.
- Main worktree `/opt/barong-ops-console` has not been modified by K work.
- `git status` is clean before new work begins.
- Planned paths are inside the allowlist.
- No C files are changed.
- No P files are changed.
- No env, live-service, production, or staging behavior is used.
- No Docker, Alembic, Postgres, staging, or production command is run without explicit future approval.
- No business code is written during documentation-only tasks.
- No migration is created before K05 owner approval.
