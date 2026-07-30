"""Service layer for the B2B wholesale catalogue."""

from __future__ import annotations

import os
import tempfile
import urllib.request
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..linesheet.schemas import LineSheetItem, LineSheetMeta, LineSheetRequest
# 对外口径全部从 policies 取——**唯一真相源**。图册和产品页小窗共用同一份,
# 改一处两处生效;各自抄一份的话,门槛一改两边必然对不上(GMC 口径不一致的雷)。
from ..policies import (
    ADDRESS_LINES,
    CONTACT_PHONE,
    DEFAULT_CURRENCY,
    DEFAULT_MIN_ORDER_VALUE,
    LEGAL_ENTITY,
    PAYMENT_TERMS as DEFAULT_PAYMENT_TERMS,
    RETAIL_CONTACT_EMAIL as CONTACT_EMAIL,
    line_sheet_notes,
)
from .models import (
    STATUS_ARCHIVED,
    STATUS_PENDING,
    STATUS_READY,
    B2BWholesaleItem,
)
from .schemas import (
    CATEGORY_PROSPECTING_MIN_READY_ITEMS,
    CategoryReadiness,
    IngestResult,
    LineSheetExportRequest,
    WholesaleItemBatchPatch,
    WholesaleItemPatch,
)

# 图册抬头必须和网站上写的一字不差。今天(2026-07-27)刚因为"GMC 说的和
# 网站说的不一样"被判虚假陈述,line sheet 是又一份对外文件,不能再开第二
# 套口径。改这里之前先去核对 /contact/ 页。
BRAND_NAME = "Barong Yekhna"
IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 20


class WholesaleValidationError(ValueError):
    """Caller passed something the catalogue refuses to store."""


class WholesaleNotFoundError(LookupError):
    """Requested wholesale item does not exist."""


def _recompute_status(item: B2BWholesaleItem) -> None:
    """状态永远由数据推导,不给人工直接改 status 的口子——
    否则会出现"标着 ready 其实缺价"的记录混进图册。"""
    if item.status == STATUS_ARCHIVED:
        return
    item.status = (
        STATUS_READY if item.wholesale_fields_complete() else STATUS_PENDING
    )


def _commit(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


# --------------------------------------------------------------------------
# 读取
# --------------------------------------------------------------------------
def list_items(
    db: Session,
    *,
    status: str | None = None,
    needs_review: bool | None = None,
    category_prefix: list[str] | None = None,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[B2BWholesaleItem], dict[str, int]]:
    stmt = select(B2BWholesaleItem)
    if status:
        stmt = stmt.where(B2BWholesaleItem.status == status)
    if needs_review is not None:
        stmt = stmt.where(B2BWholesaleItem.needs_review == needs_review)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            B2BWholesaleItem.sku.ilike(pattern)
            | B2BWholesaleItem.product_name.ilike(pattern)
        )
    rows = list(
        db.scalars(
            stmt.order_by(
                B2BWholesaleItem.status.asc(),
                B2BWholesaleItem.sku.asc(),
            )
            .limit(max(1, min(limit, 1000)))
            .offset(max(0, offset))
        )
    )
    if category_prefix:
        rows = [row for row in rows if _matches_prefix(row, category_prefix)]

    counts = {
        "pending_count": _count_by(db, status=STATUS_PENDING),
        "ready_count": _count_by(db, status=STATUS_READY),
        "needs_review_count": _count_by(db, needs_review=True),
    }
    return rows, counts


def _count_by(
    db: Session,
    *,
    status: str | None = None,
    needs_review: bool | None = None,
) -> int:
    stmt = select(func.count()).select_from(B2BWholesaleItem)
    if status:
        stmt = stmt.where(B2BWholesaleItem.status == status)
    if needs_review is not None:
        stmt = stmt.where(B2BWholesaleItem.needs_review == needs_review)
    return int(db.scalar(stmt) or 0)


def _matches_prefix(item: B2BWholesaleItem, prefix: list[str]) -> bool:
    path = list(item.category_path or [])
    return path[: len(prefix)] == prefix


