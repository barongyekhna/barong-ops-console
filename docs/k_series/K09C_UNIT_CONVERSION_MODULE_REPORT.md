# K09C Unit Conversion Module Report

Status: K09C pure unit conversion helper created, pending owner review.

Date: 2026-06-12.

## 1. K09C 目标

K09C 基于 K09A/K09B 的单位基准和 payload contract，新增一个 K module-local 的纯 Python 单位换算 helper。

该 helper 只处理已经提供的 numeric value + unit，不解析自然语言、不解析 `10 x 5 x 3 cm` 这类 dimensions string，不连接 DB，不接 FastAPI router，不读 env，不连接 live services，也不做 AI guessing。

## 2. 创建的 Python 文件路径

- `backend/app/modules/k_series/product_knowledge/unit_conversion.py`

## 3. Runtime 修改确认

- 是否修改现有 runtime 文件: no，除新增 `unit_conversion.py`。
- 是否修改 `service.py`: no.
- 是否修改 `schemas.py`: no.
- 是否修改 `router.py`: no.
- 是否修改 `models.py`: no.
- 是否注册 router: no.
- 是否连接 DB: no.
- 是否读取 env: no.
- 是否连接 live services: no.

## 4. 支持单位列表

Length:

- `mm`
- `cm`
- `m`
- `in`
- `ft`

Weight:

- `g`
- `kg`
- `oz`
- `lb`

Volume:

- `ml`
- `l`
- `fl_oz`

Temperature:

- `c`
- `f`

安全 alias 会 canonicalize 到上述单位，例如 `inch` / `inches` -> `in`，`foot` / `feet` -> `ft`，`gram` / `grams` -> `g`，`kilogram` / `kilograms` -> `kg`，`ounce` / `ounces` -> `oz`，`pound` / `pounds` -> `lb`，`liter` / `litre` / `liters` / `litres` -> `l`。

未支持单位例如 `stone`、`yard` 或未列出的 meter 拼写不会被猜测，会返回 `unsupported_unit`。

## 5. Conversion Rules Summary

Length:

- `1 m = 100 cm`
- `1 cm = 10 mm`
- `1 in = 2.54 cm`
- `1 ft = 12 in`

Weight:

- `1 kg = 1000 g`
- `1 lb = 16 oz`
- `1 lb = 0.45359237 kg`
- `1 oz = 28.349523125 g`

Volume:

- `1 l = 1000 ml`
- `1 fl_oz = 29.5735295625 ml`

Temperature:

- `c -> f = c * 9/5 + 32`
- `f -> c = (f - 32) * 5/9`

默认输出 precision 为 2 decimal places，并用 `conversion_precision = "2_decimal_places"` 标记。conversion 不输出 Decimal object 到 payload。

## 6. Market Display Default Summary

- `US`: length -> `in`, weight -> `lb`, volume -> `fl_oz`, temperature -> `f`.
- `EU`: length -> `cm`, weight -> `kg`, volume -> `l`, temperature -> `c`.
- `AU`: length -> `cm`, weight -> `kg`, volume -> `l`, temperature -> `c`.
- `fallback`: metric defaults.
- `UK` / `CA`: K09C 没有产品上下文，使用 metric fallback，并返回 `market_display_unknown` warning，留给 K09G/K07 按产品上下文细化。
- missing / unknown / unrecognized display market: 使用 metric fallback，并返回 `market_display_unknown` warning。

Display choice 不会覆盖 `original_value` 或 `original_unit`。

## 7. Error / Warning Vocabulary

Errors:

- `unsupported_unit`
- `missing_unit`
- `missing_value`
- `invalid_numeric_value`
- `conversion_not_possible`
- `ai_guessing_forbidden`
- `original_value_missing`

Warnings:

- `precision_loss_warning`
- `market_display_unknown`

## 8. 留给后续任务

- K09D: 为 `unit_conversion.py` 写 non-DB unit tests。
- K09E: dimensions / package_dimensions / weight / package_weight 组合 payload helper 和 validation helper。
- K09G: K07 前端单位输入和 product-context market display 细化。
- K09H: K10 / AI mock adapter 单位输出约束和 no-guessing 对齐。
- K09I: 未来如需进入 service create/update 流程，必须单独审批 runtime integration。

## 9. 是否建议进入 K09D

Yes. 建议进入 K09D，补齐纯函数 non-DB tests，覆盖 supported units、aliases、missing value、missing unit、unsupported unit、cross-group conversion、market display fallback、temperature conversion、AI guessing forbidden。
