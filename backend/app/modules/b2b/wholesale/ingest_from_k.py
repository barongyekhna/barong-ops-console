"""Pull a freshly uploaded product from K into the wholesale catalogue.

P 上架成功后调这里。刻意做成"只读 K、只写 b2b_wholesale_items",不反向
写 K——零售侧的真相源永远是 K,批发模块只是它的一个下游消费者。
"""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ...k_series.product_knowledge.models import (
    KProductKnowledgeProduct,
    KProductKnowledgeVariant,
)
from ..store_types import service as store_type_service
from . import service
from .schemas import IngestResult

logger = logging.getLogger(__name__)


def _lowest_variant_price(
    db: Session,
    product_id: UUID,
) -> Decimal | None:
    """多变体产品父价强制为空(2026-07-22 用户拍板),所以 MSRP 取变体最低价
    ——图册上写"起价多少",和网站上买家看到的起始价一致。"""
    prices = [
        price
        for price in db.scalars(
            select(KProductKnowledgeVariant.price_override).where(
                KProductKnowledgeVariant.product_id == product_id
            )
        )
        if price is not None
    ]
    return min(prices) if prices else None


def _resolve_category_path(db: Session, product) -> list[str]:
    """类目真相源是 K 的 google_product_category(谷歌类目数字 ID)。

    产品表上的 category_path/category_hint 都不可靠:前者实测全是空,后者是
    AI 给的建议文本、同类目下每个产品措辞都不一样,拿去分组会把 5 个捏捏球
    拆成 5 个组。google_product_category 才是 P 上架时真正用来建 Woo 类目
    的那个值,和网站上看到的一致。
    """
    google_id = (product.google_product_category or "").strip()
    if google_id:
        full_path = db.scalar(
            text("SELECT full_path FROM k_category_google WHERE id = :gid"),
            {"gid": google_id},
        )
        if full_path:
            return [
                part.strip()
                for part in str(full_path).split(">")
                if part.strip()
            ]
    raw_hint = (product.category_path or product.category_hint or "").strip()
    if raw_hint:
        separator = ">" if ">" in raw_hint else "/"
        return [
            part.strip() for part in raw_hint.split(separator) if part.strip()
        ]
    return []


def _format_variant_note(rows: list[tuple]) -> str | None:
    """把 (color, size, function, quantity) 四元组列表汇总成一句话。

    纯函数,不碰数据库——测起来干净,也方便单独验边界(整数列、空值、
    大小写不一致)。
    """
    if not rows:
        return None

    def _collect(index: int) -> list[str]:
        seen: list[str] = []
        for row in rows:
            raw = row[index]
            # quantity 是整数列,直接 .strip() 会炸(2026-07-27 实际踩过)。
            value = "" if raw is None else str(raw).strip()
            if not value:
                continue
            pretty = value[0].upper() + value[1:]
            if pretty not in seen:
                seen.append(pretty)
        return seen

    parts: list[str] = []
    colors = _collect(0)
    if len(colors) > 1:
        parts.append(f"{len(colors)} colors: {', '.join(colors)}")
    elif colors:
        parts.append(f"Color: {colors[0]}")
    for index, label in ((1, "Sizes"), (2, "Styles"), (3, "Pack sizes")):
        values = _collect(index)
        if index == 3 and values:
            # 装量是数字,按数值排序——"2, 1" 读起来像笔误。
            values = sorted(
                values,
                key=lambda v: (not v.isdigit(), int(v) if v.isdigit() else 0, v),
            )
        if values:
            parts.append(f"{label}: {', '.join(values)}")
    note = "; ".join(parts)
    return note[:255] or None


def _variant_note(db: Session, product_id: UUID) -> str | None:
    """把变体汇总成一句话写进产品卡。

    店家最关心"能不能配色卖、有几个款",这句话直接决定他要不要进。
    """
    rows = db.execute(
        select(
            KProductKnowledgeVariant.color,
            KProductKnowledgeVariant.size,
            KProductKnowledgeVariant.function,
            KProductKnowledgeVariant.quantity,
        ).where(KProductKnowledgeVariant.product_id == product_id)
    ).all()
    return _format_variant_note(list(rows))


