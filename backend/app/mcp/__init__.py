"""MCP(Model Context Protocol)机器面:给外部桌面代理(Codex 等)用的 sidecar。

只有协议层住这里;业务在各模块(K 的在 ``k_series/product_knowledge/mcp_channel.py``)。
跑法:``python -m backend.app.mcp``(独立容器 ``k-mcp``,不进主后端进程)。
"""
