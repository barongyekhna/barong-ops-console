# M 系列(制造库存)· 规格 v1

> 目标:制造公司名下的纯计算库存账(无 AI、无 n8n)。物料台 + 成品台共用**一本只增不删的流水账**,生产按配件清单(BOM)自动扣料(含箱规),发货扣成品,任何库存数字都能点开看是哪几笔流水加出来的。
> 拍板(2026-08-21):系列名 M,module key `mfg.inventory`,前端显示「库存」;**绝不联动 K/P**;**只出现在 factory 类型组织下**;**负库存拦死**。

## 0. 归属与门禁(三层)
- **工厂定位**:服务层 `resolve_factory_context()` 查「唯一的 active `org_type='factory'` 组织」,0 个 → 503「未配置制造组织」,>1 个 → 503「多工厂尚未支持」。**不依赖请求 org 上下文**——owner 在两家组织都有成员关系,中间件把 owner 的请求算死在最早建的贸易公司,所以 M 系列的表**没有 `org_id` 列**(叫 `factory_org_id`),避开 C18G 自动盖章;查 `organizations` 时用 `without_org_data_isolation()`(该表自身也受隔离)。
- **角色硬门** `user_may_access()`:owner 放行;super_admin 仅当 `user.organization_id == factory_org_id`;其他一律 403。**不看权限码**,`mfg.inventory.read/manage` 只为满足注册表/侧边栏契约。
- **隐藏**:`module_control_center._module_allowed_for_organization` 按 `org_type=="factory"`;`module_registry.FACTORY_ONLY_MODULE_KEYS` + `_user_has_factory_org_access` 过滤 `/modules/me`;前端 `ORGANIZATION_MODULE_PREFIXES` 加 `"mfg."`。
- 吉林制造公司 `org_type` 原为死字段 `store`,迁移 `20260821_03_factory_org_type` 按 org_id 改为 `factory`。

## 1. 数据模型(`backend/app/modules/m_series/inventory/models.py`)
| 表 | 要点 |
|---|---|
| `mfg_items` | `kind` part/product 共用主档;`code` 工厂内唯一;`unit` 自由文本(不换算);`is_archived`(有流水只能归档不能删) |
| `mfg_bom_lines` | `mode` `per_unit`(每件消耗 qty)/ `per_carton`(每 qty 件装一箱,**向上取整**);UNIQUE(product, part);part 必须 kind=part(一期不做成品套成品) |
| `mfg_documents` | `doc_type` receipt/production/shipment/adjustment;`doc_no` 如 `PR-000012`;`payload_json` 生产单冻结 BOM 快照;**永不改/删** |
| `mfg_movements` | 一张单据挂 N 行 ±`qty_delta` Numeric(14,3);**库存 = SUM(qty_delta)**,没有可手改的库存字段 |
| `mfg_doc_counters` | (factory, doc_type) → next_no,取号 FOR UPDATE |

## 2. 四个动作(`service.py`)
- 入库 receipt:多行 +qty。
- 生产 production:按 id 顺序 `FOR UPDATE` 锁相关 item 行 → 算需求 vs 库存 → **任一不足整单拒绝**(`InsufficientStock` → HTTP 409,带逐项缺口)→ 写单据(快照)+ N 行负流水 + 1 行正流水,一个事务。
- 发货 shipment:锁行,stock ≥ qty 否则 409。
- 盘点调整 adjustment:原因必填;结果不得为负。
- 预演 `GET /mfg/production/preview`:只算不写,前端实时显示「将扣 / 缺」。

## 3. 端点(`/api/app/mfg`,前端代理 `isAllowedMfgPath`)
`GET /context`;`GET/POST /items`;`PATCH /items/{id}`;`GET /items/{id}/movements`;`GET/PUT /items/{id}/bom`;`GET /stock`;`GET /production/preview`;`POST /documents/{receipt|production|shipment|adjustment}`;`GET /documents`;`GET /documents/{id}`。

## 4. 前端(`frontend/src/modules/m/inventory/`,路由 `/mfg-inventory`)
三页签:物料 / 成品 / 单据。成品行:配件清单编辑器(选物料 + 每件消耗/每箱装 + 数量)、生产(实时预演,有缺口提交键禁用)、发货;物料行:入库;两者:调整、归档、点行看流水;单据可点开看快照与流水。

## 5. 一期不做
多级 BOM 的 UI、批次、成本、单位换算、生产单手工微调扣料、删除/作废单据(错了用盘点调整)、多工厂。

## 6. 验证
- `scripts/run_backend_tests.sh integration`:`tests/backend/test_mfg_inventory.py`(桌子例子 1000/800/500 → 生产 100 扣 100/400/100;201 套报桌腿缺 4 且零写入;箱规 105÷10=11;发货超量/调整为负拒绝;单号连续;快照)+ `test_mfg_access.py`(角色门、503、HTTP 端到端)。
- `scripts/run_frontend_tests.sh`:导航/前缀/manifest/代理白名单漂移。
- 线上验收:owner 在吉林下见「库存」、深圳下不见;贸易 super_admin 直敲 `/api/app/mfg/stock` 得 403。
