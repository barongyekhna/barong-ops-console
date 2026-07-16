# Codex 任务单：运费链收尾 —— K 产品详情运费面板 + W 权限注册表补登

> 任务代号：SHIP-K-PANEL
> 委托方：台里（Claude）· 拍板人：Barong Yekhna
> 日期：2026-07-15

---

## 0. 开工前必读（违反任何一条 = 返工）

1. **先跑 `git status`**。这棵树上有多个并行工作头。你只准动本单「允许触碰的文件」清单里的文件。
2. **绝对禁碰**（其他工作头的活）：
   - `backend/app/modules/f_series/**`、`frontend/src/modules/f/**`（F 系列，台里的）
   - `r_system_v2/ra/quota_ledger.py`、`r_system_v2/ra/channel_signals.py`、`r_system_v2/ra/google_keyword_planner.py`、`docker-compose.production.yml`（Google Ads 接入头正在动）
   - `frontend/src/app/globals.css`、`frontend/src/lib/capability-sidebar-engine.tsx`（本任务无新模块，侧边栏/全局样式零改动）
3. **本任务没有数据库迁移**。不准创建任何 alembic revision，不准动 `scripts/staging_stabilization.py` 的 `EXPECTED_ALEMBIC_HEAD`，不准动 `migration_manifest.json`。当前 head = `20260714_04_f_market_refs`，保持原样。
4. **n8n 不归你**：barongPupload001 的 `shipping.shipping_class` → Woo 映射由台里完成（`backend/app/modules/p_series/contract/upload_package.py:29-30` 注释里写明 intentionally external）。你不碰任何 n8n 工作流。
5. **部署不归你**：完成后 commit 即止，台里负责发布与生产验证。
6. 工作目录：所有命令一律从 **repo root**（`/opt/barong-ops-console`）执行。测试脚本会自建隔离 Postgres，工作目录漂移会让 alembic 连错库（踩过）。

---

## 1. 前端美学铁律（最高优先级约束）

**你没有任何视觉设计决策权。** 具体含义：

- **禁止**新增任何 CSS 类、颜色值、动画、间距值、字号、圆角、阴影。
- **禁止**修改 `ProductKnowledge.module.css` 或任何 `.css` 文件（一行都不加）。
- 新区块**只准复用** `ProductDetail.tsx` 中现有区块已经在用的 className 组合——先通读该文件，找到现有「区块标题 + 字段行 + 徽章 + 按钮」的写法，逐一照抄结构。按钮一律用现有的 `"primary-button"` / `"secondary-button"` 全局类（K/F/W 各模块都在用），不发明新按钮。
- **所有用户可见文案必须逐字取自本文档第 4.3 节的文案表**。一个字都不许改、不许加、不许"润色"。
- 布局：新区块插在 §4.2 指定的位置，作为一个普通区块顺排。不准做折叠、不准做弹窗、不准做 tooltip 之外的任何交互花样。

---

## 2. 背景与现状盘点（这些都已存在，你不准重建）

运费链的后端在 W-S 轮已全部建成：

| 资产 | 位置 | 状态 |
|---|---|---|
| 运费类模型 `WShippingClass`（slug/name/zone_rates/woo_class_id/sync_status） | `backend/app/modules/w_series/shipping/models.py:50` | ✅ 生产在用 |
| 规则模型 `WShippingRule`（us_stock_override/battery_override/weight_band → slug） | 同文件 `:194` | ✅ |
| 确定性判定引擎（缺重量 fail-closed → 待复核） | `backend/app/modules/w_series/shipping/engine.py` | ✅ |
| K 产品运费列：`shipping_class` / `shipping_assignment_json` / `shipping_review_needed` | `backend/app/modules/k_series/product_knowledge/models.py:187-204` | ✅ 列已在库 |
| P 派单硬门：dtc 无 `shipping_class` → 拦「运费模板未分配（去 W-S 物流网络中枢处理）」 | `backend/app/modules/p_series/upload/assemble.py:46`（`gate_blockers`） | ✅ |
| 上架契约 `Shipping.shipping_class` 字段 | `backend/app/modules/p_series/contract/upload_package.py:52` | ✅ |
| W-S 前端运费看板（未分配/待复核 tab、一键重算、单品重判） | `frontend/src/modules/w/siteops/ShippingDeck.tsx` | ✅ |
| W 端点：classes CRUD、rules CRUD、simulate、assign/{id}、assign-all、board、products/{id} PATCH | `backend/app/modules/w_series/router.py:393-700` | ✅ |
| `/w/*` 前端代理白名单 | `frontend/src/app/api/backend/[...path]/route.ts`（isAllowedWPath） | ✅ 已放行 |

**缺口只有两个（= 本单的全部范围）**：

- **缺口 A**：K 产品详情页对运费零感知。用户在 K 里编辑产品时看不到运费判定结果，也无法就地手动指定运费类——必须跳去 W-S 看板。要在 K 详情页加一个只读展示 + 就地操作的运费区块。
- **缺口 B**：`w.site_ops.read` / `w.site_ops.manage` 两把权限钥匙不在中央权限注册表里（和 F 系列昨天修掉的是同一种缺口）。超级管理员的权限解析 = 注册表全部启用键，键不在注册表 = 国贸超管无权访问 W-S、也无法给成员分配。

