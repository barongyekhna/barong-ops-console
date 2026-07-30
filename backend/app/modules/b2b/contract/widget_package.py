"""B2B 产品页小窗的发布包契约——n8n 该往产品上写什么。

控制台**完全**决定每个产品的小窗内容,n8n `barongB2Bwidget001` 是一根笨管子:
读一个 Woo 产品,写一个 `_kp_b2b` meta 字段,回报。决策留在这边,跑批才可审计。

冻结并带版本号;n8n 的 Code 节点在写入前硬断言版本。

⚠️ **这里绝不出现价格。** 小窗上不显示批发价(GMC 会把"页面价与 feed 价不符"
判成 Misrepresentation,用户被封过两次只剩一次申诉),契约层就把这个口子堵死——
没有字段可以承载价格,后面谁也塞不进去。有测试钉着。

刻意不 import 任何数据库/框架代码。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

B2B_WIDGET_PACKAGE_VERSION = "b2b-widget-package-v1"

Channel = Literal["woocommerce"]

# Woo 产品上由控制台托管的 meta 键。沿用 P 系列的 `_kp_*` 归属惯例:
# **永远写这个键**(撤下时写空串),否则更新会留下过期的小窗。
WIDGET_META_KEY = "_kp_b2b"


class WidgetTarget(BaseModel):
    """一个产品的小窗数据。

    `available=False` 是有意义的状态,不是"跳过":它让 n8n 把 meta 写成空,
    产品页上的小窗随即消失。批发价被清空、产品归档,走的都是这条路。
    """

    model_config = ConfigDict(extra="forbid")

    sku: str
    woo_product_id: int
    available: bool = False
    # 以下只在 available=True 时有值。**没有价格字段,也永远不要加。**
    moq_units: int | None = None
    case_pack: int | None = None
    lead_time_days: int | None = None
    # "可提供颜色/款式"之类,店家最关心能不能配色卖。
    variant_note: str | None = Field(default=None, max_length=255)


class WidgetPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = B2B_WIDGET_PACKAGE_VERSION
    job_id: str | None = None
    channel: Channel = "woocommerce"
    generated_at: datetime | None = None
    meta_key: str = WIDGET_META_KEY
    targets: list[WidgetTarget] = Field(default_factory=list)


__all__ = [
    "B2B_WIDGET_PACKAGE_VERSION",
    "WIDGET_META_KEY",
    "WidgetPackage",
    "WidgetTarget",
]