def get_item(db: Session, item_id: UUID) -> B2BWholesaleItem:
    item = db.get(B2BWholesaleItem, item_id)
    if item is None:
        raise WholesaleNotFoundError("Wholesale item does not exist.")
    return item


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------
def update_item(
    db: Session,
    *,
    item_id: UUID,
    patch: WholesaleItemPatch,
) -> B2BWholesaleItem:
    item = get_item(db, item_id)
    _apply_patch(item, patch)
    _commit(db)
    db.refresh(item)
    return item


def batch_update(
    db: Session,
    *,
    payload: WholesaleItemBatchPatch,
) -> list[B2BWholesaleItem]:
    if not payload.items:
        return []
    ids = [entry.item_id for entry in payload.items]
    rows = {
        row.id: row
        for row in db.scalars(
            select(B2BWholesaleItem).where(B2BWholesaleItem.id.in_(ids))
        )
    }
    missing = [str(i) for i in ids if i not in rows]
    if missing:
        raise WholesaleNotFoundError(
            f"Unknown wholesale item(s): {', '.join(missing)}"
        )
    for entry in payload.items:
        _apply_patch(rows[entry.item_id], entry)
    _commit(db)
    updated = []
    for item_id in ids:
        row = rows[item_id]
        db.refresh(row)
        updated.append(row)
    return updated


def _apply_patch(item: B2BWholesaleItem, patch: WholesaleItemPatch) -> None:
    if patch.wholesale_price is not None:
        item.wholesale_price = patch.wholesale_price
    if patch.price_tiers is not None:
        item.price_tiers_json = [
            {"min_qty": tier.min_qty, "unit_price": str(tier.unit_price)}
            for tier in patch.price_tiers
        ]
    if patch.case_pack is not None:
        item.case_pack = patch.case_pack
    if patch.moq_units is not None:
        item.moq_units = patch.moq_units
    if patch.lead_time_days is not None:
        item.lead_time_days = patch.lead_time_days
    if patch.variant_note is not None:
        item.variant_note = patch.variant_note or None
    if patch.notes is not None:
        item.notes = patch.notes or None
    if patch.clear_review_flag:
        item.needs_review = False
        item.review_reason = None
    if (
        item.wholesale_price is not None
        and item.msrp is not None
        and item.wholesale_price > item.msrp
    ):
        raise WholesaleValidationError(
            "Wholesale price cannot exceed the retail price (MSRP)."
        )
    _recompute_status(item)


# --------------------------------------------------------------------------
# 从零售侧灌数据(P 上架成功后调用)
# --------------------------------------------------------------------------
def ingest_products(
    db: Session,
    *,
    products: list[dict[str, object]],
    commit: bool = True,
) -> IngestResult:
    """把上架好的产品灌进批发目录。

    只写零售侧快照字段;批发价那些**绝不覆盖人工填过的值**——重跑一次上架
    不该把人辛苦定的价清掉。零售价变了则标待复核,因为 line sheet 上印的
    MSRP 必须和网站一致。

    commit=False 供 P 上架回报路径使用:那边已经在一个事务里,这里再提交
    会把回报的事务语义切断(后续失败就回滚不掉已落的 job 状态)。
    """
    result = IngestResult()
    for raw in products:
        sku = str(raw.get("sku") or "").strip()
        if not sku:
            result.skipped += 1
            continue
        name = str(raw.get("product_name") or raw.get("name") or "").strip()
        if not name:
            result.skipped += 1
            continue

        msrp = _as_decimal(raw.get("msrp") or raw.get("price"))
        item = db.scalar(
            select(B2BWholesaleItem).where(B2BWholesaleItem.sku == sku)
        )
        if item is None:
            item = B2BWholesaleItem(sku=sku, product_name=name, msrp=msrp)
            _assign_retail_snapshot(item, raw, msrp)
            _recompute_status(item)
            db.add(item)
            result.created += 1
            continue

        previous_msrp = item.msrp
        _assign_retail_snapshot(item, raw, msrp)
        item.product_name = name
        if (
            previous_msrp is not None
            and msrp is not None
            and previous_msrp != msrp
            and item.wholesale_price is not None
        ):
            item.needs_review = True
            item.review_reason = (
                f"Retail price changed {previous_msrp} -> {msrp}; "
                "re-check the wholesale price and margin."
            )
            result.flagged_for_review += 1
        _recompute_status(item)
        result.updated += 1

    if commit:
        _commit(db)
    else:
        db.flush()
    return result


