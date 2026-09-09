"""Agent series — 数字员工。

每个数字员工 = 一份人格配置(职责/非职责/动作白名单/风险上限) + 共用的
runtime。加一个员工应该是加一份配置,不是加一个模块。

第一位:白苏婉(内容专员)。见 docs/AGENT_BAISUWAN_V1.md。
第二位:霓旌(制造公司库管员)。见 docs/AGENT_NIJING_V1.md。
第三位:殷承岳(贸易公司产品助理,只判谷歌类目)。见 docs/AGENT_YINCHENGYUE_V1.md。

欠账:三位的 worker 主循环(login/轮询/心跳/日志)是三份相同的复制。第三份落地时
有意没抽 common/worker_base.py——不想把两个在产线跑稳的员工卷进同一次发版;
下一位员工之前先抽。
"""
