---
name: amz-finance
description: 亚马逊财务(每日利润表、广告盈亏、成本与费用口径)——殷乐乐的手册。在本仓库做 A 系列亚马逊运营相关改动、分析报表或写员工规则时使用。
---

# amz-finance

这份 Claude Code 技能是员工手册的薄壳。规则只在一处维护:

- 手册正文:`backend/app/modules/amz_series/skills/e/finance-pnl.md`
- 共用算账手册:`backend/app/modules/amz_series/skills/shared/pnl-and-inventory.md`
- 来源与取舍:`docs/AMZ_SKILL_SOURCES.md`(外部技能库 MIT,已剥壳)

## 用法

1. 先读手册正文,再动手;数字是初始默认值,与 `var/amazon/seed/` 的真实数据冲突时数据赢。
2. 家规不可覆盖:影子期只建议、图片线永远人点头、不刷单不激励评论、不自动履约、事实表不够不写不画。
3. 改手册要同步 `prompt_skills.SKILLS_VERSION`,跑 `tests/backend/test_amz_skills.py`,重建 amz-agents-worker。
