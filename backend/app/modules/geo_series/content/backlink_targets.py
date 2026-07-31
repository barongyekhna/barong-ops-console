"""Which live products need their "Learn more" block refreshed, and to what.

The console decides everything here so the workflow stays a dumb pipe: it resolves
the Woo product id from the successful upload, builds the finished block, and drops
products that would be a no-op — a run that rewrites nothing still costs API calls
and shows up as churn in the store's revision history.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.models import KProductKnowledgeProduct
from ...p_series.upload.models import PUploadJob
from .backlink import guides_block_for_product
from .models import GeoContentCluster

logger = logging.getLogger(__name__)


def _woo_id_for(db: Session, product_id: Any) -> int | None:
    """The live Woo product id, from the newest successful upload of this product."""
    rows = db.execute(
        select(PUploadJob.external_product_id)
        .where(
            PUploadJob.product_id == product_id,
            PUploadJob.status == "success",
            PUploadJob.external_product_id.is_not(None),
        )
        .order_by(PUploadJob.finished_at.desc(), PUploadJob.created_at.desc())
    ).all()
    for (external_id,) in rows:
        text = str(external_id or "").strip()
        if text.isdigit() and int(text) > 0:
            return int(text)
    return None


def _cluster_product_ids(db: Session) -> list[str]:
    """Every product attached to any cluster — those are the only candidates."""
    ids: list[str] = []
    seen: set[str] = set()
    for (product_ids,) in db.execute(
        select(GeoContentCluster.product_ids_json)
    ).all():
        for raw in product_ids if isinstance(product_ids, list) else []:
            text = str(raw or "").strip()
            if text and text not in seen:
                seen.add(text)
                ids.append(text)
    return ids


# 上次真的写进各产品页的块组合哈希。存在 GeoSiteSetting 这张现成 KV 表里,
# 不为一个字典再开一张表。
BLOCK_FINGERPRINTS_KEY = "product_block_fingerprints"


def _read_fingerprints(db: Session) -> dict[str, str]:
    from .models import GeoSiteSetting

    raw = db.scalar(
        select(GeoSiteSetting.value).where(
            GeoSiteSetting.key == BLOCK_FINGERPRINTS_KEY
        )
    )
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return {str(k): str(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}


def write_fingerprints(db: Session, updates: dict[str, str]) -> None:
    """把这次真写进去的指纹落库。派单回报成功时调用。"""
    from .models import GeoSiteSetting

    if not updates:
        return
    current = _read_fingerprints(db)
    current.update({str(k): str(v) for k, v in updates.items()})
    row = db.get(GeoSiteSetting, BLOCK_FINGERPRINTS_KEY)
    payload = json.dumps(current, sort_keys=True, ensure_ascii=False)
    if row is None:
        db.add(GeoSiteSetting(key=BLOCK_FINGERPRINTS_KEY, value=payload))
    else:
        row.value = payload
    db.flush()


def _fingerprint(blocks: list[tuple[str, str]]) -> str:
    """块组合的哈希。顺序稳定(按 class 排),所以同样的内容永远同一个指纹。"""
    canonical = json.dumps(sorted(blocks), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _reason(previous: str, blocks: dict[str, str], had_history: bool) -> str:
    """给运营一句人话:这个产品为什么要更新。"""
    guides = blocks.get("kp-guides", "")
    factory = blocks.get("kp-factory", "")
    if not guides and not factory:
        return "摘除失效区块（相关内容已全部下线）"
    parts: list[str] = []
    if guides:
        parts.append(f"{guides.count('<li>')} 篇指南")
    if factory:
        parts.append(f"{factory.count('<li>')} 篇工艺文")
    verb = "更新为" if had_history and previous else "首次挂上"
    return f"{verb} " + " + ".join(parts)


def collect_backlink_targets(
    db: Session, *, product_ids: list[str] | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """(targets, skipped) — targets 可以直接派单,skipped 解释其余的。

    每个 target 带这个产品的**全部**块。绝不把一个产品拆成多条:n8n 是
    「GET 全部 → 合并 → PUT 全部」,两条 target 会读到同一份旧 description,
    第二条 PUT 抹掉第一条(契约 v2 的由来)。

    ``product_ids`` 收窄扫描范围(上架钩子只关心刚上的那个),不传就是全站扫。
    """
    # 先把「线上真实状态」刷新一次(一次批量 API)。不刷就可能把草稿指南挂到
    # 产品页上——published_url 在草稿期就已经写库了。
    from .live_state import refresh_item_live_state_safely
    from ...seo_series.content.live_state import (
        refresh_item_live_state_safely as refresh_seo_live_state,
    )

    refresh_item_live_state_safely(db)
    # 工艺文的发布状态也要核——它现在也上产品页了。
    refresh_seo_live_state(db)

    from ...seo_series.content.product_backlink import factory_block_for_product

    known = _read_fingerprints(db)
    wanted = {str(x).strip() for x in (product_ids or []) if str(x).strip()}

    targets: list[dict[str, Any]] = []
    skipped: list[str] = []

    for raw_id in _cluster_product_ids(db):
        if wanted and raw_id not in wanted:
            continue
        product = None
        for column in (KProductKnowledgeProduct.id, KProductKnowledgeProduct.product_key):
            try:
                product = db.scalar(
                    select(KProductKnowledgeProduct).where(column == raw_id)
                )
            except Exception:  # noqa: BLE001 - a UUID column rejects a non-UUID string
                db.rollback()
                product = None
            if product is not None:
                break
        if product is None:
            skipped.append(f"{raw_id}：K 里找不到这个产品")
            continue

        label = str(getattr(product, "sku", "") or product.id)
        woo_id = _woo_id_for(db, product.id)
        if woo_id is None:
            skipped.append(f"{label}：还没有成功上架的 Woo 产品页")
            continue

        guides = guides_block_for_product(
            db, product_id=product.id, product_key=product.product_key
        )
        factory = factory_block_for_product(
            db, product_id=product.id, product_key=product.product_key
        )
        blocks = [("kp-guides", guides), ("kp-factory", factory)]
        fingerprint = _fingerprint(blocks)
        previous = known.get(str(woo_id), "")

        if previous == fingerprint:
            skipped.append(f"{label}：已是最新")
            continue
        if not guides and not factory and not previous:
            # 从来没挂过、现在也没得挂 —— 真正的无操作。
            skipped.append(f"{label}：还没有可挂的内容")
            continue

        # **两块都空但有历史 → 照样派单,两块都传 ""。**
        # 契约里空串定义为"摘掉块",而旧代码在这里直接 continue,
        # 导致指南全下线之后产品页上的死链永远摘不掉(2026-07-31 查出)。
        targets.append(
            {
                "product_id": str(product.id),
                "sku": getattr(product, "sku", None),
                "woo_product_id": woo_id,
                "blocks": [
                    {"block_class": cls, "html": html} for cls, html in blocks
                ],
                "fingerprint": fingerprint,
                "reason": f"{label}：" + _reason(
                    previous, dict(blocks), bool(previous)
                ),
            }
        )

    # 顺序稳定:同样的库状态永远产出同样的包。
    targets.sort(key=lambda t: t["woo_product_id"])
    skipped.sort()
    return targets, skipped


__all__ = [
    "BLOCK_FINGERPRINTS_KEY",
    "collect_backlink_targets",
    "write_fingerprints",
]
