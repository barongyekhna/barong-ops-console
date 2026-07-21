# W-S 货源直达 · Codex 规格 v1

> 目标:订单进 W-S 后,**每件商品旁自动出现「货源」按钮,点击直达 1688 采购页**——把"翻记录找货源"变成"点一下"。数据与界面都归 W-S 物流网络中枢(用户拍板:不放 K)。采购下单永远人工(死命令:永不自动履约,本功能只缩短"找",不碰"买")。
> 分工:Codex = 表 + 迁移 + CRUD API + 订单富化 + 前端;Claude = SKU 历史清理、F 系列 1688 链接自动灌入(二期钩子)、端到端验证。无远程仓库不 push。

## 0. 归属
挂在**现有 W-S 模块**(`backend/app/modules/w_series/`),权限沿用 `w.site_ops.read` / `w.site_ops.manage`。**不新增侧边栏条目**——界面全部在 `/w-s` 现有页面内(F 系列侧边栏一个字符都不许碰,死命令)。

## 1. 数据模型 + 迁移
表 `w_product_sources`(SKU → 货源,一对一):
- id UUID pk
- `sku` String(64) **unique + index**(存储前 trim + 大写归一;这是与订单 items_json 对齐的唯一键)
- `source_url` String(1000) 必填(1688 商品页链接;esc 校验 http/https)
- `supplier_name` String(200) 可空
- `unit_cost` Numeric(12,2) 可空、`currency` String(8) 默认 "CNY"
- `moq` Integer 可空(起订量)
- `notes` Text 可空(如"要选蓝色款/找王经理")
- created_at / updated_at
**迁移铁律照旧**:先 `ls backend/alembic/versions/` 找 head,单链不分叉;**迁移不自动跑**(Claude 手动执行后才发版)。

## 2. API(控制台登录态)
- `GET /api/app/w/sources?query=&page=` —— 货源库列表,query 同时模糊匹配 sku/supplier_name;倒序分页
- `PUT /api/app/w/sources/{sku}` —— upsert(存在即改,不存在即建);body 含上表字段;sku 归一后作键
- `DELETE /api/app/w/sources/{sku}`
- 权限:读 `w.site_ops.read`,写/删 `w.site_ops.manage`

## 3. 订单富化(核心体验)
`orders_list`(`GET /api/app/w/orders`)响应中,每笔订单的 items 增加货源字段:
- 对 `items_json` 里每个 item 的 `sku`(归一后)批量查 `w_product_sources`(**一次 IN 查询,不许 N+1**)
- item 增加:`source_url`、`supplier_name`、`unit_cost`、`currency`、`moq`、`source_state`:
  - `linked` —— 有货源
  - `missing` —— 无货源记录(含 sku 为空的历史单)
- fail-safe:货源查询任何异常不影响订单列表返回(降级为全 missing)

## 4. 前端(全部在 `/w-s` 页内)
**A. 订单行内徽章**(订单与物流面板,每件商品旁):
- `linked` → **[1688 下单 ↗]** 按钮(`target="_blank"` 直达 source_url)+ 悬浮/小字显示 供应商名 · ¥进货价 · 起订量(有则显示)
- `missing` → 琥珀色「补货源」小按钮 → 弹内联小表单(sku 预填只读,填 source_url 等)→ 提交即 upsert,行内立即变 linked,**不跳页**
**B. 货源库管理区**(同页新增一个折叠面板/页签「货源库」):
- 表格:SKU / 供应商 / 进货价 / 起订量 / 链接(点开)/ 备注 / 编辑 / 删除
- 顶部搜索框 + 「新增货源」
- 风格走现有 command-center 家规(复用现有表格/徽章样式,globals.css 追加层)
**C. 新增 API 路径登记前端代理白名单**(契约测试会抓)。

## 5. 测试
- 后端:upsert 归一(" igl-001 " 与 "IGL-001" 同键)、订单富化 linked/missing 各覆盖、批量 IN 无 N+1(断言查询次数)、异常降级 fail-safe、权限(read 不能写)。`bash scripts/run_backend_tests.sh unit` 全绿
- 前端:`npm test -- --run` 全绿(含代理白名单)

## 边界(v1 不做)
- 不做多货源/候选列表(一 SKU 一主货源;F 系列多候选由 Claude 的二期钩子选主灌入)
- 不做采购状态跟踪、不做跨订单采购汇总(二期)
- 不碰 K 系列任何表;不做自动下单(死命令)

## 硬约束
别动 Claude 的 WP 插件目录;别动 F;fail-safe/权限照抄既有系列;每任务一句根因/做法;本地提交+双端测试绿。

## 交付后 Claude 接管
手动迁移 → 发版 → 造真实货源数据 + 用现有测试订单端到端验证徽章/直达/补录 → F 系列 1688 自动灌入钩子(Claude 自做,不在本规格内)。
