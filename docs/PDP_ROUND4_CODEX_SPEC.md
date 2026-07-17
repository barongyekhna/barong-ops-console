# PDP 第四轮 · Codex 规格(FAQ 同步铁律 + schema 修形 + 图位铁律 + 宽高比自动化)

> 背景:CCD-003(Woo #3821)终审后用户复查发现 4 个问题,已全部取证定根因。**#3803/#3812/#3821 都不许动**(对比样本);验证走下一个新产品。无远程仓库不 push。Claude 侧已改 SKILL.md(图位/宽高比规则)与家规 CSS,避开。

## 1. 【最高优先·谷歌红线】FAQ 同步铁律(schema 与页面可见 FAQ 不一致)
**实锤证据链**:页面可见 FAQ **整段消失**;FAQPage schema 显示旧问答(kettle/material);K 最新 copy 的 page_faq 是新问题(titanium);Woo meta `_kp_faq` 残留旧问答。
**根因(三层连锁)**:
1. 文案重生成产出的 FAQ 未挂 faq_research 证据 → 质量门把可见 FAQ 整段砍掉;
2. n8n 只在 `desc.faq` 非空时写 `_kp_faq` meta,**空时不写也不删** → 旧 meta 残留;
3. 站点端 FAQPage schema 从残留 meta 渲染 → schema 问答页面上不存在 = **谷歌眼里的 schema 造假**。
**修**:
- n8n「转 Woo 格式」:`desc.faq` 为空/不合格时**显式推空/删除** `_kp_faq` meta(如 `meta_data.push({key:'_kp_faq', value:''})` 或按 Woo REST 删 meta 的等效方式),绝不残留旧值。
- **单一数据源**:FAQPage schema 只允许从"当次上架包的可见 FAQ"生成;可见 FAQ 与 `_kp_faq` 必须出自同一份数据、同一次写入。
- **上架后自动校验**(P 回报/审计步):抓已发布页面,断言 schema FAQ ⊆ 页面可见 FAQ;不一致 → 记 error 级日志/通知(fail-safe 不回滚,但必须报警)。
- **文案重生成的 FAQ 必须复用 faq_research**:generate_marketing_copy 每次都把 faq_research_json 的问题簇作为 FAQ 唯一来源(regen 时若 research 存在则复用,不存在先跑 research);产出的 page_faq 必须携带质量门要的证据引用,避免"生成了但被砍"。

## 2. priceSpecification 变形(数组被挤成字典)
**实锤**:`offers[0].priceSpecification` 变成 `{"0":{...},"1":{...},"price":"42",...}` 混合对象——插件向 Yoast 的数组注入扁平键把 list 变 dict。
**修**(`backend/app/modules/p_series/wordpress/kp-product-structured-data.php` 的 offer 过滤器):扁平 `price`/`priceCurrency`/`priceValidUntil` 只写在 **Offer 顶层**(已做,保留);**`priceSpecification` 保持原数组结构原样不动**(检测 `isset($offer['priceSpecification']) && is_array(...)` 时不得向其塞字符串键;PHP 数组注意 list vs assoc)。加回归测试(有 fixture 模拟 Yoast 数组形状)。

## 3. 主副图(gallery)铁律:至少 6 张,五类缺一不可
**实锤**:CCD-003 图廊只有 2 张(main+dimension),信息图/配件图/场景全被排进 description。
**修**(image brief 校验,与既有 dimension 强制同一个门):
- **gallery 必含**:`main`×1 + `feature_callout`×1 + `accessory`×1 + `dimension`×1 + `proof_scene`×≥2 → **合计 ≥6**;
- description 另配横版场景图(kp-module 图文并排用),不与 gallery 抢配额;
- 产品确实无配件(无 package_includes 或单件)时 `accessory` 可豁免,但 gallery 仍须 ≥5 且含 1 张信息图;
- 校验不过=打回 AI 重排(brief 重出),重试 1 次仍不过按 fail-safe 记日志放行但报警。SKILL.md 已由 Claude 同步同一规则。

## 4. 【自动化重点】按图位定宽高比(源头治"描述图太高")
**根因**:所有渲染图 1:1(1800×1800);方图进图文并排模块,文字少图太高,头重脚轻。CSS 压高度只是裁症状。
**修(管道源头,一次定终身)**:
- 规则:`placement=gallery` → aspect_ratio **1:1**;`placement=description` → **4:3(横)**(3:2 亦可,定一个写死)。
- **代码强制**:enqueue 渲染时按 placement **硬性覆写** `aspect_ratio`(不信 AI 自觉;brief 里 AI 写错也拉回)。I 系列出图 API 本就接收 aspect_ratio 参数,管道天生支持。
- info-overlay 合成(dimension/callout/spec)当前按方图布局的锚点/包围盒逻辑需兼容非方图(gallery 类是 1:1 不受影响;若未来 description 出现叠字图,合成器要按实际宽高比计算)。
- 回归:断言 description 位产出图的宽高比为 4:3(检查 I 资产元数据或渲染参数)。

## 硬约束
- 三个对比产品(#3803/#3812/#3821)不动;fail-safe 不变;品牌硬门不变;别造假。
- 测试 `bash scripts/run_backend_tests.sh unit` 全绿;若改 n8n JSON,仓库文件为准(线上导入由 Claude 做)。
- 顺手项(上轮已记,如便利就一起):卖点证据解析器支持 `additional_specs.<key>` 路径;dispatch API 路由在门禁全清后仍 409 的多余校验(容器内直调正常,定位并修掉)。

## 交付
本地提交 + 测试绿 + 每条一句根因/修法。完成后 Claude 用新产品跑第四轮端到端验证(重点:FAQ 两处一致、schema 合形、gallery≥6 五类齐、描述图 4:3)。