def build_payload(
    db: Session,
    *,
    k_product_id: UUID,
    woo_product_id: int | None = None,
) -> dict[str, object] | None:
    product = db.get(KProductKnowledgeProduct, k_product_id)
    if product is None:
        return None
    sku = (product.sku or "").strip()
    if not sku:
        return None
    name = (product.product_name_en or "").strip()
    if not name:
        return None

    msrp = product.regular_price
    if msrp is None:
        msrp = _lowest_variant_price(db, k_product_id)

    category_path = _resolve_category_path(db, product)

    return {
        "sku": sku,
        "product_name": name,
        "msrp": msrp,
        "category_path": category_path,
        "k_product_id": k_product_id,
        "woo_product_id": woo_product_id,
        "variant_note": _variant_note(db, k_product_id),
    }


def ingest_uploaded_product(
    db: Session,
    *,
    k_product_id: UUID,
    woo_product_id: int | None = None,
    commit: bool = True,
) -> IngestResult:
    payload = build_payload(
        db,
        k_product_id=k_product_id,
        woo_product_id=woo_product_id,
    )
    if payload is None:
        return IngestResult(skipped=1)
    result = service.ingest_products(db, products=[payload], commit=False)
    # 上架即落位:按内置目录把这个类目该进的店型建出来(用户不用判断
    # "这个类目对应什么店型")。武器/情趣用品等黑名单类目不会落进任何店型。
    store_type_service.ensure_store_types_for_category(
        db,
        category_path=payload.get("category_path"),
        commit=False,
    )
    if commit:
        db.commit()
    return result


def ingest_uploaded_product_safely(
    db: Session,
    *,
    k_product_id: UUID,
    woo_product_id: int | None = None,
) -> None:
    """给 P 回报路径用的包装:批发目录出问题绝不能把上架回报带崩。"""
    try:
        # P 回报已在事务中,交给外层统一提交。
        ingest_uploaded_product(
            db,
            k_product_id=k_product_id,
            woo_product_id=woo_product_id,
            commit=False,
        )
    except Exception:  # noqa: BLE001 - 上架回报优先,批发灌数失败只记日志
        logger.exception(
            "B2B wholesale ingest failed for K product %s",
            k_product_id,
        )


def backfill_uploaded_products(db: Session) -> IngestResult:
    """回灌历史上架产品。

    P 上架成功自动灌入的钩子是 2026-07-27 才加的,在那之前上架的产品
    (最早那批捏捏球)从来没进过批发目录。这里按 p_upload_jobs 里成功的
    记录补一次,幂等——已存在的记录只更新零售快照,不碰人工填的批发价。
    """
    rows = db.execute(
        text(
            "SELECT DISTINCT ON (product_id) product_id, external_product_id "
            "FROM p_upload_jobs WHERE status = 'success' "
            "ORDER BY product_id, finished_at DESC"
        )
    ).all()
    payloads: list[dict[str, object]] = []
    skipped = 0
    for product_id, external_product_id in rows:
        woo_id = None
        if external_product_id and str(external_product_id).isdigit():
            woo_id = int(external_product_id)
        payload = build_payload(db, k_product_id=product_id, woo_product_id=woo_id)
        if payload is None:
            skipped += 1
            continue
        payloads.append(payload)
    if not payloads:
        return IngestResult(skipped=skipped)
    result = service.ingest_products(db, products=payloads, commit=False)
    # 回灌的历史产品同样要落位,否则老品永远进不了店型。
    for payload in payloads:
        store_type_service.ensure_store_types_for_category(
            db,
            category_path=payload.get("category_path"),
            commit=False,
        )
    db.commit()
    result.skipped += skipped
    return result
