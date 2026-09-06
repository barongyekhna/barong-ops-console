"""制造公司主页的卡片注册表 + 按组织类型选卡。

独立成文件而不塞进 `registry.py`：那份文件另一个头正在给贸易公司追加社媒卡，
两边只在各自文件里追加，谁也不会覆盖谁。
"""

from __future__ import annotations

from collections.abc import Sequence

from ..agent_series.nijing import home_card as nijing_home_card
from ..m_series import home_card as mfg_home_card
from . import approvals_card
from .context import FACTORY_ORG_TYPE, STORE_ORG_TYPE, HomeAccess
from .registry import STORE_CARDS, HomeCardSpec

# 顺序即设计顺序：库存总览（占两列）→ 生产能力/缺料 → 今日单据 → 霓旌 → 审批。
# 三张 mfg 卡的门是 M 模块的角色硬门，在加载器里判（不过门返回 None），
# 所以这里 required_any 为空；nijing/approvals 与模块无关。
FACTORY_CARDS: tuple[HomeCardSpec, ...] = (
    HomeCardSpec("mfg-stock", "mfg.inventory", frozenset(), False, 30.0, mfg_home_card.load_stock_card),
    HomeCardSpec("mfg-capacity", "mfg.inventory", frozenset(), False, 30.0, mfg_home_card.load_capacity_card),
    HomeCardSpec("mfg-docs", "mfg.inventory", frozenset(), False, 3.0, mfg_home_card.load_docs_card),
    HomeCardSpec("nijing", None, frozenset(), False, 15.0, nijing_home_card.load_home_card),
    HomeCardSpec("approvals", None, frozenset(), False, 15.0, approvals_card.load_home_card),
)

_BY_ORG_TYPE: dict[str, tuple[HomeCardSpec, ...]] = {
    STORE_ORG_TYPE: STORE_CARDS,
    FACTORY_ORG_TYPE: FACTORY_CARDS,
}


def cards_for(access: HomeAccess) -> tuple[HomeCardSpec, ...]:
    """这个组织类型有哪套卡；没有皮的组织类型返回空元组（前端据此回退旧主页）。"""
    return _BY_ORG_TYPE.get(access.org_type, ())


def spec_for(card_id: str, access: HomeAccess) -> HomeCardSpec | None:
    for spec in cards_for(access):
        if spec.card_id == card_id:
            return spec
    return None


def all_card_ids() -> Sequence[str]:
    seen: list[str] = []
    for specs in _BY_ORG_TYPE.values():
        for spec in specs:
            if spec.card_id not in seen:
                seen.append(spec.card_id)
    return seen
