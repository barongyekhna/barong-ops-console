# K06 Deferred Runtime Registration Gate

Status: K06 runtime registration deferred, pending owner review.

Date: 2026-06-12.

## 1. 当前决策

K06 runtime registration 暂不执行。

K router 暂不注册。

K API 仍然保持 unregistered + disabled-by-default + not externally reachable。

## 2. 为什么冻结 K06 runtime registration

- K06B 已创建 backend module skeleton，但 router 未注册。
- K06C 已证明 isolated import smoke 通过。
- K06E 已证明 non-DB contract tests 通过。
- 当前 K 后端模块是安全存在但未插入总控 runtime 的积木。
- 直接注册 router 可能触碰 main.py、core router registry、core config、core permissions、core auth/deps。
- 一旦注册 router，即使 feature flag 默认 false，路径也可能进入外部可达面。
- K branch 还需要和 C07G 封板后的最新主线做同步/兼容性审查。
- C08/C13/C18 相关正式 adapter、module switch、formal scope 状态仍需复核。
- 因此 K06 runtime registration 必须冻结，等后续老板单独批准。

## 3. 冻结范围

- 不改 backend/app/main.py。
- 不改 backend/app/core/config.py。
- 不改 backend/app/core/permissions.py。
- 不改 backend/app/api/deps.py。
- 不改 backend/app/models/__init__.py。
- 不注册 router。
- 不接 frontend menu。
- 不接 staging/production。
- 不接 live provider。
- 不接 n8n。
- 不接 WooCommerce。
- 不写 Google Sheets。

## 4. 解除冻结条件

只有满足以下条件，才允许进入 K06F minimal disabled router registration：

- K06-REM-01 reviewed and approved。
- K branch 与 C07G 最新主线同步策略明确。
- 同步后 K06C/K06E 重新通过或被确认无需重跑。
- Alembic heads/down_revision 已复核。
- C07 router/module isolation pattern 已确认。
- C08/C13/C18 状态已复核。
- API 仍然 disabled-by-default。
- no frontend menu exposure。
- no live provider。
- no staging/production。
- rollback plan exists。
- owner explicitly approves K06F。
