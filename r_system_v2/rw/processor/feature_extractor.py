"""Feature extraction for normalized Warehouse products."""

from __future__ import annotations

from r_system_v2.rw.core.models import KeepaProductData, NormalizedProduct, ProductState


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
        category_id=_category_id(keepa_data.category),
        category_path=[keepa_data.category],
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
            "parent_category_name": keepa_data.parent_category_name,
            "parent_category_rank": keepa_data.parent_category_rank,
            "subcategory_name": keepa_data.subcategory_name or keepa_data.category,
            "subcategory_rank": keepa_data.subcategory_rank or keepa_data.bsr,
        },
    )
