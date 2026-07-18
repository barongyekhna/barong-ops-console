# PDP 第七轮 · Codex 规格(CCD-006 端到端抓出的三个真问题)

> 背景:round-6 修复(卖点 id 自动重排、描述配额 gallery6+desc3)已在 CCD-006 验证通过。但 CCD-006 品牌审查抓出 3 个更深的管线问题,均已实锤。**六个对比产品(#3803/#3812/#3821/#3837/#3854 + CCD-006 上架后)不许动**;验证走新产品。无远程仓库不 push。SKILL.md 归 Claude。

## 1. 【主刀】尺寸图叠字多标签互撞(overlay 几何缺陷)
**实锤**:CCD-006 dimension 图,视觉审查连续判违规:"The bottom dimension labels 'Length: 6.7 in' and 'Width: 6.7 in' overlap each other, making the infographic appear unfinished."。根因:俯视/正视炊具时 Length 与 Width 都是水平尺寸,overlay 合成器把两个标签都锚在**底边中央**→ 文字框重叠。round-2 只做了"单标签不出框",没做**多标签互斥排布**。这是确定性 bug,重渲染/rework 躲不掉(overlay 坐标不变)。
**修(info_overlay 合成器)**:
- 叠字放置加**碰撞检测 + 自动错位**:任意两个标签框重叠时,沿其引线方向平移/换边(Length 底边、Width 顶边或右侧、Height 左侧),保证三个尺寸标签**互不重叠且都不出画**。
- 标签锚点从"产品包围盒的边中点"改为**三条边各分一个方位**(常见:宽=上/下二选一、长=另一条水平边、高=左或右竖边),从布局上先天避免同边堆叠。
- 回归:构造 length/width/height 齐全的 dimension overlay,断言三标签的包围盒两两不相交、且都在画布内。

## 2. FAQ 研究把竞品牌名 + 文章标题带进来
**实锤**:
- CCD-006 首版 FAQ 出现问题 "Is **Odoland** a good brand?"(Odoland=竞品露营炊具牌)——被品牌门拦下,但说明 **faq_research 的 PAA/相关搜索里混入竞品牌名**。
- 重生成后 FAQ 又变成 "Best Camping Cookware of 2026, Tested & Reviewed" / "The Best Campfire Cooking Kits Put to the Test" —— 这是**搜索结果的文章标题**,不是问句,低质。
**修(faq_research）**:
- **竞品牌/他方品牌过滤**:问题文本命中"品牌名黑名单 or 明显的 X-brand 实体"时丢弃(至少:含 `is <Brand> ...` / `<Brand> vs` / `<Brand> review` 句式,以及一个可维护的竞品牌名单;更稳=对问题做轻量实体识别,含非本站品牌专有名词即丢)。绝不能让竞品牌进入买家可见 FAQ/schema。
- **问句形态门**:只接**疑问句**(以 what/how/can/is/are/do/does/which/why/when + `?` 结尾 等特征),拒绝文章标题/榜单式短语("Best ... Tested & Reviewed"、"... Put to the Test (2026)")。来源优先级:peopleAlsoAsk > 论坛/差评问句 > organic;organic 只在明显问句时采用。
- 回归:含 Odoland 的候选被丢;"Best ... Reviewed" 文章标题被丢;正常 PAA 问句保留。

## 3. 供应商型号码在 F→K 导入时未清洗(反复踩)
**实锤**:DS-101(本轮)、DS-308(round-4)都从 1688 标题带进 `product_name_en` → 一路流到 json_ld.name,每次都靠品牌门兜底 + 人工 SQL 清洗。应在**源头**洗掉。
**修**:F→K 导入(`import_candidate_to_k` 生成 product_name_en / 及 DeepSeek 命名后)对名称/主词做一次**型号码剥离**:正则 `\b[A-Z]{2,}[- ]?\d{2,}\b`(如 DS-101/DS308)之类的孤立供应商编码去除并 trim 多余空格;保留正常含数字词(如 "1.5L"、"7-Piece"、"2-3")。注意别误伤规格数值——只清"字母缩写+数字"的型号形态、且不在 structured_specs 语境里。
- 回归:标题 "DS-101 Portable Cookware ..." 导入后 product_name_en 无 DS-101;"7-Piece 1.5L Set" 不被误伤。

## 附:审查快照时效性(小噪点,便利就查)
现象:改数据后经 API 触发 brand-audit,UI/DB 的 `brand_audit_json` 有一小段时间仍是旧快照(job 异步 + 可能去重),需靠 `audited_at` 变化确认新结果。若 approve/派单前的门禁读的是可能过期的 `brand_audit_json`,建议:派单门校验时若 `audited_at` 早于 marketing_copy/图片的最后更新时间,视为"需重新审查"而非直接放行/拦截,避免误判。

## 硬约束
- 六个对比产品不动;fail-safe/品牌硬门/别造假不变;测试 `bash scripts/run_backend_tests.sh unit` 全绿。
- 完成后 Claude 用新产品端到端验证(重点:dimension 三标签不撞、FAQ 无竞品牌/无文章标题、导入即无型号码)。

## 交付
本地提交 + 测试绿 + 每条一句根因/修法。
