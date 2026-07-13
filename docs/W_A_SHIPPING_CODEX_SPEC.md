# W-A 运费中枢 · Codex 施工指令（含 K/P 欠账）

> 交付人：Codex。验收人：用户 + Claude（完工后逐条对照本文验收）。
> 本文是**唯一需求来源**。有歧义按本文字面执行，不要自由发挥——尤其是前端：
> **所有 UI 文案、布局、CSS 均已在本文给定，逐字使用，禁止自创样式与文案。**

---

## 0. 背景与三条死命令

独立站即将由 F 系列（类目富化）批量灌入产品，走 K→I→P 链上架 WooCommerce。
当前产品上架时**没有运费模板归属**——本任务建立「运费中枢」：确定性规则表
自动给产品分配 Woo 运费模板（shipping class），并补齐两笔欠账：K 的运费字段
治理 + P 的运费硬门。

死命令（违反任何一条 = 验收直接打回）：

1. **永不自动履约**。本模块只管"产品归属哪个运费模板"，不得出现任何
   自动创建订单/履约/发货的代码或预留接口。
2. **模块只挂国际贸易组织**（详见 §7 组织门）。
3. **分配靠查表不靠猜**。不得引入任何 AI/启发式判断运费归属；规则引擎必须
   100% 确定性、可解释（每次分配记录命中的规则）、fail-closed（缺数据不分配）。

---

## 1. 范围

**做：**
- 新表 `w_shipping_classes`（模板登记）+ `w_shipping_rules`（分配规则）+ migration
- 确定性分配引擎（重量段位 + 带电覆盖 + 美国仓覆盖，体积重取大）
- K 产品表加 4 列：`contains_battery` / `us_stock` / `shipping_assignment_json` / `shipping_review_needed`
- 后端 API（§5 端点清单）
- P 运费硬门（gate_blockers）+ 上架契约加 `shipping_class` 字段
- 新前端页面 `/w-a`（运费中枢驾驶舱，§8 有完整骨架代码）
- 模块注册 / 权限 / 组织门 / 代理白名单 / 导航（§7、§9 有精确清单）
- 测试（§10 用例清单，三通道跑绿）

**不做（明确排除，不要顺手做）：**
- 政策页 / GMC 审计（W-A 后续刀）
- H 系列任何内容（404/健康巡检——另一个执行者在做，别碰）
- K 前端（products 页面）任何改动——运费的全部 UI 都在新的 /w-a 页面里
- n8n 工作流本身（契约字段加好即可，n8n 侧用户自己改）
- 不部署。交付 = 提交到 main（提交规范见 §12）
- 不碰 `backend/app/modules/f_series/`、`frontend/src/modules/f/`、
  `frontend/src/modules/c19/`、`backend/app/modules/c19/`（并行施工区）

---

## 2. 数据模型与 migration

新 migration 文件 `backend/alembic/versions/20260713_02_w_shipping_hub.py`。
**写之前必须 `ls backend/alembic/versions/` + `alembic heads` 确认当前唯一
head**（写本文时是 `20260713_01_f_sourcing_mode`，如已变化就接最新 head；
仓库出过双头事故，出双头验收直接打回）。

### 2.1 `w_shipping_classes` —— Woo 运费模板登记表

| 列 | 类型 | 约束 |
|---|---|---|
| id | Uuid PK | default uuid4 |
| slug | String(128) | NOT NULL, UNIQUE —— 必须与 WooCommerce shipping class 的 slug 完全一致 |
| name | String(255) | NOT NULL（中文名，展示用） |
| origin | String(20) | NOT NULL, server_default 'cn_direct'，CHECK IN ('cn_direct','us_stock')|
| notes | Text | nullable |
| active | Boolean | NOT NULL server_default true |
| sort_order | Integer | NOT NULL server_default 100 |
| created_at / updated_at | DateTime(timezone=True) | 照 F 表的写法（server_default func.now / onupdate） |

### 2.2 `w_shipping_rules` —— 分配规则表

