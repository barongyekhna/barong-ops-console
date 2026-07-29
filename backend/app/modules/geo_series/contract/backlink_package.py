"""GEO backlink-package contract — what the product pages should carry back.

The console decides *entirely* what each product's "Learn more" block contains and
ships the finished HTML; the n8n workflow ``barongGEObacklink001`` is a dumb pipe
that reads one Woo product, swaps the marker-delimited block, and writes back the
single ``description`` field. Keeping the decision here is what makes the run
auditable and what keeps the block identical to the one P injects at upload time.

Frozen and versioned; the n8n Code node hard-asserts the version before writing.

No DB / framework imports here on purpose.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

GEO_BACKLINK_PACKAGE_VERSION = "geo-backlink-package-v1"

Channel = Literal["woocommerce"]


class BacklinkTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    sku: str | None = None
    # The live Woo product to edit — resolved from the successful upload job.
    woo_product_id: int
    # Finished block HTML. Empty string is meaningful: it removes a stale block
    # from a product whose guides are no longer published.
    block_html: str = ""
    guide_count: int = 0


class BacklinkPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = GEO_BACKLINK_PACKAGE_VERSION
    job_id: str | None = None
    channel: Channel = "woocommerce"
    generated_at: datetime | None = None
    # Marker the workflow uses to find an existing block; sent so the matching rule
    # lives in the contract instead of being duplicated in a Code node.
    block_class: str = "kp-guides"
    targets: list[BacklinkTarget] = Field(default_factory=list)


__all__ = [
    "GEO_BACKLINK_PACKAGE_VERSION",
    "BacklinkPackage",
    "BacklinkTarget",
]
