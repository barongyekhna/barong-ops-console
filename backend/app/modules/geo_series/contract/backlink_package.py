"""GEO backlink-package contract — what the product pages should carry back.

The console decides *entirely* what each product's blocks contain and ships the
finished HTML; the n8n workflow ``barongGEObacklink001`` is a dumb pipe that reads
one Woo product, swaps the marker-delimited blocks, and writes back the single
``description`` field. Keeping the decision here is what makes the run auditable
and what keeps the blocks identical to the ones P injects at upload time.

Frozen and versioned; the n8n Code node hard-asserts the version before writing.

## v2 为什么不能沿用 v1

v1 一个 target 只带一个块(``block_html``)。产品页现在要挂**两个**块
(``kp-guides`` 指南 + ``kp-factory`` 工艺文)。

**不能靠"一个产品发两条 target"绕过去**:n8n 那条流是「GET 全部 → 合并 → PUT 全部」,
两条 target 会读到**同一份旧 description**,第二条 PUT 直接抹掉第一条的结果。
所以一条 target 必须带上这个产品的**全部**块。

顺带加了 ``fingerprint``:控制台算好这次要写进去的块组合的哈希,回报时原样带回来
落库。下次收集目标时拿它比对,就能**零 WP 调用**地算出"有几个产品页的链接已过期"。

No DB / framework imports here on purpose.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

GEO_BACKLINK_PACKAGE_VERSION = "geo-backlink-package-v2"

Channel = Literal["woocommerce"]


class BlockPatch(BaseModel):
    """一个块要变成什么样。

    ``html == ""`` **是有意义的**:它表示把这个块从产品页上**摘掉**——
    指南全部下线之后就该走这条路。v1 时代收集目标那一步对空块直接 ``continue``,
    导致这条语义永远走不到,线上产品页挂着摘不掉的死链(2026-07-31 查出)。
    """

    model_config = ConfigDict(extra="forbid")
    block_class: str
    html: str = ""


class BacklinkTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: UUID
    sku: str | None = None
    # The live Woo product to edit — resolved from the successful upload job.
    woo_product_id: int
    # 这个产品的**全部**块,一次写完(见模块文档:拆成多条会互相覆盖)。
    blocks: list[BlockPatch] = Field(default_factory=list)
    # 控制台算的块组合哈希,回报时原样带回落库,用来算"过期"。
    fingerprint: str = ""
    # 给运营看的一句人话:这个产品为什么要更新。
    reason: str = ""


class BacklinkPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = GEO_BACKLINK_PACKAGE_VERSION
    job_id: str | None = None
    channel: Channel = "woocommerce"
    generated_at: datetime | None = None
    targets: list[BacklinkTarget] = Field(default_factory=list)


__all__ = [
    "GEO_BACKLINK_PACKAGE_VERSION",
    "BacklinkPackage",
    "BacklinkTarget",
    "BlockPatch",
]