| 列 | 类型 | 约束 |
|---|---|---|
| id | Uuid PK | |
| priority | Integer | NOT NULL —— 数字小的先评估 |
| rule_type | String(30) | NOT NULL, CHECK IN ('us_stock_override','battery_override','weight_band') |
| min_weight_kg | Numeric(8,3) | nullable（仅 weight_band 用，含下界） |
| max_weight_kg | Numeric(8,3) | nullable（仅 weight_band 用，不含上界；NULL=无上限） |
| shipping_class_slug | String(128) | NOT NULL（指向 w_shipping_classes.slug，不建外键，slug 软引用） |
| active | Boolean | NOT NULL server_default true |
| notes | Text | nullable |
| created_at / updated_at | 同上 | |

索引：`ix_w_rules_priority (active, priority)`。

### 2.3 K 产品表加列（`k_product_knowledge_products`）

| 列 | 类型 | 语义 |
|---|---|---|
| contains_battery | Boolean NOT NULL server_default false | 带电（锂电等）。**注意：带电≠红线**，只是运费线路不同 |
| us_stock | Boolean NOT NULL server_default false | 美国仓有现货（亚马逊仓） |
| shipping_assignment_json | JSON nullable | 分配溯源：`{"rule_id","rule_type","matched_at","weight_kg","volumetric_kg","used_kg","review_reason"}` |
| shipping_review_needed | Boolean NOT NULL server_default false | 边界值/可疑分配，待人工确认 |

（`shipping_class` 列已存在，String(128)，直接用。）

### 2.4 migration 之后必须同步两处（否则单元测试红）

1. `scripts/staging_stabilization.py` 的 `EXPECTED_ALEMBIC_HEAD` 改成新 revision id；
2. 重新生成 manifest：
   ```bash
   .venv/bin/python -c "
   import sys; sys.path.insert(0, '.')
   from scripts import staging_stabilization as st
   st.write_json(st.MIGRATION_MANIFEST_FILE, st.build_migration_manifest())"
   ```

---

## 3. 分配引擎语义（一字不差地实现）

新文件 `backend/app/modules/w_series/shipping/engine.py`。

### 3.1 输入解析（全部防御性，解析失败当 None）

- **实重 kg**：优先 `package_weight_json`，回退 `weight_json`。接受形状
  `{"value": 1.2, "unit": "kg"}`；unit 支持 kg/g/lb/磅/千克/克（g÷1000，
  lb×0.4536）；也接受裸数字（按 kg）。解析不出 → None。
- **体积重 kg**：`package_dimensions_json` 形状
  `{"length":…, "width":…, "height":…, "unit":"cm"}`（unit 支持 cm/in，
  in×2.54），体积重 = L×W×H(cm)÷6000。缺任何一边 → None。
- **计费重 used_kg = max(实重, 体积重)**，两者都 None → None。

### 3.2 评估顺序（确定性，逐条短路）

对 active 规则按 priority 升序：

1. `us_stock_override`：product.us_stock 为真 → 命中，结束。
2. `battery_override`：product.contains_battery 为真 → 命中，结束。
3. `weight_band`：used_kg 非 None 且 `min_weight_kg <= used_kg < max_weight_kg`
   （min NULL 当 0，max NULL 当 +∞）→ 命中，结束。

命中后写：`shipping_class = 规则的 slug`、`shipping_assignment_json` 溯源、
`shipping_review_needed` 按 §3.3。

### 3.3 fail-closed 与边界标记

- used_kg 为 None 且没有 override 命中 → **不分配**（shipping_class 保持
  NULL），`shipping_review_needed = True`，溯源 review_reason =
  `"重量数据缺失，无法确定性分配"`。
- weight_band 命中但 used_kg 落在命中段位任一边界的 ±10% 内 →
  照常分配，但 `shipping_review_needed = True`，review_reason =
  `"计费重 {used_kg}kg 接近段位边界，请人工复核"`。
- 规则表为空/无命中 → 不分配 + review_needed + review_reason =
  `"没有命中任何规则"`。
