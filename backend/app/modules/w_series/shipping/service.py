"""Database services for W-A shipping-class registry and assignment."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from ....models import KProductKnowledgeProduct
from ...p_series.upload.models import PUploadJob
from . import engine
from .models import WShippingClass, WShippingRule


def list_shipping_classes(db: Session) -> list[WShippingClass]:
    """Return the complete registry, including inactive classes."""

    return list(
        db.scalars(
            select(WShippingClass).order_by(
                WShippingClass.sort_order.asc(),
                WShippingClass.name.asc(),
                WShippingClass.slug.asc(),
            )
        ).all()
    )


def get_shipping_class(db: Session, class_id: UUID) -> WShippingClass | None:
    return db.get(WShippingClass, class_id)


def get_shipping_class_by_slug(
    db: Session,
    slug: str,
) -> WShippingClass | None:
    return db.scalar(select(WShippingClass).where(WShippingClass.slug == slug))


def create_shipping_class(
    db: Session,
    *,
    slug: str,
    name: str,
    origin: str,
    notes: str | None,
    sort_order: int,
) -> WShippingClass:
    normalized_slug = slug.strip()
    if get_shipping_class_by_slug(db, normalized_slug) is not None:
        raise ValueError("运费模板 slug 已存在。")
    row = WShippingClass(
        slug=normalized_slug,
        name=name.strip(),
        origin=origin,
        notes=notes,
        active=True,
        sort_order=sort_order,
    )
    db.add(row)
    db.flush()
    return row


def update_shipping_class(
    row: WShippingClass,
    changes: dict[str, Any],
) -> WShippingClass:
    for field in ("name", "origin", "notes", "active", "sort_order"):
        if field in changes:
            value = changes[field]
            if field == "name" and isinstance(value, str):
                value = value.strip()
            setattr(row, field, value)
    return row


def list_shipping_rules(
    db: Session,
    *,
    active_only: bool = False,
) -> list[WShippingRule]:
    query = select(WShippingRule)
    if active_only:
        query = query.where(WShippingRule.active.is_(True))
    return list(
        db.scalars(
            query.order_by(WShippingRule.priority.asc(), WShippingRule.id.asc())
        ).all()
    )


def get_shipping_rule(db: Session, rule_id: UUID) -> WShippingRule | None:
    return db.get(WShippingRule, rule_id)


def _require_shipping_class_slug(db: Session, slug: str) -> str:
    normalized = slug.strip()
    if get_shipping_class_by_slug(db, normalized) is None:
        raise ValueError("运费模板不存在。")
    return normalized


def create_shipping_rule(
    db: Session,
    *,
    priority: int,
    rule_type: str,
    min_weight_kg: Decimal | None,
    max_weight_kg: Decimal | None,
    shipping_class_slug: str,
    active: bool,
    notes: str | None,
) -> WShippingRule:
    row = WShippingRule(
        priority=priority,
        rule_type=rule_type,
        min_weight_kg=min_weight_kg,
        max_weight_kg=max_weight_kg,
        shipping_class_slug=_require_shipping_class_slug(
            db,
            shipping_class_slug,
        ),
        active=active,
        notes=notes,
    )
    db.add(row)
    db.flush()
    return row


def update_shipping_rule(
    db: Session,
    row: WShippingRule,
    changes: dict[str, Any],
) -> WShippingRule:
    if "shipping_class_slug" in changes:
        changes["shipping_class_slug"] = _require_shipping_class_slug(
            db,
            str(changes["shipping_class_slug"]),
        )
    for field in (
        "priority",
        "min_weight_kg",
        "max_weight_kg",
        "shipping_class_slug",
        "active",
        "notes",
    ):
        if field in changes:
            setattr(row, field, changes[field])
    return row


def delete_shipping_rule(db: Session, row: WShippingRule) -> None:
    db.delete(row)


def simulate(
    db: Session,
    *,
    weight_kg: Decimal | None,
    volumetric_kg: Decimal | None,
    contains_battery: bool,
    us_stock: bool,
) -> engine.ShippingDecision:
    return engine.evaluate_rules(
        list_shipping_rules(db, active_only=True),
        weight_kg=weight_kg,
        volumetric_kg=volumetric_kg,
        contains_battery=contains_battery,
        us_stock=us_stock,
    )


def assign_one(
    db: Session,
    product: KProductKnowledgeProduct,
    *,
    force: bool = False,
) -> engine.ShippingDecision:
    return engine.assign_product(
        product,
        list_shipping_rules(db, active_only=True),
        force=force,
    )


def assign_all_dtc(db: Session) -> dict[str, int]:
    """Recalculate every DTC product, committing each batch of 50 products."""

    rules = list_shipping_rules(db, active_only=True)
    products = list(
        db.scalars(
            select(KProductKnowledgeProduct)
            .where(KProductKnowledgeProduct.channel == "dtc")
            .order_by(KProductKnowledgeProduct.id.asc())
        ).all()
    )
    stats = {
        "assigned": 0,
        "review_needed": 0,
        "skipped_manual": 0,
        "unresolved": 0,
    }
    for index, product in enumerate(products, start=1):
        decision = engine.assign_product(product, rules)
        if decision.skipped_manual:
            stats["skipped_manual"] += 1
        else:
            if decision.shipping_class_slug is None:
                stats["unresolved"] += 1
            else:
                stats["assigned"] += 1
            if decision.review_needed:
                stats["review_needed"] += 1
        if index % 50 == 0:
            db.commit()
    if products and len(products) % 50:
        db.commit()
    return stats


def _unassigned_condition():
    return or_(
        KProductKnowledgeProduct.shipping_class.is_(None),
        func.trim(KProductKnowledgeProduct.shipping_class) == "",
    )


def _exported_condition():
    return exists(
        select(PUploadJob.id).where(
            PUploadJob.product_id == KProductKnowledgeProduct.id,
            PUploadJob.status == "success",
        )
    )


def shipping_board(
    db: Session,
    *,
    filter_name: str,
    limit: int,
) -> dict[str, Any]:
    dtc = KProductKnowledgeProduct.channel == "dtc"
    unassigned = _unassigned_condition()
    exported = _exported_condition()

    total_dtc = int(
        db.scalar(
            select(func.count())
            .select_from(KProductKnowledgeProduct)
            .where(dtc)
        )
        or 0
    )
    unassigned_count = int(
        db.scalar(
            select(func.count())
            .select_from(KProductKnowledgeProduct)
            .where(dtc, unassigned)
        )
        or 0
    )
    review_count = int(
        db.scalar(
            select(func.count())
            .select_from(KProductKnowledgeProduct)
            .where(dtc, KProductKnowledgeProduct.shipping_review_needed.is_(True))
        )
        or 0
    )
    exported_missing_count = int(
        db.scalar(
            select(func.count())
            .select_from(KProductKnowledgeProduct)
            .where(dtc, unassigned, exported)
        )
        or 0
    )

    query = select(KProductKnowledgeProduct).where(dtc)
    if filter_name == "unassigned":
        query = query.where(unassigned)
    elif filter_name == "review":
        query = query.where(
            KProductKnowledgeProduct.shipping_review_needed.is_(True)
        )
    elif filter_name == "exported_missing":
        query = query.where(unassigned, exported)
    products = list(
        db.scalars(
            query.order_by(
                KProductKnowledgeProduct.updated_at.desc(),
                KProductKnowledgeProduct.id.asc(),
            ).limit(limit)
        ).all()
    )

    product_ids = [product.id for product in products]
    exported_ids: set[str] = set()
    if product_ids:
        exported_ids = {
            str(product_id)
            for product_id in db.scalars(
                select(PUploadJob.product_id)
                .where(
                    PUploadJob.product_id.in_(product_ids),
                    PUploadJob.status == "success",
                )
                .distinct()
            ).all()
        }
    class_names = {
        row.slug: row.name
        for row in db.scalars(select(WShippingClass)).all()
    }

    items: list[dict[str, Any]] = []
    for product in products:
        weight, volumetric, used = engine.product_billing_weights(product)
        slug = (product.shipping_class or "").strip() or None
        assignment = product.shipping_assignment_json
        items.append(
            {
                "product_id": str(product.id),
                "product_name": product.product_name_en,
                "sku": product.sku,
                "channel": product.channel,
                "weight_kg": weight,
                "volumetric_kg": volumetric,
                "used_kg": used,
                "contains_battery": bool(product.contains_battery),
                "us_stock": bool(product.us_stock),
                "shipping_class_slug": slug,
                "shipping_class_name": class_names.get(slug) if slug else None,
                "assignment": assignment if isinstance(assignment, dict) else None,
                "review_needed": bool(product.shipping_review_needed),
                "exported": str(product.id) in exported_ids,
            }
        )
    return {
        "summary": {
            "total_dtc": total_dtc,
            "assigned": total_dtc - unassigned_count,
            "unassigned": unassigned_count,
            "review_needed": review_count,
            "exported_missing": exported_missing_count,
        },
        "items": items,
    }


def manually_update_product(
    db: Session,
    product: KProductKnowledgeProduct,
    *,
    shipping_class_present: bool,
    shipping_class_slug: str | None,
    contains_battery_present: bool,
    contains_battery: bool | None,
    us_stock_present: bool,
    us_stock: bool | None,
    clear_review: bool,
) -> KProductKnowledgeProduct:
    """Apply operator fields without automatically invoking the rule engine."""

    if contains_battery_present and contains_battery is not None:
        product.contains_battery = contains_battery
    if us_stock_present and us_stock is not None:
        product.us_stock = us_stock
    if shipping_class_present:
        normalized_slug = (shipping_class_slug or "").strip() or None
        if normalized_slug is not None:
            _require_shipping_class_slug(db, normalized_slug)
        product.shipping_class = normalized_slug
        if normalized_slug is None:
            product.shipping_assignment_json = None
        else:
            weight, volumetric, used = engine.product_billing_weights(product)
            product.shipping_assignment_json = {
                "rule_id": None,
                "rule_type": "manual",
                "matched_at": datetime.now(timezone.utc).isoformat(),
                "weight_kg": weight,
                "volumetric_kg": volumetric,
                "used_kg": used,
                "review_reason": None,
            }
    if clear_review:
        product.shipping_review_needed = False
    return product
