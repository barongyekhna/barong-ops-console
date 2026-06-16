from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class MessageRecord(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "content_type IN ('text', 'emoji')",
            name="messages_content_type_valid",
        ),
        CheckConstraint(
            "status IN ('sent', 'delivered', 'read')",
            name="messages_status_valid",
        ),
        Index("ix_messages_conversation_id", "conversation_id"),
        Index("ix_messages_from_user_id", "from_user_id"),
        Index("ix_messages_to_user_id", "to_user_id"),
    )

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    from_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    to_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="sent",
        server_default="sent",
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
