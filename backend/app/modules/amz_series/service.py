"""A0 服务层:店铺清单、授权行、种子导入台账、按店汇总。所有函数不 commit(router / CLI 统一收尾)。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models.user import User
from .constants import STORE_ROLES
from .models import AmzAdSearchTerm, AmzSeedImport, AmzStore, AmzStoreGrant, AmzTransaction


class AmzServiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400, code: str = "amz_error") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class StoreSummary:
    store: AmzStore
    role: str
    ads_spend: Decimal
    ads_sales: Decimal
    ads_orders: int
    ads_first_date: date | None
    ads_last_date: date | None
    txn_rows: int
    txn_first_at: str | None
    txn_last_at: str | None
    ads_spend_usd: Decimal = Decimal(0)
    ads_sales_usd: Decimal = Decimal(0)
    fx_latest: tuple[str, float] | None = None


def list_visible_stores(db: Session, *, store_codes: list[str] | None) -> list[AmzStore]:
    query = select(AmzStore).where(AmzStore.status == "active").order_by(AmzStore.store_code)
    if store_codes is not None:
        if not store_codes:
            return []
        query = query.where(AmzStore.store_code.in_(store_codes))
    return list(db.scalars(query))


def grant_role_for(db: Session, *, user: User, store_code: str, is_owner: bool) -> str:
    if is_owner:
        return "grant"
    grant = db.get(AmzStoreGrant, (int(user.id), store_code))
    return grant.role if grant is not None else ""


def store_summaries(db: Session, *, stores: list[AmzStore], user: User, is_owner: bool) -> list[StoreSummary]:
    codes = [store.store_code for store in stores]
    if not codes:
        return []
    ads_rows = db.execute(
        select(
            AmzAdSearchTerm.store_code,
            func.coalesce(func.sum(AmzAdSearchTerm.spend), 0),
            func.coalesce(func.sum(AmzAdSearchTerm.sales_7d), 0),
            func.coalesce(func.sum(AmzAdSearchTerm.orders_7d), 0),
            func.min(AmzAdSearchTerm.report_date),
            func.max(AmzAdSearchTerm.report_date),
        )
        .where(AmzAdSearchTerm.store_code.in_(codes))
        .group_by(AmzAdSearchTerm.store_code)
    ).all()
    ads_by_store = {row[0]: row for row in ads_rows}
    # 美元口径:按天、按当天汇率折(欧元店)。
    from . import fx  # noqa: PLC0415

    fx_cache: dict = {}
    usd_by_store: dict[str, list[Decimal]] = {}
    for store_code, day, currency, spend, sales in db.execute(
        select(AmzAdSearchTerm.store_code, AmzAdSearchTerm.report_date, AmzAdSearchTerm.currency, func.sum(AmzAdSearchTerm.spend), func.sum(AmzAdSearchTerm.sales_7d))
        .where(AmzAdSearchTerm.store_code.in_(codes))
        .group_by(AmzAdSearchTerm.store_code, AmzAdSearchTerm.report_date, AmzAdSearchTerm.currency)
    ).all():
        factor = fx.usd_factor(db, currency, cache=fx_cache)(day)
        bucket = usd_by_store.setdefault(store_code, [Decimal(0), Decimal(0)])
        bucket[0] += Decimal(spend or 0) * factor
        bucket[1] += Decimal(sales or 0) * factor
    latest = fx.latest_rate(db)
    txn_rows = db.execute(
        select(
            AmzTransaction.store_code,
            func.count(AmzTransaction.id),
            func.min(AmzTransaction.posted_at),
            func.max(AmzTransaction.posted_at),
        )
        .where(AmzTransaction.store_code.in_(codes))
        .group_by(AmzTransaction.store_code)
    ).all()
    txn_by_store = {row[0]: row for row in txn_rows}
    summaries: list[StoreSummary] = []
    for store in stores:
        ads = ads_by_store.get(store.store_code)
        txn = txn_by_store.get(store.store_code)
        summaries.append(
            StoreSummary(
                store=store,
                role=grant_role_for(db, user=user, store_code=store.store_code, is_owner=is_owner),
                ads_spend=Decimal(ads[1]) if ads else Decimal(0),
                ads_sales=Decimal(ads[2]) if ads else Decimal(0),
                ads_orders=int(ads[3]) if ads else 0,
                ads_first_date=ads[4] if ads else None,
                ads_last_date=ads[5] if ads else None,
                txn_rows=int(txn[1]) if txn else 0,
                txn_first_at=txn[2].isoformat() if txn and txn[2] else None,
                txn_last_at=txn[3].isoformat() if txn and txn[3] else None,
                ads_spend_usd=usd_by_store.get(store.store_code, [Decimal(0), Decimal(0)])[0],
                ads_sales_usd=usd_by_store.get(store.store_code, [Decimal(0), Decimal(0)])[1],
                fx_latest=(latest[0].isoformat(), float(latest[1])) if latest and store.currency != "USD" else None,
            )
        )
    return summaries


def list_grants(db: Session, *, store_code: str) -> list[AmzStoreGrant]:
    return list(
        db.scalars(
            select(AmzStoreGrant).where(AmzStoreGrant.store_code == store_code).order_by(AmzStoreGrant.user_id)
        )
    )


def upsert_grant(
    db: Session,
    *,
    store_code: str,
    user_id: int,
    role: str,
    granted_by: User,
) -> AmzStoreGrant:
    if role not in STORE_ROLES:
        raise AmzServiceError(f"unknown role: {role}", status_code=422, code="amz_role_invalid")
    target = db.get(User, user_id)
    if target is None or not target.is_active:
        raise AmzServiceError("user not found or inactive", status_code=404, code="amz_user_not_found")
    grant = db.get(AmzStoreGrant, (user_id, store_code))
    if grant is None:
        grant = AmzStoreGrant(user_id=user_id, store_code=store_code, role=role, granted_by_user_id=int(granted_by.id))
        db.add(grant)
    else:
        grant.role = role
        grant.granted_by_user_id = int(granted_by.id)
        db.add(grant)
    db.flush()
    return grant


def delete_grant(db: Session, *, store_code: str, user_id: int) -> bool:
    grant = db.get(AmzStoreGrant, (user_id, store_code))
    if grant is None:
        return False
    db.delete(grant)
    db.flush()
    return True


def list_seed_imports(db: Session, *, store_codes: list[str] | None) -> list[AmzSeedImport]:
    query = select(AmzSeedImport).order_by(AmzSeedImport.imported_at.desc())
    if store_codes is not None:
        if not store_codes:
            return []
        query = query.where(AmzSeedImport.store_code.in_(store_codes))
    return list(db.scalars(query.limit(200)))


def summary_view(item: StoreSummary) -> dict[str, Any]:
    store = item.store
    spend = item.ads_spend
    sales = item.ads_sales
    acos = float(spend / sales * 100) if sales else None
    return {
        "store_code": store.store_code,
        "display_name": store.display_name,
        "company_org_id": store.company_org_id,
        "company_name": store.company_name,
        "marketplace_id": store.marketplace_id,
        "region": store.region,
        "country": store.country,
        "currency": store.currency,
        "timezone": store.timezone,
        "egress_ip": store.egress_ip,
        "user_agent": store.user_agent,
        "status": store.status,
        "role": item.role,
        "ads": {
            "spend": float(spend),
            "sales": float(sales),
            "orders": item.ads_orders,
            "acos_pct": round(acos, 1) if acos is not None else None,
            "first_date": item.ads_first_date.isoformat() if item.ads_first_date else None,
            "last_date": item.ads_last_date.isoformat() if item.ads_last_date else None,
            "spend_usd": round(float(item.ads_spend_usd), 2),
            "sales_usd": round(float(item.ads_sales_usd), 2),
        },
        "fx_latest": {"date": item.fx_latest[0], "rate": item.fx_latest[1]} if item.fx_latest else None,
        "transactions": {
            "rows": item.txn_rows,
            "first_at": item.txn_first_at,
            "last_at": item.txn_last_at,
        },
    }


__all__ = [
    "AmzServiceError",
    "StoreSummary",
    "delete_grant",
    "grant_role_for",
    "list_grants",
    "list_seed_imports",
    "list_visible_stores",
    "store_summaries",
    "summary_view",
    "upsert_grant",
]