---

## 3. Scope B（先做，小而独立）：W 权限注册表补登

**照抄 F 的先例**（commit `03d9266` 里 `feat(f): register f.enrichment.*`，看 `backend/app/core/permissions.py` 中 `f.enrichment.read/execute/review` 三条的写法）。

在 `backend/app/core/permissions.py` 的 `BASE_PERMISSION_REGISTRY_SEED` 中、`f.enrichment.review` 条目之后插入两条：

```python
{
    "permission_key": "w.site_ops.read",
    "module_key": "w.site_ops",
    "category": "business",
    "action": "read",
    "label": "Read W-series site ops",
    "description": "View shipping classes, rules, assignment board, orders, and tracking.",
    "risk_level": RISK_LEVEL_LOW,
    "menu_policy": MENU_POLICY_SHOW_LOCKED,
},
{
    "permission_key": "w.site_ops.manage",
    "module_key": "w.site_ops",
    "category": "business",
    "action": "manage",
    "label": "Manage W-series site ops",
    "description": (
        "Create and sync shipping classes, edit assignment rules, run "
        "shipping assignment, and manage order tracking."
    ),
    "risk_level": RISK_LEVEL_MEDIUM,
    "menu_policy": MENU_POLICY_SHOW_LOCKED,
},
```

- 与 `backend/app/core/modules.py:1269/1279` 的 W manifest 权限声明保持 key 一致（`w.site_ops.read` / `w.site_ops.manage`）。label/description 若 manifest 里有现成文本，以 manifest 为准照抄。
- 注册表同步（`upsert_permission_registry`）在生产由台里跑，你不用管。

---

## 4. Scope A（主体）：K 产品详情运费面板

### 4.1 后端：K 详情响应暴露运费字段

`backend/app/modules/k_series/product_knowledge/schemas.py` 的 `ProductKnowledgeRead`（`:271`）新增四个字段（全部 Optional，向后兼容）：

```python
shipping_class: str | None = None
shipping_review_needed: bool = False
shipping_assignment: dict[str, Any] | None = None
contains_battery: bool = False
```

在 K 详情序列化处（`router.py:2148` 的 GET `/products/{product_id}` 所走的序列化函数——先找到它现在怎么把 model 拍成 `ProductKnowledgeRead`，在同一处补字段）填充：

- `shipping_class` ← `product.shipping_class`
- `shipping_review_needed` ← `product.shipping_review_needed`
- `shipping_assignment` ← `product.shipping_assignment_json`（非 dict 时给 None）
- `contains_battery` ← `product.contains_battery`

**不改** list 端点（`/products`）的响应——列表不需要运费字段，别加。

### 4.2 前端：ProductDetail.tsx 新增「运费（独立站）」区块

**文件**：`frontend/src/modules/k/product-knowledge/ProductDetail.tsx`（区块位置：价格/库存类信息区块之后、文案/图片区块之前；先通读文件确认现有区块顺序，跟着已有的视觉节奏插入，不确定就放在基础信息区块的紧后面）。

**显示条件**：`product.channel === "dtc"` 时才渲染整个区块。非 dtc 产品完全不显示（一个字都不渲染）。

**数据**：
- 运费字段来自 §4.1 的详情响应。
- 运费类下拉选项：新增 API 函数拉 `GET /api/backend/w/shipping/classes`（返回结构见 `frontend/src/modules/w/siteops/api.ts:280` 的 `getShippingClasses`——**把该函数的 fetch 写法原样抄进** `frontend/src/modules/k/product-knowledge/api.ts`，包括 headers 构造模式；不要跨模块 import）。只列 `active === true` 的类，显示 `name`，值用 `slug`。

**三个操作**（新增到 k 的 `api.ts`，fetch 模式照抄 w 的对应函数）：

1. **手动指定运费类**：下拉选择后点「保存指定」→ `PATCH /api/backend/w/shipping/products/{productId}`，body `{ "shipping_class_slug": <slug>, "clear_review": true }`。选「（清除指定）」空选项时传 `{ "shipping_class_slug": null, "clear_review": false }`。
2. **重新判定**：点「按规则重判」→ `POST /api/backend/w/shipping/assign/{productId}`，body `{ "force": true }`。
3. **含电池开关**：复选框，变更即 `PATCH /api/backend/w/shipping/products/{productId}`，body `{ "contains_battery": <bool> }`。

三个操作成功后都**重新拉取产品详情**刷新区块（复用该页现有的详情刷新函数）。失败时把错误文本显示在区块内（复用该页现有的错误提示写法，不发明新样式）。

**区块结构**（自上而下，全部复用现有 className）：