- **人工改过的不覆盖**：若 shipping_assignment_json 里 `rule_type == "manual"`
  （人工在台账里手选过模板），重算时跳过该产品，除非调用方传 `force=true`。

### 3.4 触发方式

- 单产品：POST `/w/shipping/assign/{product_id}`。
- 批量：POST `/w/shipping/assign-all`（全部 channel='dtc' 的 K 产品；返回
  统计 {assigned, review_needed, skipped_manual, unresolved}）。
- **不做**保存时自动触发（保持用户可控）。

---

## 4. 工程红线（仓库踩过的坑，逐条遵守）

1. **C18G 数据隔离**：严格上下文会 403 掉不带 `org_id` 字面量的裸 SQL
   （"C18G rejected raw SQL without an org_id filter"）。W 的表没有 org 列，
   **优先用 ORM（select()/db.get），必须裸 SQL 时包
   `with without_org_data_isolation():`**（from
   `backend/app/services/data_isolation.py`；F 的 service.py 有现成示例）。
2. **User.id 是 int 不是 UUID**：任何 `*_by_user_id` 列用 BigInteger。
3. **慢 HTTP 前先 `db.rollback()`** 结束事务（防 idle-in-transaction）。
   本任务没有外呼，但引擎批量重算要分批 commit（每 50 个产品一次）。
4. 权限判定复用 `resolve_current_user_permission_info`，鉴权依赖照抄
   `backend/app/modules/p_series/router.py` 的 `_require_p_permission` 模式。
5. K 列是加在 K 的表上，但**逻辑放 w_series 模块**，不要往 K 的
   service/router 里塞运费代码；K 的 models.py 只加列定义。

---

## 5. 后端 API（前缀 `/w`，挂 APPLICATION_API_PREFIX，全部人用端点）

新文件 `backend/app/modules/w_series/__init__.py`、
`backend/app/modules/w_series/router.py`、
`backend/app/modules/w_series/shipping/{__init__,models,engine,service}.py`。

| 端点 | 方法 | 权限 | 语义 |
|---|---|---|---|
| /w/shipping/classes | GET | w.site_ops.read | 模板列表（含 active=false） |
| /w/shipping/classes | POST | w.site_ops.manage | 新建模板 {slug,name,origin,notes,sort_order} |
| /w/shipping/classes/{id} | PATCH | manage | 改 name/origin/notes/active/sort_order（slug 不可改） |
| /w/shipping/rules | GET | read | 规则列表按 priority 升序 |
| /w/shipping/rules | POST | manage | 新建规则 |
| /w/shipping/rules/{id} | PATCH | manage | 改 priority/min/max/slug/active/notes |
| /w/shipping/rules/{id} | DELETE | manage | 删规则 |
| /w/shipping/simulate | POST | read | 试算：{weight_kg?, volumetric_kg?, contains_battery, us_stock} → {shipping_class_slug?, rule_id?, rule_type?, review_needed, review_reason?}（纯计算不落库） |
| /w/shipping/assign/{product_id} | POST | manage | 单产品分配（body {force: bool=false}） |
| /w/shipping/assign-all | POST | manage | 批量重算 dtc 产品 |
| /w/shipping/board | GET | read | 产品运费台账（§5.1） |
| /w/shipping/products/{product_id} | PATCH | manage | 人工干预：{shipping_class_slug?, contains_battery?, us_stock?, clear_review?: bool}。手选模板时溯源写 rule_type="manual" |

### 5.1 board 返回结构

Query 参数 `filter`: `all | unassigned | review | exported_missing`，`limit` ≤ 500。

```json
{
  "summary": {"total_dtc": 0, "assigned": 0, "unassigned": 0,
               "review_needed": 0, "exported_missing": 0},
  "items": [{
    "product_id": "...", "product_name": "...", "sku": "...",
    "channel": "dtc", "weight_kg": 1.2, "volumetric_kg": 0.8, "used_kg": 1.2,
    "contains_battery": false, "us_stock": false,
    "shipping_class_slug": "...", "shipping_class_name": "...",
    "assignment": {…溯源 json…}, "review_needed": false,
    "exported": true
  }]
}
```

