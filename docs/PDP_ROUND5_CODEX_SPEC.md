# PDP 第五轮 · Codex 规格(第四轮端到端实战抓出的门禁缺陷修复)

> 背景:第四轮用 CCD-004(Woo #3837)真跑全链,四大目标(FAQ 同步/gallery≥6/宽高比自动化/价格 schema 代码侧)全部验证;过程中门禁体系抓真问题的同时暴露了 4 个自身缺陷,全部已实锤定位。**#3803/#3812/#3821/#3837 四个对比产品都不许动**;验证走新产品(SKU 自动 CCD-005)。无远程仓库不 push。
> 注:priceSpecification 修复代码已随 round-4 完成,只是要用户重传 WP 插件,不在本轮范围。

## 1. 【最高优先】标题一致性门剪秃无保底(产品名变 "Product" 事故)
**实锤**:DS-308 清洗后重生成文案,`enforce_title_evidence_consistency` 把 H1 剪到只剩 **"Product"**、`seo.title` 只剩 **"Barong Yekhna"**,照样放行 → 上架包 title 链取到秃值 → **Woo 产品名变成 "Product"** 直接见客(人工 SQL 补救才恢复)。
**根因**:一致性门逐词剪掉"证据语料里没有的词",没有下限保护;剪完剩不下可用标题时不回退、不报错。
**修**(evidence_guard.enforce_title_evidence_consistency):
- 剪完后做**退化检测**:剩余标题去掉品牌/停用词后 < 2 个实义词,或只剩 "Product"/品牌名 → 判退化。
- 退化时**回退**:用 `product_name_en`(先对它跑同一清洗,如去供应商型号码)作为 H1/title 兜底;仍退化则**报错阻断**让人工处理,绝不放行秃标题。
- 顺带查:为什么 "Camping/Portable/Cookware" 这类词不在证据语料?`title_evidence_corpus` 应包含类目名、product_name_en 分词、已审卖点全文——语料太窄是剪秃的帮凶,补齐。
- 回归测试:退化回退、彻底退化阻断、正常标题不动 三条。

## 2. overlay `source_field` 词汇表死锁(additional_specs 不可引用)
**实锤**:强制 feature_callout(round-4 gallery 铁律)后,AI 连续两次给 overlay 引用 `additional_specs.capacity_pot` 等字段 → `OVERLAY_SOURCE_FIELDS` 白名单拒 → **image brief 死循环失败**。临时解=Claude 在 SKILL.md 明示白名单让 AI 避开;但规格主要活在 additional_specs 的品类(炊具/餐具/家居多数如此)信息图只能标 material/weight/dimensions,表达力大损。
**修**:
- `OVERLAY_SOURCE_FIELDS` 扩支持 **`additional_specs.<key>`** 路径(key = 规格归一化时的稳定 key,如 capacity_pot)。
- `info_overlay._lookup_path` 支持从 additional_specs **列表**里按 key 取条目(现在点路径遍历只走 dict);显示标签用该条目的 `label_en`(缺 label_en 的条目不可引用——英文红线);数值解析走该条目 raw_value/value,与标准键同等的证据校验(non-empty raw_value + source_label)。
- 卖点证据解析器(`_selling_point_evidence_error`)**同一词汇表同步扩**——同样支持 `spec:additional_specs.<key>`(round-3 起 AI 生成就在引用这种路径,批准端一直拒,人工每轮都要兜)。
- SKILL.md 的白名单段由 Claude 在你完成后改回(允许 additional_specs.<key>);你别动 SKILL.md。
- 回归:additional_specs 路径的 overlay 渲染出真标注;卖点 approve 直接过。

## 3. 证据数字校验不认英制等值(6.7 in 被拒)
**实锤**:卖点 "packs down to 6.7 x 6.7 x 4.7 inches" 被拒 "Claim contains numbers absent from the current evidence: 4, 6, 7"——库存证据是公制(17×17×12 cm / 0.78kg),校验器数字集只含公制原值,**AI 按 round-3 规则正确使用英制**反而被判编造。
**修**:证据数字集构建时,对每个公制量**同时注入换算后的英制等值 token**(用 buyer_display 的换算函数,同一舍入规则:cm→in、mm→in、kg→lb、g→oz、L→qt),让英制表述通过;FAQ 答案的 spec-number 校验(`structured_spec_number_tokens`)同样扩,免得英制答案漏检/误判。
- 回归:英制卖点过、乱编数字仍拒。

## 4. FAQ 内容链路脆:质量门频繁全砍(两轮实测可见 FAQ 为空)
**实锤**:CCD-003 重生成、CCD-004 两次生成,产出的 page_faq 都没过质量门 → 可见 FAQ 整段消失(同步铁律保住了 schema 一致,但页面没有 FAQ 就丢了这块转化与 SEO)。
**根因**:generate_marketing_copy 的 FAQ 产出与 faq_research 的问题簇**联动不强**——AI 自拟问题/答案缺研究证据引用,质量门(正确地)砍掉。
**修**:
- FAQ 生成改为**从 faq_research_json 的问题簇里选题**(把簇列表连同来源直接喂给 AI,要求逐条 `evidence_refs` 引用簇 id),而不是让 AI 自由发挥再事后审。
- 质量门不过的条目,**用研究簇重写一次**再审;仍不过才丢弃。目标:有合格研究(quality_ready=true,如 CCD-003 有 19 源)时,可见 FAQ 至少产出 2-3 条。
- 回归:mock 研究簇下 FAQ 稳定产出且带引用;无研究时安全为空(现行为)。

## 硬约束
- 四个对比产品不动;fail-safe/品牌硬门/别造假 铁律不变。
- SKILL.md 归 Claude,勿改。测试 `bash scripts/run_backend_tests.sh unit` 全绿。
- 顺手项(便利就做):dispatch API 路由在门禁全清后仍 409(容器内直调正常——定位 route 层多裹的校验并修掉,这几轮一直靠容器内直调绕行)。

## 交付
本地提交 + 测试绿 + 每条一句根因/修法。完成后 Claude 用 CCD-005 跑第五轮端到端(重点:秃标题回退、additional_specs overlay 真标注上图、英制卖点直过、可见 FAQ 稳定产出)。
