"""content_core 自己的一张 KV 表。

只装**跨模块的内容态**:链接图的指纹、上次推送时间、dirty 标志、摘要。

为什么不塞进 ``geo_site_settings``:链接图是 GEO + SEO + 产品页三边共有的东西,
放在任何一边的表里都会让另外两边"借"别人的家具。一张表、四个键,便宜。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ...db.base import Base


class ContentLinkSetting(Base):
    """键值对。内容见 ``link_push`` 里的几个 ``*_KEY`` 常量。"""

    __tablename__ = "content_link_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = ["ContentLinkSetting"]
