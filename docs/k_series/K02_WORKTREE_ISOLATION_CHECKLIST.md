# K02 Worktree Isolation Checklist

Status: K02 isolation confirmation draft, pending owner review.

Date: 2026-06-11.

## 1. K02 Target

K02 only confirms the K series worktree isolation boundary for Product Knowledge / 白苏婉 2.0.

K02 does not write business code, create migrations, modify runtime behavior, run Docker, run Alembic, connect Postgres, touch staging or production, read env files, connect live services, or create a git commit without explicit owner approval.

## 2. Current Worktree Facts

| Item | Value |
| --- | --- |
| Current worktree path | `/opt/barong-ops-console-worktrees/k-series-product-knowledge` |
| Current branch | `feature/k-series-product-knowledge` |
| Current HEAD commit | `5f10f5bc1d690d5e06d6547396024d38f8e65f28` |
| Current HEAD summary | `5f10f5b docs: add K series product knowledge baseline` |
| Main worktree path | `/opt/barong-ops-console` |
| K worktree path | `/opt/barong-ops-console-worktrees/k-series-product-knowledge` |
| Main worktree exists | yes |
| Physical directory isolation | yes, the main worktree and K worktree are separate filesystem paths |
| K-only branch signal | yes, branch name is `feature/k-series-product-knowledge` |

Confirmed `git worktree list` output:

```text
/opt/barong-ops-console                                       32f1454 [master]
/opt/barong-ops-console-worktrees/k-series-product-knowledge  5f10f5b [feature/k-series-product-knowledge]
```

## 3. Why K Series Must Not Be Developed In The Main Worktree

The main worktree is reserved for the primary repository line and may carry C series or other owner-directed work. Developing K series there would make it harder to prove that K changes are isolated from C series module work, P series workflow work, runtime changes, migrations, and release activity.

K series also has explicit red lines in `docs/k_series/K_SERIES_ISOLATION_RULES.md`: it must not be developed in the main worktree concurrently with C series work, must not occupy C series numbering, must not behave as P series, and must not alter core scope, user, role, permission, staging, production, or live-service boundaries.

## 4. Why K Series Requires An Independent Worktree

An independent K worktree gives the owner a clear review surface:

- the path shows that the work is not happening under `/opt/barong-ops-console`;
- the branch shows that the work is scoped to Product Knowledge;
- `git status` can be checked before each K task;
- K changes can be reviewed without mixing with main worktree changes;
- future K03/K04/K05 work can be stopped before it crosses C series, P series, migration, runtime, Docker, staging, production, env, or live-service boundaries.

## 5. Clean Worktree Confirmation

Run this before starting any K task and again before requesting owner review:

```bash
pwd
git branch --show-current
git rev-parse HEAD
git worktree list
git status --short --untracked-files=all
git diff --name-only
git diff --check
```

Expected K02 clean-start state:

```text
git status --short --untracked-files=all
```

returns no output before the K02 checklist file is created.

After creating a K task document, `git status --short --untracked-files=all` must show only the expected `docs/k_series/...` documentation file until the owner approves further work.

## 6. Confirm No C Series Files Changed

Use path-focused checks before owner review:

```bash
git diff --name-only
git status --short --untracked-files=all
```

No changed path may be under C series docs or C-owned module code unless the owner explicitly approves it. In particular, K work must not modify C01-C20 docs, except owner-approved index links if requested later.

If any changed path appears outside `docs/k_series` during K02, stop and ask for owner review before continuing.

## 7. Confirm No P Series Workflow Changed

Use the same path-focused checks:

```bash
git diff --name-only
git status --short --untracked-files=all
```

No changed path may be a P-series workflow JSON, n8n draft lane file, workflow export, or other P-series integration artifact unless the owner explicitly approves it.

K series documentation may mention P series boundaries, but K02 must not modify P series workflow assets.

## 8. Future K03/K04/K05 Preflight Commands

Before any K03, K04, or K05 work starts, run:

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

- `pwd` is `/opt/barong-ops-console-worktrees/k-series-product-knowledge`;
- branch is `feature/k-series-product-knowledge`, or another owner-approved K branch;
- `/opt/barong-ops-console` remains the separate main worktree;
- status is clean before new work begins;
- planned paths match the allowlist in `docs/k_series/K_SERIES_ISOLATION_RULES.md`;
- no C series files are modified;
- no P series workflow files are modified;
- no env, Docker, Alembic, Postgres, staging, production, or live-service command is used without owner approval.

## 9. Future Path Boundary Check

Allowed future draft paths from `docs/k_series/K_SERIES_ISOLATION_RULES.md`:

```text
backend/app/modules/k_series/product_knowledge/**
tests/backend/modules/k_series/product_knowledge/**
frontend/src/modules/k-series/product-knowledge/**
docs/k_series/K_*
backend/alembic/versions/*k_series*product*knowledge*.py
```

Forbidden paths and actions remain consistent with `docs/k_series/K_SERIES_ISOLATION_RULES.md`:

- do not modify C01-C20 docs unless the owner approves adding index links only;
- do not modify existing core `users`, `roles`, `permissions`, or scope logic;
- do not modify `operation_logs` table structure;
- do not read or modify production or staging env files;
- do not modify the n8n draft lane;
- do not modify P-series workflow JSON;
- do not modify existing migrations;
- do not modify Docker production configuration;
- do not default K series into all-user menus;
- do not connect DeepSeek, OpenAI, Claude, SERP, WooCommerce, n8n, Google Sheets, WeCom, MinIO, Filebrowser, or any other live service without the required completed C tasks and owner approval.

Owner review note: this K02 checklist is an owner-requested control document under `docs/k_series`. Future K documentation naming should remain owner-approved and aligned with the documented `docs/k_series/K_*` rule.

## 10. Forbidden During K02

- Do not write business code.
- Do not create migrations.
- Do not modify runtime behavior.
- Do not run Docker.
- Do not run Alembic.
- Do not connect Postgres.
- Do not run staging scripts.
- Do not run production scripts.
- Do not read env files.
- Do not connect live services.
- Do not modify C series files.
- Do not modify P series workflow files.
- Do not commit without explicit owner approval.

## 11. Rollback Strategy

K02 should create only this checklist file. If rollback is required before commit, remove only:

```text
docs/k_series/K02_WORKTREE_ISOLATION_CHECKLIST.md
```

Do not reset, checkout, or otherwise revert unrelated files. If any unexpected changed file appears, stop and ask the owner to review the path before taking action.

## 12. Owner Review Points

Owner should verify:

- the current worktree path is the K worktree path;
- the main worktree remains separate at `/opt/barong-ops-console`;
- the branch is K-scoped;
- HEAD starts from the K01 baseline commit;
- `git diff --name-only` lists only this K02 checklist file;
- `git diff --check` passes;
- `git status --short --untracked-files=all` lists only expected K02 documentation changes;
- no C series files changed;
- no P series workflow files changed;
- no business code, migration, runtime, Docker, Alembic, Postgres, staging, production, env, or live-service action occurred;
- the owner approves before any commit is made.
