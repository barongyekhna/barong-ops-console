# K Series Isolation Rules

Status: approved baseline for K01.

These rules define the K series isolation boundary for Product Knowledge / 白苏婉 2.0. K01 records rules only and does not create business code directories, migrations, runtime changes, or live-service connections.

## 1. Isolation Principles

- Git worktree isolation.
- Code directory isolation.
- Database table-family isolation.
- Migration isolation.
- Docker project-name isolation.
- Feature flag isolation.
- Scope-adapter-pending isolation.
- Permission prefix isolation.
- Provider adapter isolation.
- Staging / production release isolation.

## 2. Scope-Adapter-Pending Boundary

K series starts with `scope-adapter-pending` because the formal C platform pieces are not fully complete:

- C07 module isolation.
- C08 Module Adapter.
- C13 module switches.
- C18 organization structure / formal scope.

K Scope Shim temporary fields:

| Field | Value |
| --- | --- |
| `workspace_key` | `default_independent_store` |
| `business_context` | `independent_store` |
| `scope_mode` | `adapter_pending` |

Runtime expectations for future K code:

- API default is disabled.
- Frontend menu default is hidden.
- Fallback access allows only owner or K-prefixed permissions.
- Formal adapter connection waits for C07/C08/C13/C18.
- K series must not invent a permanent scope system.
- K series must not modify core `users`, `roles`, `permissions`, or `organizations` structures.

## 3. Allowed Future Draft Paths

The following paths are allowed as future K-series draft paths only. K01 does not create them.

```text
backend/app/modules/k_series/product_knowledge/**
tests/backend/modules/k_series/product_knowledge/**
frontend/src/modules/k-series/product-knowledge/**
docs/k_series/K_*
backend/alembic/versions/*k_series*product*knowledge*.py
```

## 4. Forbidden Paths And Actions

- Do not modify C01-C20 docs unless the owner approves adding index links only.
- Do not modify existing core `users`, `roles`, or `permissions` logic.
- Do not modify existing core scope logic.
- Do not modify `operation_logs` table structure.
- Do not read production or staging env files.
- Do not modify production or staging env files.
- Do not modify the n8n draft lane.
- Do not modify P-series workflow JSON.
- Do not modify existing migrations.
- Do not modify Docker production configuration.
- Do not default K series into all-user menus.
- Do not write business code during K01.
- Do not create migrations during K01.
- Do not run Docker, Alembic, Postgres, staging scripts, or production scripts during K01.
- Do not connect DeepSeek, OpenAI, Claude, SERP, WooCommerce, n8n, Google Sheets, WeCom, MinIO, Filebrowser, or any other live service during K01.

## 5. K Series Red Lines

- K series does not occupy C series numbering.
- K series is not C07.
- K series is not P series.
- K01/K02/K03 are task numbers, not module names.
- K series must not be developed in the main worktree concurrently with C series work.
- K series must not change core `users`, `roles`, `permissions`, or scope tables.
- K series must not read production or staging env.
- K series must not connect real DeepSeek, OpenAI, Claude, SERP, WooCommerce, n8n, Google Sheets, WeCom, MinIO, Filebrowser, or any other live service unless the corresponding C task is complete and the owner approves.
- K series must not go online by default.
- K series must not be visible to all users by default.
- n8n must not write directly to the Barong database.
- Google Sheets must not remain the long-term source of truth for Product Knowledge.

## 6. Release Boundary

- Staging and production releases are isolated from K01.
- K production dormant release waits for later K readiness, staging acceptance, and owner approval.
- K production enable waits for C07/C13/C18/C14/C16 and owner approval.
- Audit page display waits for C17.
- Formal n8n / P series integration waits for C15 and a stable K API.
