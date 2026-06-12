# K06 Review Checklist

Status: K06A review checklist draft, pending owner review.

Date: 2026-06-12.

## 1. K06A 审核清单

- [ ] 是否只创建 `docs/k_series/K06_*.md`。
- [ ] 是否没有 backend runtime。
- [ ] 是否没有 frontend runtime。
- [ ] 是否没有 tests。
- [ ] 是否没有 migration。
- [ ] 是否没有 Docker/Alembic/Postgres。
- [ ] 是否没有 staging/production。
- [ ] 是否没有 env。
- [ ] 是否没有 live services.
- [ ] 是否没有修改 `/opt/barong-ops-console` 主工作树。
- [ ] 是否没有修改 C01-C20 编号。
- [ ] 是否没有修改 C 系列文档。
- [ ] 是否没有读取或处理 P-series workflow JSON。
- [ ] 是否没有修改 n8n draft lane。
- [ ] 是否没有修改 README.md / CHANGELOG.md / backend README。

## 2. K06B 进入条件

- [ ] K06A reviewed by owner.
- [ ] ChatGPT review passed.
- [ ] worktree clean.
- [ ] owner explicitly approves backend runtime skeleton.
- [ ] K06B prompt limited to allowed K backend paths.
- [ ] API disabled by default.
- [ ] no frontend.
- [ ] no staging/prod.
- [ ] no live provider.
- [ ] no env read.
- [ ] no Docker/Alembic/Postgres unless separately approved in a future task.
- [ ] If route registration outside K module is required, owner explicitly
  approves the exact runtime touchpoint.

## 3. K06B 禁止事项

- no core table changes.
- no auth/permission core rewrite.
- no official scope implementation.
- no operation_logs table change.
- no provider live call.
- no P-series modification.
- no frontend menu.
- no production/staging env.
- no hard delete endpoint in first-version CRUD.
- no default API enablement.
- no bypass of K Scope Shim.
- no direct n8n database write path.