`exported_missing` = 已上架（`p_upload_jobs` 里该 product 有 status='success'
的记录）但 shipping_class 为 NULL —— 这是"存量欠账"清单。

---

## 6. P 运费硬门 + 契约字段

1. `backend/app/modules/p_series/upload/assemble.py` 的 `gate_blockers`，在
   价格检查之后加：
   ```python
   if (getattr(product, "channel", "") or "").strip().lower() == "dtc" and not (
       getattr(product, "shipping_class", None) or ""
   ).strip():
       blockers.append("运费模板未分配（去 W-A 运费中枢处理）")
   ```
2. `backend/app/modules/p_series/contract/upload_package.py`：
   - `Shipping` 新 model：`class Shipping(BaseModel): model_config = ConfigDict(extra="forbid"); shipping_class: str | None = None`
   - `UploadPackage` 加字段 `shipping: Shipping = Field(default_factory=Shipping)`
   - 组包处（文件里 `google_product_category` 的映射与赋值两处旁边）同步加
     `shipping_class` 映射：值取 `product.shipping_class`。
   - **契约版本注释**里写明：n8n 侧 barongPupload001 需把
     `shipping.shipping_class` 写到 Woo 产品的 shipping_class（用户自己改
     n8n，不在本任务内）。

---

## 7. 模块注册 / 权限 / 组织门 / 依赖绑定

1. `backend/app/core/modules.py`：在 `f.enrichment` manifest 之后插入
   `w.site_ops` manifest。照抄 f.enrichment 的结构，改这些值：
   - module_key `w.site_ops`；display_name `W-A 网站运营中枢`；
   - description（英文）自拟但需提到 shipping rule engine / deterministic / fail-closed；
   - route_namespace `/w-a`；api_namespace `/w`；
   - navigation: group "Registry", label `W-A 网站运营中枢`, icon `Boxes`, order 15；
   - required_permissions `("w.site_ops.read",)`；
   - permission_manifest 两条：`w.site_ops.read`（read/low）、
     `w.site_ops.manage`（manage/medium, operation_log_required=True）；
   - external_dependencies：**留空 ()**（不声明 woocommerce/n8n——写 Woo 的是
     P 的 n8n 通道，W 只管数据；声明了就得动依赖绑定测试，不要给自己找事）；
   - data_boundary reads/writes 写 w_shipping_classes / w_shipping_rules /
     k_product_knowledge_products。
2. `backend/app/services/module_registry.py`：`INTL_TRADE_ONLY_MODULE_KEYS`
   的 frozenset 里加 `"w.site_ops"`（组织门，死命令 2）。
3. `backend/app/main.py`：import + `app.include_router(w_siteops_router, prefix=APPLICATION_API_PREFIX)`（照 f_enrichment_router 两行）。
4. 鉴权依赖：照 P 的 `_require_p_permission`；manage 隐含 read。

---

## 8. 前端（逐字执行，禁止发挥）

### 8.0 总则

- 只允许新建以下文件 + §9 列出的 6 处共享文件小改，**别的前端文件一律不碰**，
  尤其不碰 `globals.css`。
- 颜色只允许用本文 CSS 里出现的值（青 `rgb(57 212 255)` 系、绿
  `rgb(61 220 151)` 系、橙 `rgb(255 184 76)` 系、红 `rgb(255 107 107)` 系、
  文字 `#eafaff / #d9f3ff / #cfe8f5 / rgb(157 199 219)`）。
- 按钮只用全局类 `primary-button` / `secondary-button`；图标只用
  lucide-react，尺寸 14-16。**禁止**：emoji、alert()、inline style、新字体、
  渐变按钮、圆角>16px、任何"卡片阴影发光"之外的新效果。
- 所有界面文案用本文给定的中文原文，一个字都不要改。

### 8.1 `frontend/src/app/(console)/w-a/layout.tsx`（整文件，原样使用）

