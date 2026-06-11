# K Series Memory Baseline

Status: approved baseline for K01.

This document records the engineering memory baseline for the K series. It is documentation only. K01 does not add business code, migrations, runtime configuration, or live-service integration.

## 1. Series Boundary

- C series = Barong Ops Console Core / Console 总控平台任务.
- K series = Knowledge / 产品知识库 / 白苏婉 2.0.
- P series = n8n 产品页自动化工作流.
- K series is not C07.
- K series does not occupy C series numbering.
- K series is not P series.
- K series currently refers only to the Product Knowledge board.
- K01/K02/K03 are internal K series task numbers, not module names.

## 2. Product Knowledge Goal

- Replace Google Sheets `Product_Knowledge`.
- Store product information in Barong's own database.
- Support input in any language.
- In the future, call DeepSeek V4 Pro to translate, normalize, and structure product input into English canonical product data.
- English is the primary record language.
- Operators can review and edit the English structured result.
- The multilingual review interface must not use ordinary machine translation; it must use DeepSeek V4 Pro in the future.
- Support dimensions, weight, unit selection, and target-market unit conversion.
- Support high-quality English selling-point refinement.
- After product entry succeeds, provide a keyword research button.
- Future keyword flow: SERP -> ChatGPT filtering -> Claude second-pass filtering.
- Main keywords, secondary keywords, and risk keywords are written into the K database and remain manually editable.
- K series will later provide data to P series, page generation, WooCommerce drafts, image generation, ad material generation, and related modules.

## 3. Scope-Adapter-Pending Strategy

Current architecture reality:

- C07 module isolation is not fully complete.
- C08 Module Adapter is not fully complete.
- C13 module switches are not fully complete.
- C18 organization structure / formal scope is not fully complete.

K series therefore starts as `scope-adapter-pending`.

Rules:

- K series may build functionality while keeping the adapter pending.
- K series must use a K Scope Shim.
- K series must not invent a formal scope system.
- K series must not modify the core `users`, `roles`, `permissions`, or `organizations` structure.
- K series must remain independent, closable, migratable, and ready for later connection to the C console.

Temporary shim fields:

| Field | Value |
| --- | --- |
| `workspace_key` | `default_independent_store` |
| `business_context` | `independent_store` |
| `scope_mode` | `adapter_pending` |

Default behavior:

- API default: disabled.
- Frontend menu default: hidden.
- Fallback access: owner or K-prefixed permission only.
- Formal adapter integration waits for C07/C08/C13/C18 completion.

## 4. Multi-Layer Isolation

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

## 5. C Series Dependencies

- Formal module registration waits for C07/C08/C13.
- Formal scope integration waits for C18.
- Live provider secret rules wait for C14.
- Provider execution waits for C09.
- Approval gates wait for C12.
- Formal n8n / P series integration waits for C15.
- Production enable waits for C16.
- Audit page display waits for C17.

## 6. Red Lines

- Do not occupy C series numbering.
- Do not develop K series concurrently in the main worktree with C series work.
- Do not modify core `users`, `roles`, `permissions`, or scope tables.
- Do not read production or staging env files.
- Do not connect real DeepSeek, OpenAI, Claude, SERP, WooCommerce, n8n, Google Sheets, WeCom, MinIO, Filebrowser, or any other live service unless the corresponding C task is complete and the owner approves it.
- Do not enable K series by default in production.
- Do not make K series visible to all users by default.
- Do not allow n8n to write directly to the Barong database.
- Do not keep Google Sheets as the long-term source of truth for Product Knowledge.
