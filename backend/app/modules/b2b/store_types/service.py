"""店型层的业务规则。

两条硬规则:
1. **一次只允许 N 个店型在跑**(默认 1)。这不是技术限制,是保护用户——他一个
   人处理回复,同时在跟的对话必须恒定,否则类目一多他本人就是瓶颈。
2. **图册不够厚不许开跑**。沿用用户定的 30 个品门槛,但从"按类目"改成
   "按店型"算——决定一封开发信值不值得发的是"我能给这家店看多少货",
   而一个店型往往横跨好几个类目。
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..prospects.models import (
    PROSPECT_STATUS_APPROVED,
    PROSPECT_STATUS_NEW,
    B2BProspect,
    B2BProspectQuery,
)
from ..wholesale.models import STATUS_ARCHIVED, STATUS_READY, B2BWholesaleItem
from ..wholesale.schemas import CATEGORY_PROSPECTING_MIN_READY_ITEMS
from . import catalog
from .models import (
    OUTREACH_ACTIVE,
    B2BStoreType,
    B2BStoreTypeCategory,
)
from .schemas import (
    StoreTypeCategoryRead,
    StoreTypeCreate,
    StoreTypePatch,
    StoreTypeRead,
)

DEFAULT_MAX_ACTIVE_STORE_TYPES = 1
# 自动建出来多久之内算「新」——界面靠它提示用户上架带出了新店型。
NEWLY_ADDED_WINDOW = timedelta(days=7)


class StoreTypeError(ValueError):
    """人能看懂的错误,直接冒到界面上。"""


def max_active_store_types() -> int:
    """同时在跑的店型上限。想加速把环境变量调大,默认死守 1。"""
    raw = os.getenv("B2B_MAX_ACTIVE_STORE_TYPES", "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ACTIVE_STORE_TYPES
    return max(1, value)


def category_key(prefix: list[str]) -> str:
    """类目前缀的规范化字符串形式,只用于唯一约束和比对。

    Postgres 的 json 类型没有相等运算符,进不了 UNIQUE 索引,所以另存一列。
    """
    return " > ".join(str(part).strip() for part in prefix if str(part).strip())


def matches_any_prefix(path: list[str] | None, prefixes: list[list[str]]) -> bool:
    """产品类目路径是否落在任一前缀之下。空前缀列表 = 谁都不匹配。"""
    actual = list(path or [])
    for prefix in prefixes:
        if prefix and actual[: len(prefix)] == prefix:
            return True
    return False


# --------------------------------------------------------------------------
# 读
# --------------------------------------------------------------------------


def _get_by_key(db: Session, key: str) -> B2BStoreType:
    row = db.scalar(select(B2BStoreType).where(B2BStoreType.key == key))
    if row is None:
        raise StoreTypeError(f"没有这个店型：{key}")
    return row


def prefixes_for(db: Session, store_type_key: str) -> list[list[str]]:
    """一个店型能拿到哪些类目前缀。"""
    row = _get_by_key(db, store_type_key)
    rows = db.scalars(
        select(B2BStoreTypeCategory).where(
            B2BStoreTypeCategory.store_type_id == row.id
        )
    )
    return [list(entry.category_prefix or []) for entry in rows]


def active_store_type_keys(db: Session) -> list[str]:
    rows = db.scalars(
        select(B2BStoreType)
        .where(B2BStoreType.outreach_status == OUTREACH_ACTIVE)
        .order_by(B2BStoreType.sort_order, B2BStoreType.key)
    )
    return [row.key for row in rows]


def list_store_types(db: Session) -> list[StoreTypeRead]:
    """店型清单,带图册成熟度和客户漏斗计数。"""
    types = list(
        db.scalars(
            select(B2BStoreType).order_by(
                B2BStoreType.sort_order, B2BStoreType.label
            )
        )
    )
    if not types:
        return []

    by_id = {row.id: row for row in types}
    prefixes: dict[UUID, list[list[str]]] = defaultdict(list)
    categories: dict[UUID, list[StoreTypeCategoryRead]] = defaultdict(list)
    for link in db.scalars(select(B2BStoreTypeCategory)):
        if link.store_type_id not in by_id:
            continue
        prefix = list(link.category_prefix or [])
        prefixes[link.store_type_id].append(prefix)
        categories[link.store_type_id].append(
            StoreTypeCategoryRead(id=link.id, category_prefix=prefix)
        )

    items = [
        item
        for item in db.scalars(select(B2BWholesaleItem))
        if item.status != STATUS_ARCHIVED
    ]

    prospect_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"new": 0, "approved": 0}
    )
    for prospect in db.scalars(select(B2BProspect)):
        bucket = prospect_counts[prospect.store_type]
        if prospect.status == PROSPECT_STATUS_NEW:
            bucket["new"] += 1
        elif prospect.status == PROSPECT_STATUS_APPROVED:
            bucket["approved"] += 1

    out: list[StoreTypeRead] = []
    for row in types:
        own = prefixes.get(row.id, [])
        matched = [
            item for item in items if matches_any_prefix(item.category_path, own)
        ]
        ready = sum(1 for item in matched if item.status == STATUS_READY)
        counts = prospect_counts.get(row.key, {"new": 0, "approved": 0})
        out.append(
            StoreTypeRead(
                id=row.id,
                key=row.key,
                label=row.label,
                outreach_status=row.outreach_status,
                sort_order=row.sort_order,
                notes=row.notes,
                categories=sorted(
                    categories.get(row.id, []),
                    key=lambda entry: entry.category_prefix,
                ),
                total_items=len(matched),
                ready_items=ready,
                prospecting_unlocked=(
                    ready >= CATEGORY_PROSPECTING_MIN_READY_ITEMS
                ),
                shortfall=max(0, CATEGORY_PROSPECTING_MIN_READY_ITEMS - ready),
                prospects_new=counts["new"],
                prospects_approved=counts["approved"],
                newly_added=_is_newly_added(row),
            )
        )
    return out


# --------------------------------------------------------------------------
# 写
# --------------------------------------------------------------------------


def _is_newly_added(row: B2BStoreType) -> bool:
    created = row.created_at
    if created is None:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created) <= NEWLY_ADDED_WINDOW


def create_store_type(db: Session, *, payload: StoreTypeCreate) -> B2BStoreType:
    existing = db.scalar(
        select(B2BStoreType).where(B2BStoreType.key == payload.key)
    )
    if existing is not None:
        raise StoreTypeError(f"店型 {payload.key} 已经存在了。")
    row = B2BStoreType(
        key=payload.key,
        label=payload.label,
        notes=payload.notes,
        sort_order=payload.sort_order,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def patch_store_type(
    db: Session,
    *,
    key: str,
    patch: StoreTypePatch,
) -> B2BStoreType:
    row = _get_by_key(db, key)
    status = patch.validated_status()

    if status == OUTREACH_ACTIVE and row.outreach_status != OUTREACH_ACTIVE:
        _guard_activation(db, row)

    if patch.label is not None:
        row.label = patch.label
    if patch.notes is not None:
        row.notes = patch.notes
    if patch.sort_order is not None:
        row.sort_order = patch.sort_order
    if status is not None:
        row.outreach_status = status

    db.commit()
    db.refresh(row)
    return row


def _guard_activation(db: Session, row: B2BStoreType) -> None:
    """开跑前的两道门:图册够厚 + 没超过同时在跑的上限。"""
    prefixes = db.scalars(
        select(B2BStoreTypeCategory).where(
            B2BStoreTypeCategory.store_type_id == row.id
        )
    )
    own = [list(link.category_prefix or []) for link in prefixes]
    if not own:
        raise StoreTypeError(
            f"「{row.label}」还没挂类目,不知道能给这类店看什么货。先挂类目。"
        )

    ready = sum(
        1
        for item in db.scalars(select(B2BWholesaleItem))
        if item.status == STATUS_READY
        and matches_any_prefix(item.category_path, own)
    )
    if ready < CATEGORY_PROSPECTING_MIN_READY_ITEMS:
        raise StoreTypeError(
            f"「{row.label}」只有 {ready} 个填全批发价的品，"
            f"不足 {CATEGORY_PROSPECTING_MIN_READY_ITEMS} 个。"
            "图册太薄，发出去等于浪费一次机会。"
        )

    limit = max_active_store_types()
    active = [
        other
        for other in db.scalars(
            select(B2BStoreType).where(
                B2BStoreType.outreach_status == OUTREACH_ACTIVE
            )
        )
        if other.id != row.id
    ]
    if len(active) >= limit:
        names = "、".join(other.label for other in active)
        raise StoreTypeError(
            f"已经有 {len(active)} 个店型在跑（{names}）。"
            "先把在跑的停掉再开新的——同时开几条线，回复你一个人接不住。"
        )


def delete_store_type(db: Session, *, key: str) -> None:
    row = _get_by_key(db, key)
    if row.outreach_status == OUTREACH_ACTIVE:
        raise StoreTypeError(f"「{row.label}」正在跑,先停掉再删。")
    db.execute(
        delete(B2BStoreTypeCategory).where(
            B2BStoreTypeCategory.store_type_id == row.id
        )
    )
    db.delete(row)
    db.commit()


def add_category(
    db: Session,
    *,
    key: str,
    category_prefix: list[str],
) -> B2BStoreTypeCategory:
    row = _get_by_key(db, key)
    cleaned = [str(part).strip() for part in category_prefix if str(part).strip()]
    if not cleaned:
        raise StoreTypeError("类目前缀不能为空。")
    normalized = category_key(cleaned)
    existing = db.scalar(
        select(B2BStoreTypeCategory)
        .where(B2BStoreTypeCategory.store_type_id == row.id)
        .where(B2BStoreTypeCategory.category_key == normalized)
    )
    if existing is not None:
        return existing
    link = B2BStoreTypeCategory(
        store_type_id=row.id,
        category_prefix=cleaned,
        category_key=normalized,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def remove_category(db: Session, *, key: str, category_id: UUID) -> None:
    row = _get_by_key(db, key)
    db.execute(
        delete(B2BStoreTypeCategory)
        .where(B2BStoreTypeCategory.store_type_id == row.id)
        .where(B2BStoreTypeCategory.id == category_id)
    )
    db.commit()


# --------------------------------------------------------------------------
# 自动落位:上架一款产品就把它该进的店型建出来
# --------------------------------------------------------------------------


def ensure_store_types_for_category(
    db: Session,
    *,
    category_path: list[str] | None,
    commit: bool = True,
) -> list[str]:
    """按内置目录把产品类目落进店型,返回**这次新建出来的**店型 key。

    用户拍板(2026-07-28):"即使新增加类目,我可能也不知道这个类目应该对应什么
    店型……希望自动一些"。所以映射写死在 catalog.py 里,上架即落位,他不用判断。

    店型第一次被用到时才建出来(界面上就不会挂一堆空壳),建的时候把它在目录里
    的**全部**类目前缀一次挂齐——以后同店型的新品自动进来,不用再回来补。
    """
    specs = catalog.store_types_for_category(category_path)
    if not specs:
        return []

    created: list[str] = []
    for spec in specs:
        row = db.scalar(select(B2BStoreType).where(B2BStoreType.key == spec["key"]))
        if row is None:
            row = B2BStoreType(
                key=spec["key"],
                label=spec["label"],
                sort_order=spec["sort_order"],
            )
            db.add(row)
            db.flush()
            created.append(spec["key"])

        existing_keys = {
            link.category_key
            for link in db.scalars(
                select(B2BStoreTypeCategory).where(
                    B2BStoreTypeCategory.store_type_id == row.id
                )
            )
        }
        for prefix in spec["prefixes"]:
            normalized = category_key(list(prefix))
            if normalized in existing_keys:
                continue
            db.add(
                B2BStoreTypeCategory(
                    store_type_id=row.id,
                    category_prefix=list(prefix),
                    category_key=normalized,
                )
            )
            existing_keys.add(normalized)
        # session 是 autoflush=False 的:不 flush 的话,下一个产品跑到这里时
        # 上面刚 add 的行还看不见,查重扑空 → 重复插入 → 撞唯一键炸整批。
        # (回灌 6 个产品时真炸过一次。)
        db.flush()

        _ensure_prospect_queries(db, spec)

    if commit:
        db.commit()
    return created


def _ensure_prospect_queries(db: Session, spec: catalog.StoreTypeSpec) -> None:
    """新店型要能立刻拿去挖客户,搜索词模板得跟着建。

    英文模板给 US/CA,西班牙语给 MX——发信语言跟着模板走,不是跟着国家猜。
    """
    wanted: list[tuple[str, str, str]] = []
    for template in spec["queries_en"]:
        wanted.append(("US", "en", template))
        wanted.append(("CA", "en", template))
    for template in spec["queries_es"]:
        wanted.append(("MX", "es", template))

    for country, language, template in wanted:
        exists = db.scalar(
            select(B2BProspectQuery)
            .where(B2BProspectQuery.store_type == spec["key"])
            .where(B2BProspectQuery.country == country)
            .where(B2BProspectQuery.query_template == template)
        )
        if exists is not None:
            continue
        db.add(
            B2BProspectQuery(
                store_type=spec["key"],
                store_type_label=spec["label"],
                country=country,
                language=language,
                query_template=template,
            )
        )
        # 同上:autoflush=False,不 flush 下一轮查重就看不见这一行。
        db.flush()
