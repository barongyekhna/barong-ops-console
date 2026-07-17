# PDP 第三轮打磨 · Codex 规格(CCD-002 审计后)

> 背景:第二轮(证据驱动)上架的 CCD-002(Woo #3812,`lightweight-camping-cookware-set`)审计 ~90/100,证据/场景/FAQ来源/schema 大方向已对。本轮修剩余 7 个用户实测问题 + 上轮遗留。**#3803 与 #3812 都不许动**(用户留作对比);下次验证走新产品(SKU 自动 CCD-003)。
> 实测取证已做,每条附实锤。无远程仓库,不 push。Claude 侧负责 `description_html.py` 的 H2 层级与家规 CSS,已改完,避开。

## 1. 【最高优先·红线】面向买家的文本绝不允许中文
**实锤**:Woo「额外信息」属性表出现 `主锅容量 / 件数 / 涂层 / 适用人数 / 手柄`(5 条中文标签)。
**根因**:`structured_specs_json.additional_specs[].label` = 1688 中文 `source_label` 原样透传成 Woo attribute name。标准键(material/weight/dimensions)有服务端英文映射所以没事,additional_specs 没有。
**修**:
- 规格归一化(structured_specs)时给 additional_specs 增加 **`label_en`**(AI 翻译一次、落库固化;翻译失败=该条不进任何买家可见面)。
- 上架包/n8n 属性、schema additionalProperty、规格表**只用英文标签**;无 `label_en` 的条目跳过(fail-safe,宁缺勿中文)。
- **出口硬门**:assemble 时对所有买家可见字符串(属性名/值、规格表、文案、FAQ、alt)做 CJK 字符检测,含中文=剔除该条并记日志(绝不上架中文)。value 也要查(如"叠嵌收纳+网袋"这类中文值同样要英文化)。

## 2. 【红线】买家可见的尺寸/重量一律美制
**实锤**:属性 `16 cm / 0.72 kg`,规格表 `160×160×110 mm / 720 g`,schema unitText=cm/kg,文案正文也是公制。
**修**:**库存公制不变**(structured_specs 存原始+公制),**展示层统一换算美制**:
- inch(1 位小数,如 6.3 × 6.3 × 4.3 in)、lb(0.72kg→1.6 lb;<1 lb 可用 oz)、容量 L→qt(1.4 L→1.5 qt,或 L/qt 双标)。
- 覆盖所有买家可见面:Woo 属性、规格表(specifications_html_table 生成处)、schema additionalProperty 的 value/unitText、**文案正文**(copy prompt 要求引用规格时用美制值——给 AI 的 specs 输入直接附带换算好的 imperial 字段,别让 AI 自己算)、图片叠字(上轮已定 imperial,保持)。
- 换算函数做成公共 util,单测覆盖(cm→in、kg→lb、g→oz、L→qt、mm 组合尺寸)。

## 3. H2 子标题(Claude 已修,Codex 不用做,只别改回去)
`description_html.py` 的 chunk 标题已从 `<h3>` 升为 `<h2>`(SEO 层级:页面 H1=产品名 → 描述内 H2 小节)。copy skill 若有"标题层级"提示,同步为 H2 语义(小节标题要含关键词)。

## 4. 套装必须列清单(七件套到底是哪七件)
**实锤**:全文 4 处提"7-piece"但从未列出内容物。
**修**:
- 规格模型增加 **`package_includes`**(内容物清单,list[str],英文);来源:1688 详情"包装清单"抓取 or 运营手填(K 手动录入区加此字段)。
- **声明-清单一致性门**:文案/卖点声称"N-piece"时,必须存在 `package_includes` 且条数=N,否则:有清单没数字→可以;有数字没清单→**降级为不提件数**(别让"7件套"成为无法验证的声明)。
- 有清单时,描述里输出"What's in the box"小节(H2 + 列表);上架包带给 n8n(可进 Woo 属性 `What's included`)。

## 5. 长尾关键词覆盖严重不足
**实锤**:K 工作流 SERP+双AI 已产出 final_keyword_set(高价值+长尾),但 `generate_marketing_copy` 的 ai_input **没有喂关键词集**——文案 AI 根本看不到爬来的词。
**修**:
- `generate_marketing_copy` 的 ai_input 增加 `final_keywords`(高价值+长尾,来自 execution.final_keyword_set_json/风险审查后的定稿集),prompt 要求:主词进 H1/首屏,**长尾词自然覆盖进 H2 小节标题与正文**(不许堆砌,语义自然)。
- **覆盖率回执**:文案生成后计算关键词覆盖率(final set 中出现在文案的比例),写进 marketing_copy_json.coverage,低于阈值(如 60%)记 warning 供人工看(不阻断)。

## 6. 幽灵组件:提了水壶但没有水壶数据
**实锤**:文案多处提 kettle(来自中文标题"茶壶套锅"),但规格无 kettle 任何数据。
**修**:**组件级证据规则**(evidence_guard 扩展):文案/卖点提到的**具体组件**(kettle/pot/pan/bowls…)必须在 `package_includes` 或规格键中存在;不存在→生成时不许提,或人工审查时标 unverified。与 #4 共用 package_includes。标题里的组件词同样过"标题↔证据一致性门"。

## 7. FAQ 答案不许复述规格数字
**实锤**:FAQ 答案里出现 "This 720 g set nests into a compact 16..."、"7-piece" 等——问题来源是真实的(Serper),但**答案**又绕回参数复读。
**修**:FAQ 答案生成规则+校验器:
- 答案回答问题本身(建议/方法/取舍),**禁止出现规格数值**(数字白名单:年份/温度建议等非本品规格的通用数字可留;实现上可校验"答案中的数字不得命中本品 structured_specs 的数值集合")。
- 提产品可以,但用定性描述("nests compactly"),数字留给规格表。
- 校验不过的答案自动重写一次,仍不过则丢弃该条(FAQ 少而精)。

## 8. 上轮遗留(顺手清掉)
- **尺寸图强制**:SKILL.md 已加"组成硬规则"(main×1+dimension×1 强制)。代码侧在 image-brief 校验加同样断言:产品有 dimensions 而图组无 dimension 角色 → 校验失败让 AI 重出(别静默放行)。
- **callout/spec 两类 overlay 仍未验证**(上轮 dimension 通、这轮图组没生成这两类):确保三类都能渲染;dimension 叠字用 imperial(#2)。
- **卖点"生成松、批准严"不一致**:生成端(selling-points/generate)给 AI 的规则加上与批准校验同一把尺(数字必须来自所引证据),减少人工改写。
- **F→K 参考图先落地**:import-to-k 时把 1688 参考图**下载存进 K 媒体库**(服务端 UA/Referer 伪装或复用抓取通道),渲染不再临时下 alicdn(已实测 420 限流炸过一整批)。
- 渲染失败重试:图片模型瞬时失败(已试备用 key 仍失败)给自动二次重试(间隔退避),减少人工点重试。

## 硬约束
- 别造假:翻译/换算是对真数据的变换,允许;无据声明仍禁止。
- #3803 / #3812 不动;fail-safe 原则不变;品牌硬门不动。
- 迁移(package_includes/label_en 若涉表)先 ls versions 单 head;测试 `bash scripts/run_backend_tests.sh unit` 全绿。

## 交付
本地提交 + 测试绿 + 每条一句根因/修法。完成后 Claude 会用新产品(CCD-003)跑第三次端到端验证。
