from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.roles import is_owner_role
from ...db.session import get_db
from ...models.org_membership import OrgMembershipRecord
from ...models.organization import OrganizationRecord
from ...models.user import User
from ...services.data_isolation import without_org_data_isolation
from ...services.rw_keepa_ingestion import keepa_ingestion_runtime_status
from ..deps import get_current_user


router = APIRouter(prefix="/rw", tags=["r-warehouse"])

R_SERIES_TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"

MOCK_PRODUCTS = [
    {
        "asin": "B033B3F98C",
        "title": "Portable Door Draft Stopper",
        "category": "Home & Kitchen",
        "price": 34.99,
        "bsr": 8421,
        "reviews": 214,
        "seller_count": 7,
        "state": "rule_passed",
        "rule_result": "rule_passed",
        "margin": 0.4928,
        "source": "mock_keepa",
    }
]

RULES = [
    {
        "id": "price_band_filter",
        "label": "price band filter",
        "enabled": True,
        "result": "passed",
        "threshold": "25 <= price <= 70",
    },
    {
        "id": "margin_check",
        "label": "margin check",
        "enabled": True,
        "result": "passed",
        "threshold": "est_net_margin >= 0.15",
    },
    {
        "id": "competition_filter",
        "label": "competition filter",
        "enabled": True,
        "result": "passed",
        "threshold": "seller_count <= 15",
    },
    {
        "id": "brand_dominance_filter",
        "label": "brand dominance filter",
        "enabled": True,
        "result": "passed",
        "threshold": "brand_share <= 0.50",
    },
    {
        "id": "price_trend_filter",
        "label": "price trend filter",
        "enabled": True,
        "result": "passed",
        "threshold": "price_trend not declining",
    },
]


def _user_has_target_org_access(db: Session, user: User) -> bool:
    return _target_org_for_user(db, user) is not None


def _target_org_for_user(db: Session, user: User) -> OrganizationRecord | None:
    if is_owner_role(user.role):
        with without_org_data_isolation():
            return db.scalar(
                select(OrganizationRecord)
                .where(
                    OrganizationRecord.org_name == R_SERIES_TARGET_ORGANIZATION_NAME,
                    OrganizationRecord.status != "deleted",
                )
                .order_by(OrganizationRecord.org_id)
                .limit(1)
            )

    org_ids: set[str] = set()
    if user.organization_id:
        org_ids.add(user.organization_id)

    with without_org_data_isolation():
        membership_org_ids = db.scalars(
            select(OrgMembershipRecord.org_id).where(
                OrgMembershipRecord.user_id == str(user.id),
                OrgMembershipRecord.status == "active",
            )
        )
        org_ids.update(membership_org_ids)

        if not org_ids:
            return None

        return db.scalar(
            select(OrganizationRecord)
            .where(
                OrganizationRecord.org_id.in_(org_ids),
                OrganizationRecord.org_name == R_SERIES_TARGET_ORGANIZATION_NAME,
                OrganizationRecord.status != "deleted",
            )
            .order_by(OrganizationRecord.org_id)
            .limit(1)
        )


def require_r_series_org(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    if not _user_has_target_org_access(db, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="R-series modules are bound to the target organization only.",
        )
    return user


@router.get("/status")
def rw_status(
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _target_org_for_user(db, user)
    if target_org is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="R-series modules are bound to the target organization only.",
        )
    with without_org_data_isolation():
        ingestion_status = keepa_ingestion_runtime_status(
            db,
            org_id=target_org.org_id,
        )
    keepa_bound = ingestion_status["keepa_key_bound"] is True
    return {
        "module": "R-W",
        "active": True,
        "mode": "keepa_key_bound" if keepa_bound else "mock_mode",
        "mock_mode_active": not keepa_bound,
        "waiting_for_keys": not keepa_bound,
        "real_keepa_api_used": False,
        "keepa_key_bound": keepa_bound,
        "ingestion_service_ready": ingestion_status["ingestion_service_ready"],
        "adapter": ingestion_status["adapter"],
        "organization": R_SERIES_TARGET_ORGANIZATION_NAME,
        "pipeline": ingestion_status.get(
            "pipeline",
            "Keepa API -> ingestion service -> product DB",
        ),
        "endpoints": [
            "/api/rw/products",
            "/api/rw/status",
            "/api/rw/rules",
            "/api/rw/ingestion/status",
        ],
    }


@router.get("/ingestion/status")
def rw_ingestion_status(
    db: Session = Depends(get_db),
    user: User = Depends(require_r_series_org),
) -> dict[str, object]:
    target_org = _target_org_for_user(db, user)
    if target_org is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="R-series modules are bound to the target organization only.",
        )
    with without_org_data_isolation():
        ingestion_status = keepa_ingestion_runtime_status(
            db,
            org_id=target_org.org_id,
        )
    return {
        "module": "R-W",
        "organization": R_SERIES_TARGET_ORGANIZATION_NAME,
        **ingestion_status,
    }


@router.get("/products")
def rw_products(user: User = Depends(require_r_series_org)) -> dict[str, object]:
    del user
    return {
        "items": MOCK_PRODUCTS,
        "count": len(MOCK_PRODUCTS),
        "mode": "mock_mode",
        "organization": R_SERIES_TARGET_ORGANIZATION_NAME,
    }


@router.get("/rules")
def rw_rules(user: User = Depends(require_r_series_org)) -> dict[str, object]:
    del user
    return {
        "items": RULES,
        "count": len(RULES),
        "enabled": True,
        "mode": "mock_mode",
    }
