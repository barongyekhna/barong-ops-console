# PDP 大改 · Codex 规格(管线代码侧)

> 背景:一个 K→P 全链路产出的产品页(Solar Garden Light,product_id `d1ffac94-4946-41c0-b869-020721b0a00e`,Woo #3778)经严格审计,判定为低质量页(EEAT 不及格、无真实规格、无信任元素、图片无信息、SKU 误用 ASIN)。根因:**从一份缺数据的描述生成,没有真实 1688 规格喂入**。本文档是 Codex 负责的**管线代码**部分;作图指令 skill 与描述 HTML 模板由 Claude 另行改(两边有契约耦合,见各节"与 Claude 侧的契约")。

## 审计实锤(复现用)
- `Product` JSON-LD:`sku="B0BYTEST01"`(=亚马逊 ASIN,严重误用)、`additionalProperty: 0`(零结构化规格)、`aggregateRating/review: false`。
- meta description 由描述 HTML 剥标签生成,**句子间缺空格**("GlowAdd""upkeep.This")且被截断。
- K 生成的 `marketing_copy_json.seo.{title,meta_description}` 质量 OK,但**线上根本没写进 SEO 插件**(管线断点)。
- `marketing_copy_json.missing_inputs` 自带数组,列的正是:尺寸重量/充电续航/流明/电池规格/IP 等级——**管线知道缺,只是没源数据**。
- 描述图/场景图为"产品平面图层贴 AI 背景",穿帮;灯的自发光没有溢到环境。

---

## 任务 1 —— 1688 真实规格接入 K(第一因,最高优先)
**目标**:F 系列找货(`backend/app/modules/f_series/enrichment/`)本就抓 1688 产品;把 1688 的**结构化规格**落进 K 产品,供文案 + 图上标注 + schema 使用。
- 定义一组标准规格字段(建议存 K 产品的 `attributes`/新 JSON 字段 `structured_specs_json`):lumens、color_temperature_k、battery_type、battery_capacity_mah、charge_time_h、runtime_h、ip_rating、dimensions(l/w/h+unit)、weight、material、mount_type(spike/base…)、certifications 等(做成可扩展 key-set,不同品类可加字段)。
- **F→K 落库**:F 找货/富化时把能从 1688 详情/属性抓到的规格解析进上述字段(抓不到的留空,别编)。若已有 F→K 通道复用;没有则新增(参考 `r_to_k_transfer.py` 的搬运范式 + scope 处理)。
- **喂给文案**:K marketing_copy / selling_points 生成时,把 `structured_specs_json` 作为输入喂给 AI(治 `missing_inputs`),并要求文案**引用真实数值**(2700K、mAh、IP65…),缺失字段不许臆造。
- **与 Claude 侧契约**:Claude 的作图指令 skill 会要求"信息图/尺寸图的文字来自 `structured_specs_json`"。字段名定稿后同步给 Claude。

## 任务 2 —— SKU 发号器(铁律)
**铁律**:`SKU = 叶子类目简写 + "-" + 数字编号`,编号=该叶子类目内**上架顺序**自增。例 In-Ground Lights → `IGL-001`、`IGL-002`。**永不使用 ASIN**。
- 叶子类目简写:从叶子类目名派生(大写首字母缩写,如 "In-Ground Lights"→IGL;"Cold Therapy Machine"→CTM),冲突时加约定映射表兜底。
- 编号:该叶子类目内自增(建一张 `sku_sequence(leaf_key, next_seq)` 计数表 or 查现有 max+1),并发安全。
- 替换点:`backend/app/modules/p_series/upload/assemble.py` 及任何 `product.sku = ASIN` 处;SKU 在产品首次进入 K/首次上架时**分配一次并固化**(重复上架幂等,不重发号)。
- 迁移:新计数表要 Alembic 迁移(**建迁移前先 ls versions 找 head 从它分叉,单 head**;迁移不自动跑)。

## 任务 3 —— SEO 字段真正应用到站点
**目标**:把 K 的 `seo.title` / `seo.meta_description` 写进 WooCommerce 产品的 SEO 插件字段,并修 meta 断词 bug。
- 站点 SEO 插件是 Yoast/等;产品的 SEO title/meta 存在产品 meta(如 `_yoast_wpseo_title` / `_yoast_wpseo_metadesc`)。上架包 `product.seo.{title,description}` 已有;n8n「转 Woo 格式」节点要把它们写进 `meta_data`(对应 Yoast meta key),n8n 侧改动同 P 上架工作流(`backend/app/modules/p_series/n8n/p_upload_workflow.json`,改后 Claude/运维会重导线上 n8n)。
- **meta 断词 bug**:若 meta 由描述 HTML 自动生成,则改为**优先用 `seo.meta_description`**(K 已生成规范文案);彻底不靠"剥标签"兜底。

## 任务 4 —— 图上信息叠加(info-overlay 合成)
**目标**:信息图/尺寸图/规格图 = AI 生成"干净基底图(留标注空间)" + **管线程序化叠加文字/尺寸线**(AI 直接写字必乱码)。
- 在 K 渲染链(`backend/app/modules/k_series/product_knowledge/image_render_jobs.py`)后增一个"叠字合成"步骤:对 asset_role ∈ {feature_callout, dimension, spec} 的图,按作图指令给的 overlay 规格(标注文本、锚点坐标/引线、尺寸线端点),用服务器端图像库(Pillow/skia)把文字+引线+尺寸线合成到基底图上,产出成品。
- 文本内容来自任务 1 的 `structured_specs_json`(真数值);字体/配色遵循家规(暖白底、深色字 #1b1a18、极简)。
- **与 Claude 侧契约**:Claude 的作图指令 skill 会为这几类图输出结构化 `overlay` 段(role、每条标注的 text 来源字段、锚点、引线方向);本任务消费该段。字段 schema 定稿后与 Claude 对齐(建议放进上架包/媒体 metadata)。

## 任务 5 —— Product schema 补规格 + 评分
- Product JSON-LD 增 `additionalProperty`(从 `structured_specs_json` 映射:PropertyValue name/value/unitText),让谷歌拿到结构化规格(EEAT/富结果)。
- 有真实评价时输出 `aggregateRating`/`review`(**评价不许造假**;无则不输出该字段,别硬造)。
- 规格也建议同时写成 WooCommerce 产品属性(`attributes`),站点侧/SEO 插件可复用。

## 硬约束(全任务通用)
- **P 上架保持 fail-safe**:任一环节(规格缺、类目解析、叠字)失败绝不阻断上架,降级继续 + 记日志。
- **别造假**:抓不到的规格留空,不编数值;无真实评价不造评分。
- 品牌硬门不动(json_ld 品牌永远只有 Barong Yekhna)。
- 测试:各任务加回归测试;跑 `bash scripts/run_backend_tests.sh unit`。风格/迁移照仓库惯例。
- **注意本仓库正被 Claude 同时改** `product-image-art-direction/SKILL.md` 与 `p_series/upload/description_html.py`——尽量避开这两个文件,若必须动先协调,防止双头/冲突。

## 交付
分支/PR + 测试全绿 + 每个任务一句根因与修法说明 + 任务 1/4 的字段/overlay schema 定稿(供 Claude 对齐)。
