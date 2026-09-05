"""独立站流量（Jetpack Stats）采集与汇总。

数据由 n8n 流 `barongWtraffic001` 每 10 分钟从站内 Jetpack REST 拉取后原样推到
`POST /w/traffic/ingest`；归一化、落库、按区间聚合全部在这里做，n8n 只打包不加工。
"""