def _assign_retail_snapshot(
    item: B2BWholesaleItem,
    raw: dict[str, object],
    msrp: Decimal | None,
) -> None:
    if msrp is not None:
        item.msrp = msrp
    category_path = raw.get("category_path")
    if isinstance(category_path, list) and category_path:
        item.category_path = [str(part) for part in category_path]
    image_url = raw.get("image_url")
    if isinstance(image_url, str) and image_url.strip():
        item.image_url = image_url.strip()
    # 变体说明只在空的时候写入——人工改过就不覆盖(同批发价的规矩)。
    variant_note = raw.get("variant_note")
    if isinstance(variant_note, str) and variant_note.strip() and not item.variant_note:
        item.variant_note = variant_note.strip()[:255]
    k_product_id = raw.get("k_product_id")
    if isinstance(k_product_id, UUID):
        item.k_product_id = k_product_id
    elif isinstance(k_product_id, str) and k_product_id:
        try:
            item.k_product_id = UUID(k_product_id)
        except ValueError:
            pass
    woo_product_id = raw.get("woo_product_id")
    if isinstance(woo_product_id, int):
        item.woo_product_id = woo_product_id


def _as_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None


# --------------------------------------------------------------------------
# 类目成熟度(挖客户门禁)
# --------------------------------------------------------------------------
def category_readiness(db: Session) -> list[CategoryReadiness]:
    buckets: dict[tuple[str, ...], dict[str, int]] = defaultdict(
        lambda: {"total": 0, "ready": 0, "pending": 0, "review": 0}
    )
    for item in db.scalars(select(B2BWholesaleItem)):
        if item.status == STATUS_ARCHIVED:
            continue
        key = tuple(item.category_path or ["(uncategorised)"])
        bucket = buckets[key]
        bucket["total"] += 1
        if item.status == STATUS_READY:
            bucket["ready"] += 1
        else:
            bucket["pending"] += 1
        if item.needs_review:
            bucket["review"] += 1

    out: list[CategoryReadiness] = []
    for key in sorted(buckets):
        bucket = buckets[key]
        ready = bucket["ready"]
        out.append(
            CategoryReadiness(
                category_path=list(key),
                total_items=bucket["total"],
                ready_items=ready,
                pending_items=bucket["pending"],
                needs_review_items=bucket["review"],
                prospecting_unlocked=(
                    ready >= CATEGORY_PROSPECTING_MIN_READY_ITEMS
                ),
                shortfall=max(
                    0, CATEGORY_PROSPECTING_MIN_READY_ITEMS - ready
                ),
            )
        )
    return out


# --------------------------------------------------------------------------
# 导出 line sheet
# --------------------------------------------------------------------------
def _tiers_for(row: B2BWholesaleItem) -> list[tuple[int, Decimal]]:
    """把存的阶梯价整理成 (起订量, 单价),按起订量升序。

    脏数据(缺字段/负数/不是数字)一律丢掉——图册是给买手看的,宁可少一行
    也不能印出个 `0+ : $0`。
    """
    out: list[tuple[int, Decimal]] = []
    for raw in row.price_tiers_json or []:
        if not isinstance(raw, dict):
            continue
        try:
            qty = int(raw.get("min_qty") or 0)
            price = Decimal(str(raw.get("unit_price")))
        except (TypeError, ValueError, ArithmeticError):
            continue
        if qty > 0 and price > 0:
            out.append((qty, price))
    return sorted(out)


