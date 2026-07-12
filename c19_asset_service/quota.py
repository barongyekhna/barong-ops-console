"""Shared SQL expressions for durable Asset capacity accounting."""

from __future__ import annotations

from sqlalchemy import and_, case, func

from .models import Asset


def retained_asset_predicate():
    return Asset.status != "deleted"


def reserved_asset_bytes_expression(thumbnail_max_bytes: int):
    thumbnail_reservation = case(
        (
            and_(Asset.kind == "image", Asset.thumbnail_size_bytes.is_(None)),
            thumbnail_max_bytes,
        ),
        else_=func.coalesce(Asset.thumbnail_size_bytes, 0),
    )
    return (
        func.coalesce(Asset.actual_size_bytes, Asset.declared_size_bytes, 0)
        + thumbnail_reservation
    )


__all__ = ["reserved_asset_bytes_expression", "retained_asset_predicate"]
