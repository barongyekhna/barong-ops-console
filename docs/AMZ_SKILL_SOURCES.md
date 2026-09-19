# A 系列员工技能手册:来源与取舍

外部技能库:[liangdabiao/Amazon-Skills-Liang](https://github.com/liangdabiao/Amazon-Skills-Liang)(MIT,60 个技能,中文)。
2026-09-16 取 21 个剥壳,落在 `backend/app/modules/amz_series/skills/`,由 `prompt_skills.py` 全文注入员工提示词(system 第二条)。

## 吸收原则
1. 只取骨架:框架、清单、数字规则。删掉「先问用户选择题」的访谈壳、多平台泛化、输出格式模板、局限性免责声明。
2. 每条数字是初始默认值;与我们种子数据冲突时我们的数据赢;幅度受五道护栏截断(单次 ±25%、每店每日动作上限、总闸)。
3. 家规不可覆盖:影子期只建议;图片线永远人点头;不刷单不激励评论;不自动履约;事实表不够不写不画;老板被压货伤过,「宁可积压」改成「库存天数 ≥ 45 天 + 断货前 45 天提醒」。
4. 每份手册头部写来源与 MIT;`prompt_skills.manifest()` 给出 sha256。

## 映射

| 手册 | 员工 | 吸收的技能 | 取了什么 | 丢了什么 |
|---|---|---|---|---|
| d/ads-funnel-and-bids.md | 殷素素 D | amazon-ppc-campaign、amazon-negative-keywords、amazon-advertising-strategy、amazon-dayparting-strategy、amazon-seasonal-planning(广告部分) | 盈亏 ACoS / 目标 ACoS / 最高 CPC 三公式;四活动漏斗与起始出价比例;迁移与否词规则;出价调整档;否词四档 + 我们的需求储备第五档;否精准 vs 否短语;全漏斗与生命周期;旺季预算节奏 | 访谈流程、fetch-competitor 脚本、autocomplete curl、SB/SD 细节(未做)、分时出价实施(亚马逊不支持) |
| a/listing-copy.md | 殷笑笑 A | amazon-listing-optimization、amazon-backend-keywords、amazon-search-optimization、amazon-a-plus-content、amazon-return-reduction | 字符上限;关键词分层分配;标题 / 五点 / 描述结构;后台词 250 字节去重与禁词;8 维记分卡;A9/COSMO 要点与索引验证;A+ 模块顺序与 FAB;退货与页面准确性 | fetch-listing 脚本、web_search 找竞品、语气选择表、输出模板、尺码指南(服装) |
| b/listing-images.md | 殷熊 B | amazon-listing-images、amazon-a-plus-content(图 brief) | 七图职责;信息图层次 / 色彩 / 引导 / 数据可视化;移动端规则;A+ 图 brief 结构 | 专业摄影建议、平台列表 |
| c/competitors-and-sqp.md | 殷长辰 C | amazon-competitor-analysis、amazon-brand-analytics、amazon-review-analyzer、amazon-review-strategy、amazon-vine-program、amazon-seasonal-planning | SQP 四份额判据(点击 > 购买 = 详情页漏);SFR 读法;竞品对比框架与价格-评论矩阵;评论分层与投诉排序;合规催评(请求评论 5–30 天、插卡、Vine 窗口);季节日历与促销类型 | 抓评论脚本、购物篮 / 复购(无数据)、ERP 遗留、买家跟进邮件(不做) |
| e/finance-pnl.md | 殷乐乐 E | amazon-fba-calculator、amazon-profit-analyzer、tariff-calculator-amazon | 每日利润表口径;不算利润的行(转账 / 跨账户 / 后台广告扣费);月结摊销与「不完整」标记;广告盈亏;五条预警门槛 | calculator.py 脚本、场景模拟、估算成本(成本只认人填的) |
| shared/pnl-and-inventory.md | 笑笑 / 长辰 / 素素 / 乐乐共用 | amazon-fba-calculator、amazon-profit-analyzer、tariff-calculator-amazon、amazon-inventory-management、amazon-variation-strategy | 利润瀑布;FBA 尺寸层级表;到岸成本与 301 税率;补货点 / 安全库存 / IPI;退货阈值;变体合规与合并拆分 | calculator.py 脚本、HS 编码数据库、场景模拟输出格式 |

## 没纳入的(39 个)
one-shot、category / store / product-research、niche-finder、trending-products、deal-finder、shipping-calculator、repricing-strategy、buy-box、display-ads、sales-estimator、rank / keyword / price-tracker、keyword-research、brand-registry、brand-tailored-promotions、category-ungating、coupon-strategy、enhanced-brand-content、fba-prep、global-selling、international-listings、private-label、product-bundling、product-compliance、product-photography、seller-analytics、storefront-design、subscribe-save、suspension-appeal、wholesale-sourcing。
理由:属于 R 系列(选品)范围、依赖抓取脚本、或我们已有更好的数据源(Keepa、SP-API、广告 API)。product-bundling 和 coupon-strategy 在 A4 推新 / 促销时再评估。

## 更新办法
改手册 → `SKILLS_VERSION` 加一 → 跑 `tests/backend/test_amz_skills.py` → 重建 amz-agents-worker。不要在提示词里另写一套规则,规则只在手册里。
