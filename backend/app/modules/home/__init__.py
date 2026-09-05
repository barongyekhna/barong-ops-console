"""贸易公司主页：按组织类型换皮的待办卡片 + 单条 SSE 推送流。

骨架不认识任何模块。每个模块自己出一个 `home_card.py::load_home_card`，这里的
注册表只负责：谁有资格看哪张卡、逐卡加载、单卡失败隔离、有变化才推。
"""

from .router import router

__all__ = ["router"]
