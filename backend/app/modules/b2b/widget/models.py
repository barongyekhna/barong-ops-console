"""产品页 B2B 小窗的派单任务表。

结构照抄 `geo_series/content/models.py` 的 GeoBacklinkJob——那套语义是生产
事故换来的,不重新推导。

**爆炸半径刻意做小**:这条流只在已存在的 Woo 产品上写**一个** meta 字段
(`_kp_b2b`)。永不建产品、永不改价、永不碰图片、永不动描述(描述归 P 系列
和 GEO 反链管,两边打架过)。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import conv
from sqlalchemy.types import Uuid

from ....db.base import Base
from ....models.base_mixins import json_type

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_DISPATCHED = "dispatched"
JOB_STATUS_SUCCESS = "success"
JOB_STATUS_FAILED = "failed"


class B2BWidgetJob(Base):
    """一次「把批发信息推到产品页」的派单。

    `targets_json` 在**派单那一刻**就冻住:n8n 拉到的包和派单时决定的内容
    一定一致。别在包端点里重新推导——重新推导意味着派单后数据变了,n8n
    拿到的会和台账记录的不是一回事。
    """

    __tablename__ = "b2b_widget_jobs"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_b2b_widget_jobs_job_id"),
        CheckConstraint(
            "status IN ('queued', 'dispatched', 'success', 'failed')",
            name=conv("ck_b2b_widget_jobs_status"),
        ),
        Index("ix_b2b_widget_jobs_status", "status"),
        Index("ix_b2b_widget_jobs_created", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # 对外的公开句柄(hex uuid4),包 URL 和回调 URL 都用它。
    job_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="woocommerce",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=JOB_STATUS_QUEUED,
    )
    # 一单一钥:包端点靠 (job_id, token) 配对鉴权,回调靠 X-Job-Token。
    token: Mapped[str] = mapped_column(String(128), nullable=False)
    targets_json: Mapped[list | None] = mapped_column(json_type(), nullable=True)
    updated_items_json: Mapped[list | None] = mapped_column(
        json_type(), nullable=True
    )
    requested_by_username: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
