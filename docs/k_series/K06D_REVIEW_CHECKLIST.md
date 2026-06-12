# K06D Review Checklist

Status: K06D review checklist draft, pending owner review.

Date: 2026-06-12.

## 1. K06D 边界检查

- [x] 是否只创建 `docs/k_series/K06D_*.md`.
- [x] 是否没有修改 Python code.
- [x] 是否没有注册 router.
- [x] 是否没有修改 `backend/app/main.py`.
- [x] 是否没有修改 core config.
- [x] 是否没有修改 core permissions.
- [x] 是否没有修改 core auth/deps.
- [x] 是否没有写 frontend.
- [x] 是否没有写 tests.
- [x] 是否没有创建 migration.
- [x] 是否没有运行 Docker/Alembic/Postgres/staging/production.
- [x] 是否没有读取 env.
- [x] 是否没有连接 live services.
- [x] 是否没有修改 `/opt/barong-ops-console` main worktree.
- [x] 是否没有修改 C01-C20 编号.
- [x] 是否没有修改 C 系列文档.
- [x] 是否没有读取或处理 P-series workflow JSON.
- [x] 是否没有修改 n8n draft lane.
- [x] 是否没有修改 README.md.
- [x] 是否没有修改 CHANGELOG.md.
- [x] 是否没有修改 `backend/README.md`.

## 2. K06E 进入条件

- [ ] K06D reviewed by owner.
- [ ] ChatGPT review passed.
- [ ] worktree clean.
- [ ] owner approves writing backend tests.
- [ ] tests limited to allowed K test path.
- [ ] no router registration.
- [ ] no staging/prod.
- [ ] no production/staging env read.
- [ ] no live services.
- [ ] no frontend.
- [ ] no migration.
- [ ] no core config/permissions/deps changes.

## 3. K06F 进入条件

- [ ] K06E pass.
- [ ] owner explicitly approves router registration.
- [ ] C07 registration pattern confirmed.
- [ ] C08/C13/C18 status reviewed.
- [ ] API remains disabled by default.
- [ ] no frontend menu exposure.
- [ ] no live provider.
- [ ] no staging/prod.
- [ ] rollback plan exists.
