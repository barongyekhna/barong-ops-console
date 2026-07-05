"""Feature extraction for normalized Warehouse products."""

from __future__ import annotations

from r_system_v2.rw.core.models import KeepaProductData, NormalizedProduct, ProductState
from r_system_v2.rw.processor.monthly_sales_estimator import estimate_monthly_sales


def _category_id(category: str) -> str:
    normalized = category.strip().lower().replace("&", "and")
    return "-".join(part for part in normalized.replace(",", " ").split() if part)


def extract_product_features(source_query: str, keepa_data: KeepaProductData) -> NormalizedProduct:
    """Convert Keepa provider output into the normalized product schema.

    The production Keepa payload does not contain the seller's actual landed
    cost. When landed cost is missing, margin stays NULL instead of using a fake
    fixed percentage.
    """

    estimated_fees = round(keepa_data.price * 0.15, 2)
    if keepa_data.landed_cost is None:
        est_net_margin = None
        margin_source = keepa_data.margin_source or "missing_landed_cost"
        margin_confidence = keepa_data.margin_confidence or "unknown"
    else:
        est_net_margin = round(
            (keepa_data.price - keepa_data.landed_cost - estimated_fees) / keepa_data.price,
            4,
        )
        margin_source = keepa_data.margin_source or "estimated_from_landed_cost"
        margin_confidence = keepa_data.margin_confidence or "estimated"
    demand_bucket = "high" if keepa_data.bsr <= 10_000 else "medium" if keepa_data.bsr <= 50_000 else "low"
    monthly_sales_estimate = estimate_monthly_sales(
        bsr=keepa_data.bsr,
        category=keepa_data.category,
        parent_category_name=keepa_data.parent_category_name,
        subcategory_name=keepa_data.subcategory_name,
        monthly_sales=keepa_data.monthly_sales,
    )

    category_path = keepa_data.category_path or [keepa_data.category]
    category_id_path = keepa_data.category_id_path
    amazon_leaf_category_id = keepa_data.category_id or (
        category_id_path[-1] if category_id_path else None
    )

    return NormalizedProduct(
        asin=keepa_data.asin,
        source_query=source_query,
        marketplace=keepa_data.marketplace,
        title=keepa_data.title,
        brand=keepa_data.brand,
        category=keepa_data.category,
        price=keepa_data.price,
        bsr=keepa_data.bsr,
        reviews=keepa_data.reviews,
        seller_count=keepa_data.seller_count,
        landed_cost=keepa_data.landed_cost,
        est_net_margin=est_net_margin,
        brand_share=keepa_data.brand_share,
        price_trend=keepa_data.price_trend,
        rating=keepa_data.rating,
        image_url=keepa_data.image_url,
        fulfillment_method=keepa_data.fulfillment_method,
        lithium_battery_warning=keepa_data.lithium_battery_warning,
        margin_source=margin_source,
        margin_confidence=margin_confidence,
        category_id=amazon_leaf_category_id or _category_id(keepa_data.category),
        category_path=category_path,
        state=ProductState.ENRICHED,
        features={
            "demand_bucket": demand_bucket,
            "estimated_fees": estimated_fees,
            "feature_source": "keepa_v1",
            "fulfillment_method": keepa_data.fulfillment_method or "unknown",
            "lithium_battery_warning": keepa_data.lithium_battery_warning,
            "margin_source": margin_source,
            "margin_confidence": margin_confidence,
            "monthly_sales": keepa_data.monthly_sales,
            "monthly_sales_source": "keepa_monthly_sold"
            if keepa_data.monthly_sales is not None
            else "unknown",
            "fba_fee_usd": keepa_data.fba_fee_usd,
            "fba_pick_pack_fee_usd": keepa_data.fba_fee_usd,
            "fba_fee_currency": "USD" if keepa_data.fba_fee_usd is not None else None,
            "fba_fee_source": "keepa_fbaFees.pickAndPackFee"
            if keepa_data.fba_fee_usd is not None
            else "missing_keepa_fbaFees",
            "fba_fee_last_update": keepa_data.fba_fee_last_update,
            "referral_fee_percentage": keepa_data.referral_fee_percentage,
            "package_weight_g": keepa_data.package_weight_g,
            "package_length_mm": keepa_data.package_length_mm,
            "package_width_mm": keepa_data.package_width_mm,
            "package_height_mm": keepa_data.package_height_mm,
            "item_weight_g": keepa_data.item_weight_g,
            "item_length_mm": keepa_data.item_length_mm,
            "item_width_mm": keepa_data.item_width_mm,
            "item_height_mm": keepa_data.item_height_mm,
            **monthly_sales_estimate.to_features(),
            "parent_category_name": keepa_data.parent_category_name,
            "parent_category_rank": keepa_data.parent_category_rank,
            "amazon_category_path": category_path,
            "amazon_category_id_path": category_id_path,
            "amazon_leaf_category_id": amazon_leaf_category_id,
            "subcategory_name": keepa_data.subcategory_name or keepa_data.category,
            "subcategory_rank": keepa_data.subcategory_rank,
            "image_candidates": keepa_data.image_candidates,
        },
    )
