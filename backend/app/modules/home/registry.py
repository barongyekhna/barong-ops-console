"""卡片注册表：谁能看、怎么加载、失败怎么隔离。

加载器只允许 `select`。3 秒一轮的流循环 × 打开的标签页数，任何一次顺手 commit
都会变成持续写压。`h_runs_list` / `orders_list` 这类「读接口里藏着回收+commit」
的东西一律不进这里。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ...models.user import User
from ..b2b import home_card as b2b_home_card
from ..cs_series import home_card as cs_home_card
from ..geo_series import home_card as geo_home_card
from ..h_series import home_card as h_home_card
from ..seo_series import home_card as seo_home_card
from ..w_series import home_card as w_home_card
from ..w_series.traffic import service as traffic_service
from . import approvals_card
from .context import HomeAccess
from .schemas import HomeCardRead

logger = logging.getLogger(__name__)

LoaderFn = Callable[..., HomeCardRead | None]


@dataclass(frozen=True)
class HomeCardSpec:
    card_id: str
    module_key: str | None
    # 任一命中即可看；空集 = 不看模块权限。
    required_any: frozenset[str]
    # 表没有 org 列的模块：调用者必须就是唯一目标组织。
    needs_target_org: bool
    # 流循环里这张卡最少隔多久重算一次，给重查询摊薄压力。
    min_refresh_seconds: float
    loader: LoaderFn


STORE_CARDS: tuple[HomeCardSpec, ...] = (
    HomeCardSpec("site-traffic", None, frozenset(), True, 60.0, traffic_service.load_home_card),
    HomeCardSpec("site-health", None, frozenset(), True, 30.0, h_home_card.load_home_card),
    HomeCardSpec(
        "cs-inbox",
        "cs.customer_service",
        frozenset({"cs.customer_service.read", "cs.customer_service.update"}),
        True,
        3.0,
        cs_home_card.load_home_card,
    ),
    HomeCardSpec(
        "w-orders",
        "w.site_ops",
        frozenset({"w.site_ops.read", "w.site_ops.manage"}),
        True,
        3.0,
        w_home_card.load_home_card,
    ),
    HomeCardSpec(
        "geo-todo",
        "geo.content",
        frozenset({"geo.content.read", "geo.content.execute", "geo.content.manage"}),
        False,
        3.0,
        geo_home_card.load_home_card,
    ),
    HomeCardSpec(
        "seo-todo",
        "seo.content",
        frozenset({"seo.content.read", "seo.content.execute", "seo.content.manage"}),
        False,
        3.0,
        seo_home_card.load_home_card,
    ),
    HomeCardSpec(
        "b2b-drafts",
        "b2b.wholesale",
        frozenset({"b2b.wholesale.read", "b2b.wholesale.manage", "b2b.wholesale.export"}),
        True,
        3.0,
        b2b_home_card.load_home_card,
    ),
    # 审批 + 通知：跨两个模块，归 home 自有；治理权在加载器内部判。排最后，
    # 它是唯一带语句超时的，出事时不影响前面的卡。
    HomeCardSpec("approvals", None, frozenset(), False, 15.0, approvals_card.load_home_card),
)

CARDS_BY_ID: dict[str, HomeCardSpec] = {spec.card_id: spec for spec in STORE_CARDS}


def allowed(spec: HomeCardSpec, access: HomeAccess) -> bool:
    if spec.needs_target_org and not access.is_target_org:
        return False
    if not spec.required_any:
        return True
    if access.is_full_access:
        return True
    return bool(spec.required_any & access.permission_keys)


def _degraded(spec: HomeCardSpec) -> HomeCardRead:
    return HomeCardRead(
        card_id=spec.card_id,
        module_key=spec.module_key,
        count=None,
        items=[],
        freshness=datetime.now(UTC),
        actions=[],
        extra={"degraded": True},
        severity="warn",
    )


def load_cards(
    db: Session,
    *,
    access: HomeAccess,
    user: User,
    specs: Sequence[HomeCardSpec] = STORE_CARDS,
) -> list[HomeCardRead]:
    out: list[HomeCardRead] = []
    for spec in specs:
        if not allowed(spec, access):
            continue
        try:
            card = spec.loader(
                db,
                workspace_key=access.workspace_key,
                user=user,
                permission_keys=access.permission_keys,
                is_full_access=access.is_full_access,
                governance_read=access.governance_read,
            )
        except Exception:  # noqa: BLE001 - 一张卡坏了不许拖死整页
            db.rollback()
            logger.exception("home card %s failed to load", spec.card_id)
            card = _degraded(spec)
        if card is not None:
            out.append(card)
    return out


def visible_specs(access: HomeAccess) -> list[HomeCardSpec]:
    return [spec for spec in STORE_CARDS if allowed(spec, access)]


__all__: list[str] = [
    "CARDS_BY_ID",
    "HomeCardSpec",
    "STORE_CARDS",
    "allowed",
    "load_cards",
    "visible_specs",
]
