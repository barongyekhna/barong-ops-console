# PDP 第八轮 · Codex 规格(标题层收口:数字一致性门 + 可读性重写)

> 背景:外部审稿(DeepSeek)对 CCD-006(#3864)抓出 2 条真问题,内部复核确认。其余建议(编造对比数据/假评分/FAQ塞规格数字/价格结构改法)经评审**拒绝**——违反证据铁律或技术上不成立,勿采纳。**七个对比产品(#3803…#3864)不动**;验证走新产品。无远程仓库不 push。SKILL.md 归 Claude。

## 1. 【P0】标题↔规格 数字声明一致性门
**实锤**:CCD-006 H1 写 "for **1-2 People**"(来自 1688 供应商标题"1-2人"),规格表/卖点写 "**2-3 people**"(specs.capacity_people)——同页自相矛盾,买家信任即碎。根因:证据门覆盖了卖点与 H1 的"词",**没覆盖 H1 里的数字型受众/数量声明与 structured_specs 的一致性**。
**修**(evidence_guard 扩展,与既有标题一致性门同处):
- 从标题/H1 提取**数字型声明**:人数(`for N people` / `N-person` / `N-N people`)、件数(`N-piece`)、容量(`N qt/L`)等模式。
- 与 structured_specs 对应字段(capacity_people / piece_count / capacity_*)比对:**不一致 → 以规格为准改写标题中的该声明**(规格是证据源);规格缺该字段 → 标题**删除该声明**(不许无据声明);无法安全改写 → 阻断报错给人工。
- 供应商标题(product_name_en)在 F→K 导入时也过同一门(supplier 的 "1-2人" 遇上 specs 的 2-3 people,导入即改/即删,别等到上架)。
- 回归:标题 1-2 vs specs 2-3 → 标题被改成 2-3;specs 无人数 → 标题人数声明被删;一致时不动。

## 2. 【P0】H1/标题由文案 AI 重写为"可读句",供应商名词串只作最后兜底
**实锤**:CCD-006 最终 H1/`<title>`/og:title/schema.name 全是剥了型号码的供应商标题原样——6 个名词连串("Cookware Mess Kit ... Pot Kettle Pan Tableware Set"),关键词沙拉,可读性差;且 `<title>` 没有走"短标题 | Barong Yekhna"模式(此前多轮是有的,退化路径把它冲掉了)。
**修**:
- **H1 生成规则**(marketing copy 的 seo.h1):主关键词前置 + 用 "–"/"," 断句 + ≤70 字符左右;例:`Portable Camping Cookware Mess Kit for 2-3 People – Non-stick Pot, Kettle & Pan Set`。prompt 明确"像一句自然英文,不是关键词罗列"。
- **`<title>`(seo.title)固定短模式**:`<主关键词短语> | Barong Yekhna`(≤60 字符),与 H1 解耦;退化兜底链修正:**兜底到 product_name_en 时也要重排成可读句 + 短 title 模式**,不许原样名词串直出。
- 两者都过 #1 的数字一致性门与既有证据门。
- 回归:AI 正常时短 title + 可读 H1;触发兜底时输出同样合规;`<title>`≤60 字符含品牌后缀。

## 3. 顺手项(便利就做)
- **meta_description 提示词微调**:鼓励自然覆盖 1-2 个高转化长尾(nested storage / backpacking 类),**硬上限 160 字符**(超长即截断,宁短勿超)。
- **OG 横版分享图**(P2,可留下一轮):og:image 生成/裁切一张 1200×630 横版(产品居中),Woo meta 或上架包新字段;没做也不阻塞。

## 明确不做(外部审稿建议被否,防止误采纳)
- ❌ "比不锈钢轻 40%" 之类**无出处对比数据**——违反证据铁律;可验证的算术锚点(如"比 1 升水还轻")才允许。
- ❌ 煎盘"能煎 2 个鸡蛋"——无数据编造;正确路径=把 pan 直径加入采集/手填字段(K 手动规格区已支持,不需代码)。
- ❌ FAQ 答案塞规格数字——违反既有 FAQ 校验器(答案禁复读规格)。
- ❌ `aggregateRating` 占位假评分——schema 造假,谷歌手动处罚重灾区;有真实评价时 Woo/Yoast 自动输出。
- ❌ 拆掉 priceSpecification 数组——会丢划线价信号;现结构(Yoast 数组 + Offer 顶层扁平价)是双保险,保持。

## 硬约束
- 七个对比产品不动;fail-safe/品牌硬门/别造假不变;测试 `bash scripts/run_backend_tests.sh unit` 全绿。
- 完成后 Claude 用新产品端到端验证(重点:人数矛盾被自动纠正、H1 成句、title 短模式回归)。

## 交付
本地提交 + 测试绿 + 每条一句根因/修法。