1. 区块标题行：`运费（独立站）`
2. 状态行（只读）：
   - 已分配：显示运费类 name（用 slug 从 classes 列表反查 name；查不到显示 slug 本身）+ 来源说明（`shipping_assignment.rule_type` 存在 → 显示「规则判定」；否则显示「手动指定」）
   - 未分配：显示「未分配——P 系列上架前必须解决」
   - `shipping_review_needed === true`：追加显示「待复核：」+ `shipping_assignment.review_reason`（无 reason 显示「缺少判定依据」）
3. 判定痕迹行（只读，仅 `shipping_assignment` 存在时）：显示「判定重量 {used_kg} kg」（`used_kg` 为空则整行不显示）
4. 操作行：运费类下拉 + 「保存指定」按钮（`secondary-button`）+「按规则重判」按钮（`secondary-button`）
5. 含电池复选框 + 标签「含电池（命中电池规则）」

### 4.3 文案表（逐字使用，不许改）

| 位置 | 文案 |
|---|---|
| 区块标题 | `运费（独立站）` |
| 未分配状态 | `未分配——P 系列上架前必须解决` |
| 规则判定来源 | `规则判定` |
| 手动指定来源 | `手动指定` |
| 待复核前缀 | `待复核：` |
| 待复核缺省原因 | `缺少判定依据` |
| 判定重量行 | `判定重量 {used_kg} kg` |
| 下拉空选项 | `（清除指定）` |
| 下拉未选提示项（初始） | `选择运费类…` |
| 保存按钮 | `保存指定` |
| 重判按钮 | `按规则重判` |
| 电池复选框标签 | `含电池（命中电池规则）` |
| 保存成功提示（如该页有成功提示模式则用，没有则不加） | `运费指定已保存` |
| 重判成功提示（同上） | `已按规则重新判定` |
| 通用失败前缀（拼接后端 detail） | `运费操作失败：` |

### 4.4 类型

`frontend/src/modules/k/product-knowledge/types.ts` 的产品详情类型加：

```ts
shipping_class?: string | null;
shipping_review_needed?: boolean;
shipping_assignment?: {
  rule_type?: string | null;
  used_kg?: number | null;
  review_reason?: string | null;
} | null;
contains_battery?: boolean;
```

新增 `WShippingClassOption` 类型（id/slug/name/active），字段跟 `/w/shipping/classes` 响应对齐（看 w 的 `api.ts` 里现有 `ShippingClass` 类型抄字段）。

### 4.5 权限注意

- K 详情页本身由 k.* 权限门守着，不用你动。
- 三个操作端点要求 `w.site_ops.manage`（owner/super_admin 天然有；Scope B 落地后国贸超管也有）。普通成员若无 w 权限，后端会回 403——把 403 的 detail 用通用失败前缀显示出来即可，**不要**做前端权限预判/按钮隐藏逻辑。

---

## 5. 测试要求

全部从 repo root 执行：

```bash
bash scripts/run_backend_tests.sh unit          # 现有 478 全绿基线
bash scripts/run_backend_tests.sh integration   # 现有 80 全绿基线（自建 docker Postgres）
cd frontend && npx tsc --noEmit && npm run test # 现有 191 全绿基线
```

新增断言（放进现有测试文件，不新建文件）：

1. `tests/backend/test_k_product_knowledge*.py`（找到现有 K 详情测试）：详情响应含四个新字段；给测试产品设 `shipping_class='cn-standard'`、`shipping_review_needed=True`、`shipping_assignment_json={"rule_type":"weight_band","used_kg":1.2}` 后断言原样返回。
2. 权限注册表测试（找到现有断言注册表种子的测试，如有 key 集合断言需同步加 `w.site_ops.read/manage`；`tests/backend/test_pre20_p_staging_stabilization.py` 若因种子变化失败，按其报错提示处理——但**不许**动 migration manifest 相关部分）。
3. 前端如有 K 详情组件测试则补一条：dtc 产品渲染 `运费（独立站）` 标题、非 dtc 不渲染。没有现成组件测试则不新建。

---

## 6. 验收清单（完成后逐项自查并在回报里贴结果）

- [ ] `git status` 显示只动了：`backend/app/core/permissions.py`、`backend/app/modules/k_series/product_knowledge/schemas.py`、K 详情序列化所在文件、`frontend/src/modules/k/product-knowledge/{ProductDetail.tsx,api.ts,types.ts}`、相关测试文件
- [ ] 没有任何 `.css` 文件变更、没有新 CSS 类、没有新迁移文件
- [ ] 三条测试通道全绿（贴数字）
- [ ] 文案与本文档 §4.3 完全一致（自查一遍）
- [ ] dtc 产品详情渲染运费区块；非 dtc 完全不渲染
- [ ] 手动指定 → 详情刷新后 `shipping_class` 生效；`force` 重判调用成功
- [ ] commit 信息格式：`feat(w+k): K product shipping panel + w.site_ops registry keys`，正文写清两个 scope；**只 commit 你自己动的文件**

---

## 7. 回报格式

完成后回报：动了哪些文件、三通道测试数字、验收清单勾选情况、以及任何你发现但没动的问题（发现问题只报告，不越界修）。