```tsx
export default function WCommandLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // 复用 .ra-command 驾驶舱皮肤（globals.css 同一视觉体系）
  return (
    <div className="ra-command">
      <div className="ra-command-space" aria-hidden>
        <div className="ra-command-nebula" />
        <div className="ra-command-phoenix" />
      </div>
      <div className="ra-command-content">{children}</div>
    </div>
  );
}
```

### 8.2 `frontend/src/app/(console)/w-a/page.tsx`（整文件，原样使用）

```tsx
import type { Metadata } from "next";

import { ShippingDeck } from "@/modules/w/siteops/ShippingDeck";

export const metadata: Metadata = {
  title: "W-A 网站运营中枢",
};
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default function WSiteOpsPage() {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <span className="section-index">W</span>
        <div>
          <h1>W-A 网站运营中枢</h1>
          <p>
            运费中枢：确定性规则表给独立站产品分配 Woo
            运费模板——重量段位查表、带电与美国仓单独走线、缺数据不放行。
            每个产品都能看到它为什么在这个模板里。
          </p>
        </div>
      </section>
      <ShippingDeck />
    </div>
  );
}
```

### 8.3 `frontend/src/modules/w/siteops/api.ts`

结构照抄 `frontend/src/modules/f/enrichment/api.ts`（同样的
`API_PROXY_BASE`/`buildHeaders`/`readJson` 三件套，逐字复制那三个函数），
然后按 §5 的端点补 fetch 函数与 TS 类型。类型字段名与后端 schema 完全一致。

### 8.4 `frontend/src/modules/w/siteops/ShippingDeck.tsx` —— 布局规格

`"use client"` 组件，结构自上而下：

1. **统计行**（4 张卡，类名/结构逐字复制 F 的 `.statRow/.statCard` 用法）：
   - `独立站产品`（summary.total_dtc）
   - `已分配`（summary.assigned，data-tone="success"）
   - `待人工复核`（summary.review_needed，data-tone="flight"）
   - `已上架缺运费`（summary.exported_missing，data-tone="failed"）
2. **错误/通知条**：照 F 的 `.state`（role="alert"）与 `.notice` 用法。
3. **横向 tab**（类名结构逐字复制 `frontend/src/modules/p/upload/UploadDeck.tsx`
   的 `.tabs/.tab/.tabOn/.tabCount` 用法），四个 tab：
   `产品台账` / `分配规则` / `运费模板` / `试算器`。
4. **产品台账 tab**：
   - 头部左侧标题 `产品台账 · 独立站产品的运费归属与溯源`，右侧两个按钮：
     `重算全部`（primary，POST assign-all 后刷新 + notice
     `已重算：{assigned} 个分配成功，{review_needed} 个待复核，{unresolved} 个缺数据未分配。`）、
     `刷新`（secondary）。
   - 筛选行：四个 secondary 按钮当 filter 切换
     （`全部/未分配/待复核/已上架缺运费`），当前项加 `.tabOn`。
   - 表格列：`产品`（名称+SKU 两行，复制 F/P 的 .productCell）| `计费重`
     （used_kg，两位小数 + " kg"，缺失显示 `—` 且红字 `缺数据`）| `带电`
     （checkbox，改了就 PATCH）| `美国仓`（checkbox 同上）| `运费模板`
     （`<select>` 下拉，选项=active 模板 name，值=slug，含空选项 `未分配`；
     变更即 PATCH，人工选择）| `溯源`（命中规则的 rule_type 中文：
     `美国仓线/带电线/重量段位/人工指定`，带 title=完整 assignment json；
     review_needed 时前面加橙色 `.statusBadge` 写 `待复核`，点击 =
     PATCH clear_review）| `操作`（secondary 小按钮 `重算`，单产品 assign）。
