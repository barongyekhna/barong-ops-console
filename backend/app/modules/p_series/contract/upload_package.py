"""P-series upload-package contract — the packaged, versioned single source of
truth for a product's canonical, publishable representation.

Why this is its own package (not inlined in an endpoint):

* **P series** builds the WooCommerce product from it.
* **The future GMC series** will audit that the live website, the product page,
  and the Merchant Center feed all agree with it — Google disapproves products
  as *misrepresentation* when feed and landing page disagree on
  title / description / image / price / currency / availability. If every
  surface is projected from THIS one object, they agree by construction.

So the shape is frozen and versioned. Consumers pin ``UPLOAD_PACKAGE_SCHEMA_VERSION``
and can request the JSON Schema via ``upload_package_json_schema()``.

No DB / framework imports here on purpose — both series import this cleanly.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

UPLOAD_PACKAGE_SCHEMA_VERSION = "p-upload-package-v2"

Availability = Literal["in_stock", "out_of_stock", "preorder"]
Channel = Literal["woocommerce"]  # Amazon/GMC/SEO get their own channels later.
Placement = Literal["gallery", "description"]


class Price(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regular: Decimal
    sale: Decimal | None = None
    currency: str = Field(min_length=3, max_length=3)  # ISO-4217, e.g. "USD"


class Stock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Availability = "in_stock"
    qty: int | None = None


class Category(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str | None = None
    google_product_category: str | None = None
    merchant_product_type: str | None = None


class Seo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    description: str | None = None


class Keywords(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary: list[str] = Field(default_factory=list)
    secondary: list[str] = Field(default_factory=list)
    longtail: list[str] = Field(default_factory=list)


class Variant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str
    color: str | None = None
    size: str | None = None
    function: str | None = None
    price: Price | None = None
    image: str | None = None  # absolute URL
    gtin: str | None = None


class ImageAsset(BaseModel):
    """One publishable image with its store destination and media SEO fields.

    ``placement`` splits the set: gallery images go into the store's product
    image gallery; description images are embedded inside ``description.html``
    at the ``embed_token`` placeholder (the uploader replaces the token with
    the store-hosted media URL after uploading). title/alt/caption/description
    are the WordPress media SEO fields, written by gpt-5.5 at art-direction
    time.
    """

    model_config = ConfigDict(extra="forbid")
    asset_id: str
    url: str                       # fetchable by the uploader (job-token auth)
    placement: Placement = "gallery"
    position: int = 0              # global order from the art-direction brief
    is_main: bool = False          # exactly one gallery image is the main/hero
    role: str | None = None        # e.g. "Hero lifestyle image"
    filename: str | None = None
    mime_type: str | None = None
    title: str | None = None
    alt: str | None = None
    caption: str | None = None
    description: str | None = None
    # description-placement only: the exact placeholder inside description.html
    # (e.g. "{{KP_IMG_8}}") that must be replaced with the uploaded media URL.
    embed_token: str | None = None


class Description(BaseModel):
    """Marketing body. NOTE: never carries price / availability — those are
    structured fields, and duplicating them in prose is what breaks feed↔page
    consistency (GMC misrepresentation)."""

    model_config = ConfigDict(extra="forbid")
    html: str                       # from the product-page-layout skill
    text: str | None = None         # plain-text fallback
    bullets: list[str] = Field(default_factory=list)
    layout_skill_version: str | None = None
    category_block: str | None = None


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str | None = None
    title: str
    brand: str | None = None
    product_type: str | None = None
    gtin: str | None = None
    mpn: str | None = None
    condition: Literal["new", "refurbished", "used"] = "new"
    description: Description
    price: Price
    stock: Stock
    category: Category
    # v2: rich image objects. Gallery images first (main/hero leads), then
    # description-embedded images; see ImageAsset.placement.
    images: list[ImageAsset] = Field(default_factory=list)
    keywords: Keywords = Field(default_factory=Keywords)
    seo: Seo = Field(default_factory=Seo)
    variants: list[Variant] = Field(default_factory=list)
    item_group_id: str | None = None  # ties variants together for GMC


class Gate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ready: bool
    blockers: list[str] = Field(default_factory=list)


class UploadPackage(BaseModel):
    """Top-level object returned by the data-fetch endpoint and consumed by n8n
    (and, later, the GMC audit series)."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = UPLOAD_PACKAGE_SCHEMA_VERSION
    job_id: str | None = None
    product_id: UUID
    workflow_trace_id: str | None = None
    channel: Channel = "woocommerce"
    generated_at: datetime
    gate: Gate
    product: Product


# --- GMC bridge -----------------------------------------------------------
# The map the future GMC series uses to audit each surface (feed / product page /
# website) against this canonical object. Keys = Google Merchant Center feed
# attributes; values = dotted paths into UploadPackage.product.
GMC_ATTRIBUTE_MAP: dict[str, str] = {
    "id": "sku",
    "title": "title",
    "description": "description.text",
    "image_link": "images[placement=gallery][main].url",
    "additional_image_link": "images[placement=gallery][rest].url",
    "availability": "stock.status",
    "price": "price.regular+price.currency",
    "sale_price": "price.sale+price.currency",
    "brand": "brand",
    "gtin": "gtin",
    "mpn": "mpn",
    "google_product_category": "category.google_product_category",
    "product_type": "category.merchant_product_type",
    "item_group_id": "item_group_id",
    "condition": "condition",
}


def gmc_feed_view(package: UploadPackage) -> dict[str, Any]:
    """Project the canonical package into GMC feed attributes. The Woo product
    and this feed view come from the SAME object, so they cannot silently drift
    apart — that is the misrepresentation guard. The GMC series later diffs this
    against the live feed + rendered page."""
    p = package.product
    price = f"{p.price.regular} {p.price.currency}"
    sale = f"{p.price.sale} {p.price.currency}" if p.price.sale is not None else None
    gallery = [img for img in p.images if img.placement == "gallery"]
    gallery.sort(key=lambda img: (not img.is_main, img.position))
    return {
        "id": p.sku,
        "title": p.title,
        "description": p.description.text,
        "image_link": gallery[0].url if gallery else None,
        "additional_image_link": [img.url for img in gallery[1:]],
        "availability": p.stock.status,
        "price": price,
        "sale_price": sale,
        "brand": p.brand,
        "gtin": p.gtin,
        "mpn": p.mpn,
        "google_product_category": p.category.google_product_category,
        "product_type": p.category.merchant_product_type,
        "item_group_id": p.item_group_id,
        "condition": p.condition,
    }


def upload_package_json_schema() -> dict[str, Any]:
    """Emit the JSON Schema for external consumers (n8n docs, GMC series, tests)."""
    schema = UploadPackage.model_json_schema()
    schema["$schemaVersion"] = UPLOAD_PACKAGE_SCHEMA_VERSION
    return schema
