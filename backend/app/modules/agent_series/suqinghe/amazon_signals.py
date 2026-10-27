"""亚马逊信号(10-27 选品评分卡用):同类关键词在亚马逊首页的竞争快照 + 前几名的 Keepa 月销。薄封装,全走台账。

- competition():R-A 现成的 Rainforest 搜索快照(ra_competition_snapshots 缓存 30 天,缓存未命中才花 2 credits);
  她自己再加一道日上限 sqh_rainforest(缓存命中退回),免得把 R-A 的 330/天吃光。
- keepa_top():前三名 ASIN 各查一次 Keepa(月销/BSR/评论/评分/价),台账 sqh_keepa。
钥匙都按贸易公司组织绑(R 模块那把),没绑就返回 error,评分卡把这一维标「没拿到」,不冒充 0。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
TOP_ASINS = 3


def competition(db: Session, *, org_id: str, keyword: str) -> dict[str, Any]:
    """{keyword, valid, review_wall_max, single_brand_share, dominant_brand, new_entrant_ratio_est, seller_count, top[], cache_hit} 或 {error}。"""
    from r_system_v2.ra.quota_ledger import PROVIDER_SQH_RAINFOREST, RAQuotaExhaustedError, refund, try_consume

    keyword = " ".join(str(keyword or "").split())
    if not keyword:
        return {"error": "没有能查的英文词"}
    try:
        try_consume(db, PROVIDER_SQH_RAINFOREST, amount=1)
    except RAQuotaExhaustedError:
        return {"keyword": keyword, "error": "今天她的亚马逊查询额度用完了"}
    db.commit()  # 出网前放掉事务
    try:
        from r_system_v2.ra.competition import ensure_competition_snapshot

        snap = ensure_competition_snapshot(db, org_id=org_id, context={}, keyword=keyword)
    except RAQuotaExhaustedError:
        refund(db, PROVIDER_SQH_RAINFOREST, amount=1)
        db.commit()
        return {"keyword": keyword, "error": "R-A 的 Rainforest 日额度用完了"}
    except Exception as exc:  # noqa: BLE001 —— 外部服务问题不能炸挑货;原因带回卡上
        logger.warning("rainforest snapshot failed keyword=%s: %s", keyword, exc)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        refund(db, PROVIDER_SQH_RAINFOREST, amount=1)
        db.commit()
        return {"keyword": keyword, "error": f"{exc.__class__.__name__}: {str(exc)[:120]}"}
    if snap.get("cache_hit"):
        refund(db, PROVIDER_SQH_RAINFOREST, amount=1)  # 缓存命中不算她的
        db.commit()
    return slim_snapshot(snap, keyword=keyword)


def slim_snapshot(snap: dict[str, Any], *, keyword: str) -> dict[str, Any]:
    payload = snap.get("payload") if isinstance(snap.get("payload"), dict) else {}
    source = str(snap.get("source") or "")
    valid = payload.get("valid") if isinstance(payload.get("valid"), bool) else not source.endswith("_invalid")
    sample = snap.get("page_one_sample") if isinstance(snap.get("page_one_sample"), list) else []
    top = [
        {
            "asin": str(item.get("asin") or ""),
            "title": str(item.get("title") or "")[:120],
            "brand": str(item.get("brand") or "")[:60],
            "rating": _num(item.get("rating")),
            "ratings_total": _int(item.get("ratings_total")),
        }
        for item in sample
        if isinstance(item, dict) and item.get("asin")
    ][:TOP_ASINS]
    return {
        "keyword": keyword,
        "valid": bool(valid),
        "review_wall_max": _int(snap.get("review_wall_max")),
        "single_brand_share": _num(snap.get("single_brand_share")),
        "dominant_brand": (str(snap.get("dominant_brand")) if snap.get("dominant_brand") else None),
        "new_entrant_ratio_est": _num(snap.get("new_entrant_ratio_est")),
        "seller_count": _int(payload.get("market_seller_count_est")),
        "top": top,
        "cache_hit": bool(snap.get("cache_hit")),
    }


def keepa_top(db: Session, *, org_id: str, asins: list[str], limit: int = TOP_ASINS) -> tuple[list[dict[str, Any]], str | None]:
    """前几名各查一次 Keepa。返回 ([{asin, monthly_sales, bsr, reviews, rating, price}], 第一条错误或 None)。"""
    from r_system_v2.ra.quota_ledger import PROVIDER_SQH_KEEPA, RAQuotaExhaustedError, refund, try_consume

    wanted = [str(a).strip() for a in asins if str(a or "").strip()][:limit]
    if not wanted:
        return [], "亚马逊首页没拿到 ASIN"
    try:
        from r_system_v2.core.secret_manager import SecretManager
        from r_system_v2.rw.providers.keepa_provider import KeepaProvider

        provider = KeepaProvider(org_id=org_id, secret_manager=SecretManager(db_session=db))
        if not provider.api_key:
            return [], "Keepa 钥匙没绑"
    except Exception as exc:  # noqa: BLE001 —— 钥匙/依赖问题不能炸挑货
        logger.warning("keepa provider unavailable: %s", exc)
        return [], f"Keepa 用不了:{exc.__class__.__name__}"
    rows: list[dict[str, Any]] = []
    error: str | None = None
    for asin in wanted:
        try:
            try_consume(db, PROVIDER_SQH_KEEPA, amount=1)
        except RAQuotaExhaustedError:
            error = error or "今天她的 Keepa 额度用完了"
            break
        db.commit()
        try:
            data = provider.fetch_product(asin)
        except Exception as exc:  # noqa: BLE001 —— 一条查不到不影响别的
            logger.warning("keepa fetch failed asin=%s: %s", asin, exc)
            refund(db, PROVIDER_SQH_KEEPA, amount=1)
            db.commit()
            error = error or f"{exc.__class__.__name__}: {str(exc)[:100]}"
            continue
        rows.append(
            {
                "asin": asin,
                "monthly_sales": _int(getattr(data, "monthly_sales", None)),
                "bsr": _int(getattr(data, "bsr", None)),
                "reviews": _int(getattr(data, "reviews", None)),
                "rating": _num(getattr(data, "rating", None)),
                "price": _num(getattr(data, "price", None)),
            }
        )
    return rows, error


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN 不要


def _int(value: Any) -> int | None:
    out = _num(value)
    return int(out) if out is not None else None


__all__ = ["TOP_ASINS", "competition", "keepa_top", "slim_snapshot"]