5. **分配规则 tab**：
   - 说明行（`.mutedLine`）：
     `评估顺序：美国仓线 → 带电线 → 重量段位（priority 小的先）。计费重 = 实重与体积重取大（体积重 = 长×宽×高cm ÷ 6000）。缺重量数据的产品不会被分配，只会进待复核。`
   - 表格列：`优先级` | `类型`（下拉：美国仓线/带电线/重量段位）| `重量下限 kg`
     | `重量上限 kg` | `运费模板`（下拉=模板列表）| `启用`（checkbox）|
     `备注` | `操作`（保存/删除，secondary）。
   - 底部 `新增规则` primary 按钮插入空行编辑。
6. **运费模板 tab**：
   - 说明行：`slug 必须与 WooCommerce 后台的运费类别（shipping class）slug 完全一致——这是唯一的对齐点，填错产品会挂错模板。`
   - 表格列：`slug`（新建时可填，已存不可改）| `名称` | `线路`
     （下拉：中国直发/美国仓）| `启用` | `备注` | `操作`（保存）。
   - 底部 `新增模板` primary 按钮。
7. **试算器 tab**：
   - 一行输入：`实重 kg`（number）、`长/宽/高 cm`（三个 number）、
     `带电`（checkbox）、`美国仓现货`（checkbox）、`试算` primary 按钮。
   - 结果卡（复用 .statCard 样式）：命中显示
     `→ {模板名}（{rule_type 中文}，计费重 {used_kg}kg）`；review_needed 时
     橙字附 review_reason；未命中显示红字 `不分配：{review_reason}`。

轮询：不需要（无长任务）；数据在动作后手动刷新。加载/空态照 F 的
`.state`（LoaderCircle + `正在加载…`）与 `.emptyHint` 模式。

### 8.5 `frontend/src/modules/w/siteops/ShippingDeck.module.css`

**从 `frontend/src/modules/f/enrichment/EnrichmentDeck.module.css` 逐字复制**
这些类（含媒体查询与 data-tone/data-status 变体，一个属性都不要改）：
`.deck .statRow .statCard .statLabel .statValue .panel .panelHead .panelTitle
.state .emptyHint .notice .table .tableScroll .timeCell .errorCell
.statusBadge .mutedLine`；
再从 `frontend/src/modules/p/upload/UploadDeck.module.css` 逐字复制
`.tabs .tab .tabOn .tabCount .productCell`。
新增的类只允许做布局（flex/grid/gap/padding），颜色必须取自 §8.0 的清单。
表单控件（input/select）样式逐字复制 F 的 `.searchInput`（改名 `.formInput`
即可），select 同款边框底色。

---

## 9. 共享文件的 6 处小改（精确位置，最小 diff）

1. `frontend/src/app/api/backend/[...path]/route.ts`：
   - 照 `isAllowedFPath` 新写 `isAllowedWPath(method, path)`，按 §5 的表
     枚举（`path[0] === "w"`，`shipping/classes|rules|simulate|assign|assign-all|board|products` 各自的方法与 UUID 段校验，照 F 的写法）；
   - 在 `getBackendApiPath` 的链里 `isAllowedFPath(...) ||` 后面加一行
     `isAllowedWPath(method, path) ||`。
2. `frontend/src/lib/navigation.ts`：业务处理组，F 的记录后面插：
   ```ts
   {
     category: "business",
     denied_behavior: "show_locked",
     href: "/w-a",
     icon: Boxes,
     label: "W-A 网站运营中枢",
     module_key: "w.site_ops",
     required_permission: "w.site_ops.read",
     route_namespace: "/w-a",
     status: "active",
   },
   ```
   （`Boxes` 已在该文件 import 列表里。）
3. `frontend/src/lib/frontend-capability-state.ts` 四处 map：
   `PRODUCT_NAVIGATION_GROUPS` 加 `["w.site_ops", "业务处理"]`；
   `PRODUCT_NAVIGATION_LABELS` 加 `["w.site_ops", "W-A 网站运营中枢"]`；
   `PRODUCT_NAVIGATION_ORDER` 加 `["w.site_ops", 15]`；
   `ACTION_SCOPED_EXECUTION_GATE_MODULE_KEYS` 加 `W_SITE_OPS_MODULE_KEY`
   （常量定义照 F 的 `F_ENRICHMENT_MODULE_KEY` 加在旁边）。
