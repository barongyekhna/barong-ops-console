# K09 Review Checklist

Status: K09A review checklist, pending owner review.

Date: 2026-06-12.

# 1. K09A 边界检查

- 是否只创建 `docs/k_series/K09_*.md`。
- 是否没有 Python code。
- 是否没有 frontend。
- 是否没有 tests。
- 是否没有 migration。
- 是否没有 backend runtime。
- 是否没有 frontend runtime。
- 是否没有 Docker/Alembic/Postgres/staging/production。
- 是否没有 env。
- 是否没有 live services。
- 是否没有 P-series workflow JSON 读取/修改。
- 是否没有 n8n draft lane 修改。
- 是否没有 router registration。

# 2. Unit baseline checklist

- 是否覆盖 supported length units。
- 是否覆盖 supported weight units。
- 是否覆盖 optional volume units。
- 是否覆盖 optional temperature units。
- 是否保留 `original_value` / `original_unit`。
- 是否定义 metric / imperial normalized values。
- 是否定义 `display_market`。
- 是否定义 `conversion_source`。
- 是否定义 `conversion_precision`。
- 是否禁止 AI 猜测尺寸重量。
- 是否定义 market display defaults。
- 是否定义 rounding / precision rules。
- 是否定义 error / warning categories。
- 是否支持 K07/K10/K12/K15/P-series future usage。

# 3. K09B 进入条件

- K09A reviewed by owner.
- ChatGPT review passed.
- worktree clean.
- owner approves payload contract docs.
- K09B remains docs only.
- no code / no DB / no frontend.
