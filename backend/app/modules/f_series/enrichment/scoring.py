"""F 候选推荐评分：MOQ 为王的确定性打分 + 画像产品组内 top3 推荐。

用户拍板（2026-07-14）：每个画像产品推荐评分最高的 3 家，MOQ 作为重要
加分项（越小分越高），其余候选折叠可展开。

分项（总分 100，全部确定性可解释，存 score_json 供前端明细展示）：
- moq_pts   0-50  MOQ=1 满分 50，按 log10 衰减（2→46 / 10→38 / 100→26 /
                  1000→14）；未知 MOQ 给 20（不能压过已知小单）
- sales_pts 0-25  月销 log10 刻度（100→12 / 1000→19 / 1万+→25）；未知 0
- opa_pts   0/10  一件代发（one_piece_hint）+10
- price_pts 0-15  组内相对价：同画像产品最便宜 15、最贵 0 线性；单家或
                  无价给 8（中位）

price_pts 依赖组内全体，所以每轮找货落库后按 (category_id,
profile_product_zh) 组重算全组分数与名次（幂等，重跑自动纠正）。
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import FCategoryCandidate

RECOMMEND_TOP_N = 3

_PRICE_MID_PTS = 8


def base_components(
    *,
    moq: int | None,
    monthly_sales: int | None,
    one_piece_hint: bool,
) -> dict[str, Any]:
    """落库时可算的静态分项（价格分留待组内重算）。"""
    if moq is None or moq <= 0:
        moq_pts = 20
    else:
        moq_pts = max(0, round(50 - 12 * math.log10(max(moq, 1))))
        moq_pts = min(50, moq_pts)
    if monthly_sales is None or monthly_sales <= 0:
        sales_pts = 0
    else:
        sales_pts = min(25, round(25 * math.log10(monthly_sales + 1) / 4))
    return {
        "moq": moq,
        "monthly_sales": monthly_sales,
        "moq_pts": moq_pts,
        "sales_pts": sales_pts,
        "opa_pts": 10 if one_piece_hint else 0,
    }


def _price_points(
    price: Decimal | None, low: Decimal | None, high: Decimal | None
) -> int:
    if price is None or low is None or high is None:
        return _PRICE_MID_PTS
    if high <= low:
        return _PRICE_MID_PTS
    ratio = float((high - price) / (high - low))
    return max(0, min(15, round(15 * ratio)))


def rescore_product_group(
    db: Session,
    *,
    category_id: str,
    profile_product_zh: str,
) -> None:
    """重算一个画像产品组的组内价格分、总分与 top3 名次（幂等）。"""
    rows = db.scalars(
        select(FCategoryCandidate)
        .where(FCategoryCandidate.category_id == category_id)
        .where(FCategoryCandidate.profile_product_zh == profile_product_zh)
    ).all()
    if not rows:
        return
    prices = [row.price_cny for row in rows if row.price_cny is not None]
    low = min(prices) if prices else None
    high = max(prices) if prices else None

    scored: list[tuple[int, FCategoryCandidate]] = []
    for row in rows:
        parts = dict(row.score_json or {})
        parts["price_pts"] = _price_points(row.price_cny, low, high)
        total = (
            int(parts.get("moq_pts") or 0)
            + int(parts.get("sales_pts") or 0)
            + int(parts.get("opa_pts") or 0)
            + int(parts["price_pts"])
        )
        parts["total"] = total
        row.score_json = parts
        row.score = total
        scored.append((total, row))

    # 名次：分数降序，同分按价升序再按创建时间稳定排；前 3 名 rank 1-3。
    scored.sort(
        key=lambda item: (
            -item[0],
            item[1].price_cny if item[1].price_cny is not None else Decimal("1e12"),
            item[1].id.hex,
        )
    )
    for index, (_, row) in enumerate(scored):
        row.recommended_rank = index + 1 if index < RECOMMEND_TOP_N else None
    db.flush()
