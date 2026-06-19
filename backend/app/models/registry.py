from typing import Any

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .base_mixins import PrimaryKeyMixin, TimestampMixin, json_type


class RegistryFieldsMixin:
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    responsibilities: Mapped[list[Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    non_responsibilities: Mapped[list[Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    input_schema: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    output_schema: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    permissions: Mapped[list[Any]] = mapped_column(json_type(), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    dependencies: Mapped[list[Any]] = mapped_column(json_type(), nullable=False)
    artifact_types: Mapped[list[Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    review_types: Mapped[list[Any]] = mapped_column(json_type(), nullable=False)
    error_codes: Mapped[list[Any]] = mapped_column(json_type(), nullable=False)
    healthcheck_config: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    rollback_policy: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )


class ModuleRegistry(
    RegistryFieldsMixin,
    PrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "module_registry"

    module_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    organization_id: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        index=True,
    )


class AgentRegistry(
    RegistryFieldsMixin,
    PrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "agent_registry"

    agent_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    allowed_module_ids: Mapped[list[Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    allowed_workflow_ids: Mapped[list[Any]] = mapped_column(
        json_type(),
        nullable=False,
    )


class WorkflowRegistry(
    RegistryFieldsMixin,
    PrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "workflow_registry"

    workflow_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
    )
    engine: Mapped[str] = mapped_column(String(50), nullable=False)
    endpoint_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    callback_contract: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_policy: Mapped[dict[str, Any]] = mapped_column(
        json_type(),
        nullable=False,
    )
