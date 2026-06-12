# K06 Deferred Core Touchpoints

Status: K06 core touchpoints deferred, pending owner review.

Date: 2026-06-12.

## 1. 高危 core touchpoints

| Future touchpoint | Why it may be needed later | Approval |
| --- | --- | --- |
| `backend/app/main.py` | Future minimal router registration may need an explicit `include_router` entry or equivalent runtime hook. | requires owner approval |
| `backend/app/core/config.py` | Future K feature flag may need to move from module-local fallback to official core configuration or module switch settings. | requires owner approval |
| `backend/app/core/permissions.py` | Future K permission keys may need formal core permission registry registration. | requires owner approval |
| `backend/app/api/deps.py` | Future K route access may need official auth/dependency integration instead of the dormant module-local boundary. | requires owner approval |
| `backend/app/models/__init__.py` | Future model autoload or Alembic discovery behavior may require explicit registry changes. | requires owner approval |
| C07 module registry files if any | Future formal module registration may need to use the C07 module registry pattern once confirmed. | requires owner approval |
| C08 module adapter files if any | Future module adapter integration may need to connect K to the official C08 adapter. | requires owner approval |
| C13 module switch files if any | Future module enable/disable behavior may need to use official C13 module switch enforcement. | requires owner approval |
| C18 scope adapter files if any | Future formal scope behavior may need to replace the temporary K Scope Shim with C18 scope adapter integration. | requires owner approval |

## 2. 为什么它们高危

- main.py / router registry 会让 K API 进入 runtime。
- core config 会影响全局配置行为。
- core permissions 会影响权限体系。
- core auth/deps 会影响认证授权边界。
- models registry 可能影响 Alembic/autoload 行为。
- C07/C08/C13/C18 文件属于总控平台，不应由 K 系列擅自改。

## 3. 当前替代策略

- K backend module 保持 unregistered。
- K feature flag 使用 module-local fallback，默认 false。
- K permissions 保持 constants，不注册 core registry。
- K Scope Shim 保持 workspace_key / business_context / scope_mode。
- 只在 K 自己模块路径内继续做低风险 mock / unit / service work。

## 4. 后续触碰规则

- 每个 core touchpoint 必须单独任务、单独批准、单独 review。
- 不允许一个 prompt 同时改 main.py、config、permissions、scope、frontend。
- 不允许顺手接 staging/production。
- 不允许顺手接 live provider。
- 不允许顺手接 n8n。
