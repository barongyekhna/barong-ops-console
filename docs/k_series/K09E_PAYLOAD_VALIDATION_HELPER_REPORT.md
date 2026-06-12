# K09E Payload Validation Helper Report

Status: K09E helper created and Docker pytest passed, pending owner review.

Date: 2026-06-12.

## 1. K09E 目标

K09E 基于 K09B payload contract 和 K09C `unit_conversion.py`，新增一个 K module-local helper，用于构建和校验：

- `dimensions_json`
- `package_dimensions_json`
- `weight_json`
- `package_weight_json`

K09E 只组合已经拆分好的 numeric value + unit，不解析自然语言尺寸文本，不猜测缺失尺寸/重量/包装尺寸/净重/毛重/运输重量，不接入 service create/update 流程，也不改变现有 runtime 行为。

## 2. 创建的 Python helper 文件路径

- `backend/app/modules/k_series/product_knowledge/unit_payloads.py`

## 3. 创建的 test 文件路径

- `tests/backend/modules/k_series/product_knowledge/test_unit_payloads.py`

## 4. 是否修改 unit_conversion.py

No.

## 5. 是否修改 service.py / schemas.py / router.py / models.py / __init__.py

No.

## 6. 是否注册 router

No.

## 7. 是否连接 DB

No.

## 8. 是否读取 env

No.

## 9. 是否连接 live services

No.

## 10. 是否运行 Alembic/Postgres/staging/production

No.

## 11. Helper 支持的 payload

`unit_payloads.py` 支持以下 builder 和 validator：

- `build_dimensions_payload`
- `build_package_dimensions_payload`
- `build_weight_payload`
- `build_package_weight_payload`
- `validate_dimensions_payload`
- `validate_package_dimensions_payload`
- `validate_weight_payload`
- `validate_package_weight_payload`
- `collect_payload_errors`
- `collect_payload_warnings`

## 12. Validation behavior summary

- Validation 不连接 DB、不调用外部服务、不读取 env。
- Validation 不 mutate input payload。
- Validation 会递归收集 nested Unit Value Payload 的 `errors` / `warnings`。
- Validation 会调用 K09C `validate_unit_value_payload` 校验 nested Unit Value Payload。
- 任意 error 会使 `is_valid = false`。
- Missing / unknown 不会转换为 `0`。
- Package payload validation 会拒绝混入 product keys，例如 package dimensions 中的 `length` / `width` / `height`，以及 package weight 中的 `net_weight` / `gross_weight`。

## 13. No free-text parser boundary

K09E 不解析 `10 x 5 x 3 cm`、`weight: 2 lb` 或其他自然语言/free-text input。

K09E 可以保留 `source_text` 和 `parsed_from_text` metadata，但不会从 `source_text` 推导 `length` / `width` / `height` / `net_weight` / `package_weight` 等字段。无 numeric args 时会保留 missing error，并可返回 `free_text_parsing_not_supported` warning。

## 14. AI guessing forbidden behavior

当 `conversion_source = "ai_structured_from_provided_input"`：

- 已提供的 numeric value + unit 可以被结构化并交给 K09C normalize。
- Missing value / missing unit 仍会保留 `missing_value` / `missing_unit` / `conversion_not_possible`。
- 对 AI source 下 missing value/unit 的 attempted field，会补充 `ai_guessing_forbidden`。
- Helper 不会生成缺失的 width / height / package_weight / net_weight。
- Helper 不会推断 net/gross 或 package/shipping distinction。

## 15. py_compile 结果

Command:

```bash
PYTHONPYCACHEPREFIX=/tmp/k09e_pycache python3 -m py_compile backend/app/modules/k_series/product_knowledge/unit_payloads.py tests/backend/modules/k_series/product_knowledge/test_unit_payloads.py
```

Result: passed.

## 16. pytest 结果

Local command:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m pytest tests/backend/modules/k_series/product_knowledge/test_unit_payloads.py -q
```

Local result: failed before collection because local Python does not have `pytest` installed.

```text
/usr/bin/python3: No module named pytest
```

Docker pre-check rerun:

```text
No temporary npm run build / safe release / test_db / c07 / c08 blocker was found.
```

Docker note:

- The first `docker-compose run --rm --no-deps backend ...` used a stale backend image and could not find `tests/backend/modules/k_series/product_knowledge/test_unit_payloads.py`.
- The isolated backend image was rebuilt under the same K09E project so the container included the current untracked K09E files.
- No Postgres dependency was started because pytest was run with `--no-deps`.

Docker pytest command:

```bash
docker-compose -p barong-k-series-product-knowledge-test -f docker-compose.example.yml run --rm --no-deps backend sh -c 'PYTHONPATH=/app pytest tests/backend/modules/k_series/product_knowledge/test_unit_payloads.py -q'
```

Docker pytest result:

```text
27 passed in 0.90s
```

## 17. Docker project name if used

Used isolated project:

- `barong-k-series-product-knowledge-test`

## 18. Docker cleanup result if used

Docker cleanup command:

```bash
docker-compose -p barong-k-series-product-knowledge-test -f docker-compose.example.yml down -v
```

Docker cleanup result:

- passed.
- The isolated network `barong-k-series-product-knowledge-test_default` was removed.
- No staging/prod container was stopped.

## 19. 失败/跳过项和原因

- Local pytest: skipped/failed because `pytest` is not installed in local Python.
- First Docker pytest attempt: failed before collection because the stale backend image did not include current untracked K09E files.
- Docker pytest after isolated backend rebuild: passed, `27 passed in 0.90s`.
- Test blocker report removed because the blocker was resolved.

## 20. 是否建议进入 K09F / K09G / K09H / K09-SEAL

- K09F: may proceed only after owner review.
- K09G: only after owner review.
- K09H: only after owner review.
- K09-SEAL: not recommended until owner reviews K09A-K09H readiness.