4. `tests/frontend/module-isolation.test.mjs` 两处：
   nav 期望数组里 `"f.enrichment",` 后面加 `"w.site_ops",`；
   registryItems fixture 里照 f.enrichment 的 manifest 块加一个 w.site_ops
   块（route_namespace "/w-a"，required_permissions ["w.site_ops.read"]，
   external_dependencies 留空数组）。
5. `backend/app/core/modules.py` / `module_registry.py` / `main.py`：见 §7。
6. **不碰** `dependency_bindings.py` 与其测试（external_dependencies 留空的
   原因就在这）。

---

## 10. 测试要求

后端 `tests/backend/test_w_shipping_hub.py`（`pytestmark = pytest.mark.integration`，
fixture 结构照抄 `tests/backend/test_f_series_enrichment.py` 的 f_env——
seed 用 ORM/SQL 建模板与规则，teardown 清理 w_* 表和 K 加的列数据）：

1. 模板/规则 CRUD 走通（含 PATCH slug 不可改返回 422）。
2. 引擎用例（直接调 engine 或走 simulate 端点）：
   - 0.05kg → 命中小件段；5kg → 命中重货段（**两个产品绝不同段**——这是
     本任务的初心用例，用规则 seed：0–0.5 / 0.5–2 / 2–∞ 三段验证）；
   - 体积重大于实重时按体积重（30×40×50cm、实重 1kg → 体积重 10kg 段）；
   - 带电 + 2kg → battery_override 赢过 weight_band；
   - us_stock + 带电 → us_stock 赢（priority 在前）；
   - 无重量无 override → 不分配 + review_needed + 原因文案完全匹配；
   - 边界 ±10%（段位切 2kg，产品 1.95kg）→ 分配 + review_needed；
   - 人工指定后重算不覆盖，force=true 覆盖。
3. P 硬门：dtc 产品无 shipping_class → gate_blockers 含
   `"运费模板未分配（去 W-A 运费中枢处理）"`；赋值后 blocker 消失；
   channel=amazon 不受影响。
4. 契约：上架包 JSON 里出现 `shipping.shipping_class`。
5. board 的 exported_missing 过滤正确（造一条 p_upload_jobs success 记录）。
6. 权限：viewer 用户全端点 403（照 F 的 test_f_endpoints_require_permission）。

前端：`tests/frontend/w-shipping-proxy.test.mjs` 照
`f-enrichment-proxy.test.mjs` 写 allow/deny 两组断言。

**全部跑绿才算完**：
```bash
bash scripts/run_backend_tests.sh unit          # 447+ 全绿
bash scripts/run_backend_tests.sh integration   # 55+ 全绿
cd frontend && npm run test && npm run typecheck  # 全绿
```

---

## 11. 验收清单（Claude 会逐条对照）

- [ ] 三条死命令无违反
- [ ] migration 单头、EXPECTED_ALEMBIC_HEAD + manifest 同步、干净库 upgrade head 通过
- [ ] 引擎 8 个用例语义与 §3 完全一致（尤其 fail-closed 与 ±10%）
- [ ] P 硬门文案逐字一致；amazon 渠道不受影响
- [ ] 契约新字段 + extra="forbid" 不破坏现有 n8n 取数（旧字段零变动）
- [ ] /w-a 页面视觉与 F/P 驾驶舱不可区分（同卡片/同表格/同徽章/同按钮）
- [ ] 全部 UI 文案与本文逐字一致
- [ ] 共享文件 diff ≤ 本文 §9 列出的范围
- [ ] 三通道全绿；**未部署**

## 12. 提交规范

- 只提交本任务文件；一个 commit，message：
  `feat(w): shipping hub with deterministic class assignment (W-A cut 1)`
  + body 概述 + 你的署名规范。
- 提交前 `git status` 确认没把并行施工区（f_series/c19）的文件卷进来。
