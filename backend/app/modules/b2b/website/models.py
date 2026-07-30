"""B2B 站点侧 id 的小键值表。

存 `/wholesale/` 主页和各店型子页的 WordPress 页面 id——页面在第一次发布时
创建,之后每次重发都要靠 id 找回来。用一张表而不是环境变量,因为这些 id 是
运行时产生的。

**不复用 GEO 的 `geo_site_settings`**:那张表建在 GEO 的迁移里,跨模块共用
一张表会让两边的迁移互相绑死。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ....db.base import Base

# 主页 id。页面 1792 是手工建的,第一次发布时会把它认领进来。
WHOLESALE_PAGE_ID_KEY = "wholesale_page_id"
# 店型子页 id:`wholesale_page_id:<store_type_key>`
STORE_TYPE_PAGE_ID_PREFIX = "wholesale_page_id:"
LAST_PUBLISHED_KEY = "wholesale_last_published_at"
# 每个店型页上**真的挂上去了**几篇指南:`wholesale_guides:<store_type_key>`。
# 存下来而不是查询时重算——重算得向 WP 核一遍发布状态(出网),而面板是
# 高频读的;而且"页面上现在是什么"本来就该是上次发布的结果,不是猜测。
GUIDE_COUNT_PREFIX = "wholesale_guides:"
# guide-links option 覆盖了几个 WP 类目(反向回链的覆盖面)。
GUIDE_CATEGORIES_KEY = "wholesale_guide_categories"


class B2BSiteSetting(Base):
    __tablename__ = "b2b_site_settings"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
