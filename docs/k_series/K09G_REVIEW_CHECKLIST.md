# 1. K09G 边界检查

- 是否只创建 docs/k_series/K09G_*.md。
- 是否没有 Python code。
- 是否没有 frontend code。
- 是否没有 tests。
- 是否没有 migration。
- 是否没有 backend runtime 修改。
- 是否没有 frontend runtime 修改。
- 是否没有 router registration。
- 是否没有 Docker/Alembic/Postgres/staging/production。
- 是否没有 env。
- 是否没有 live services。
- 是否没有 P-series workflow JSON 读取/修改。
- 是否没有 n8n draft lane 修改。

# 2. UI design checklist

- 是否覆盖 product dimensions。
- 是否覆盖 package dimensions。
- 是否覆盖 product weight。
- 是否覆盖 package/shipping weight。
- 是否覆盖 future volume。
- 是否覆盖 future temperature。
- 是否明确 product/package separation。
- 是否明确 net/gross/package/shipping separation。
- 是否明确 no free-text parser。
- 是否明确 missing/unknown not zero。
- 是否明确 AI no guessing。
- 是否明确 original values not overwritten。
- 是否明确 display market behavior。
- 是否明确 hidden-by-default K07 boundary。

# 3. 后续进入条件

- K09G 通过后，可以进入 K09H 或 K07A。
- K09I runtime integration 仍 blocked。
- K07 frontend code 仍需单独 owner approval。
- K07 正式菜单仍 blocked until C13/formal module switch path.
- K10 live provider 仍 blocked until C14/C09.
- K07A 如进入，也必须 hidden-by-default，不挂正式菜单，不接正式 scope，不接 live provider。
- K09H 如进入，应继续保持 docs/mock-output boundary，不能暗示 live AI provider 接入。
