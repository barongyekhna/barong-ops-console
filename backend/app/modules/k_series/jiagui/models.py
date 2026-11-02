"""作图家规注册表的三张表(交接 09 第 2b 节、M0 冻结版第五部分)。

没有 org_id 列:风格包是全站共用的家规,不按组织隔离(和苏青禾的表一样,C18G 不会去过滤它)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Index, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ....db.base import Base

# 注册表状态(和包自己的 stage 是两回事):待生效 / 生效 / 停用 / 驳回
PENDING = "pending"
ACTIVE = "active"
RETIRED = "retired"
REJECTED = "rejected"
STATUSES = (PENDING, ACTIVE, RETIRED, REJECTED)
STATUS_LABELS = {PENDING: "待生效", ACTIVE: "生效", RETIRED: "停用", REJECTED: "驳回"}


def _json() -> JSON:
    return JSON().with_variant(JSONB(), "postgresql")


class JiaguiCoreVersion(Base):
    """基座版本(M1 交付后才有行)。完整包要查 core 版本;只含选包的包不查。"""

    __tablename__ = "jiagui_core_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=PENDING)
    selftest: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)
    decided_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class JiaguiPack(Base):
    """一个风格包的一个版本。同一个包 id 同一时间只有一个「生效」(库里有部分唯一索引兜底)。"""

    __tablename__ = "jiagui_packs"
    __table_args__ = (
        UniqueConstraint("pack_id", "version", name="uq_jiagui_packs_pack_version"),
        Index("uq_jiagui_packs_one_active", "pack_id", unique=True, postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=PENDING)
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    provides: Mapped[Any] = mapped_column(_json(), nullable=False, default=list)
    core_req: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False, default="")  # 收进来的文件名
    pack_json: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)
    manifest: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)  # 包内文件 → sha256
    # 登记时生效的那一版;只改进度的判定就是拿它比
    previous_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    progress_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    card_ref: Mapped[str | None] = mapped_column(String(8), nullable=True)
    registered_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 用户 id,或 system(只改进度自动生效 / 检查没过)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class JiaguiPackCheck(Base):
    """每次自动检查一行:verify(收包检查)、replay(装了它以后选包结果会变的品)、以后的 test / selftest。"""

    __tablename__ = "jiagui_pack_checks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pack_row_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result: Mapped[Any] = mapped_column(_json(), nullable=False, default=dict)
    cost_usd: Mapped[Any] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
