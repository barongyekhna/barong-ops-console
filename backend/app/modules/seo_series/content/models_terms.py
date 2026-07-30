"""SEO 的 WP 分类缓存表。单独一个文件,免得 models.py 变成杂物间。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base


class SeoWpCategoryMap(Base):
    """分类名 → WordPress term id。

    死规矩(踩过):删 WordPress 分类必须同时清这张表——代码不校验 term 还在不在,
    留着陈旧 id 会把文章挂到一个已经不存在的分类上。
    """

    __tablename__ = "seo_wp_category_map"
    __table_args__ = (
        UniqueConstraint("name", name=conv("uq_seo_wp_category_map_name")),
        Index("ix_seo_wp_category_map_destination", "destination"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    destination: Mapped[str] = mapped_column(String(16), nullable=False)
    wp_term_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["SeoWpCategoryMap"]