def build_line_sheet_request(
    db: Session,
    *,
    payload: LineSheetExportRequest,
    image_dir: Path,
) -> LineSheetRequest:
    stmt = select(B2BWholesaleItem).where(
        B2BWholesaleItem.status != STATUS_ARCHIVED
    )
    if payload.item_ids:
        stmt = stmt.where(B2BWholesaleItem.id.in_(payload.item_ids))
    rows = list(db.scalars(stmt))
    if payload.store_type:
        # 图册以店型为单位出——一家礼品店该看到的是"所有我能卖给礼品店的货",
        # 横跨几个类目也一起给,而不是按类目切成好几本薄册子。
        from ..store_types import service as store_type_service

        prefixes = store_type_service.prefixes_for(db, payload.store_type)
        if not prefixes:
            raise WholesaleValidationError(
                f"店型 {payload.store_type} 还没挂类目，出不了图册。"
            )
        rows = [
            row
            for row in rows
            if store_type_service.matches_any_prefix(row.category_path, prefixes)
        ]
    if payload.category_prefix:
        rows = [
            row for row in rows if _matches_prefix(row, payload.category_prefix)
        ]
    if not payload.include_not_ready:
        rows = [row for row in rows if row.status == STATUS_READY]

    if not rows:
        raise WholesaleValidationError(
            "No wholesale-ready products match this selection. Fill in "
            "wholesale price, case pack, MOQ and lead time first."
        )

    incomplete = [row.sku for row in rows if not row.wholesale_fields_complete()]
    if incomplete:
        raise WholesaleValidationError(
            "These SKUs are missing wholesale data: "
            + ", ".join(sorted(incomplete)[:10])
        )

    items = [
        LineSheetItem(
            sku=row.sku,
            name=row.product_name,
            category_path=list(row.category_path or []),
            image_path=(
                _k_main_image_path(db, row.k_product_id)
                or _localise_image(row.image_url, image_dir, row.sku)
            ),
            wholesale_price=row.wholesale_price,
            msrp=row.msrp,
            case_pack=row.case_pack,
            moq_units=row.moq_units,
            lead_time_days=row.lead_time_days,
            variant_note=row.variant_note,
            price_tiers=_tiers_for(row),
        )
        for row in rows
    ]
    meta = LineSheetMeta(
        brand_name=BRAND_NAME,
        legal_entity=LEGAL_ENTITY,
        contact_email=CONTACT_EMAIL,
        contact_phone=CONTACT_PHONE,
        address_lines=list(ADDRESS_LINES),
        currency=DEFAULT_CURRENCY,
        edition_label=payload.edition_label or "",
        min_order_value=DEFAULT_MIN_ORDER_VALUE,
        payment_terms=DEFAULT_PAYMENT_TERMS,
        notes=list(line_sheet_notes()),
    )
    return LineSheetRequest(meta=meta, items=items)


def _k_main_image_path(db: Session, k_product_id: UUID | None) -> str | None:
    """取 K 的主图本地路径。

    K 的图存在磁盘上(K_PRODUCT_MEDIA_STORAGE_DIR),渲染器又正好只读本地文件,
    所以直接指过去——比下载一遍快得多,也不依赖外网。
    """
    if k_product_id is None:
        return None
    object_key = db.scalar(
        text(
            "SELECT object_key FROM k_product_knowledge_media_assets "
            "WHERE product_id = :pid AND asset_role = 'main' "
            "AND status = 'available' AND object_key IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"pid": k_product_id},
    )
    if not object_key:
        return None
    root = Path(
        os.getenv("K_PRODUCT_MEDIA_STORAGE_DIR", "/var/lib/barong/k-media")
    )
    candidate = root / str(object_key)
    return str(candidate) if candidate.exists() else None


def _localise_image(
    image_url: str | None,
    image_dir: Path,
    sku: str,
) -> str | None:
    """渲染器只读本地文件,所以下载这一步归调用方。

    下载失败不抛异常——渲染器对缺图会画占位框,为一张图挂掉整份图册
    不值得。
    """
    if not image_url:
        return None
    parsed = urlparse(image_url)
    if parsed.scheme in ("", "file"):
        candidate = Path(parsed.path or image_url)
        return str(candidate) if candidate.exists() else None
    if parsed.scheme not in ("http", "https"):
        return None

    suffix = Path(parsed.path).suffix or ".img"
    safe_sku = "".join(ch for ch in sku if ch.isalnum() or ch in "-_") or "item"
    target = image_dir / f"{safe_sku}{suffix}"
    try:
        request = urllib.request.Request(
            image_url,
            headers={"User-Agent": "barong-ops-console/b2b-linesheet"},
        )
        with urllib.request.urlopen(
            request,
            timeout=IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
        ) as response:
            target.write_bytes(response.read())
    except Exception:
        return None
    return str(target)


def make_image_dir() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix="b2b-linesheet-")
