"""Temporary K Scope Shim for adapter-pending Product Knowledge data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from .constants import (
    DEFAULT_BUSINESS_CONTEXT,
    DEFAULT_SCOPE_MODE,
    DEFAULT_WORKSPACE_KEY,
)

QueryT = TypeVar("QueryT")


@dataclass(frozen=True)
class KScopeContext:
    workspace_key: str
    business_context: str
    scope_mode: str


def default_scope_context() -> KScopeContext:
    return KScopeContext(
        workspace_key=DEFAULT_WORKSPACE_KEY,
        business_context=DEFAULT_BUSINESS_CONTEXT,
        scope_mode=DEFAULT_SCOPE_MODE,
    )


def normalize_scope_context(
    scope_context: KScopeContext | Mapping[str, str] | None = None,
    *,
    workspace_key: str | None = None,
    business_context: str | None = None,
    scope_mode: str | None = None,
) -> KScopeContext:
    if isinstance(scope_context, KScopeContext):
        base = scope_context
    elif scope_context is not None:
        base = KScopeContext(
            workspace_key=scope_context.get("workspace_key", DEFAULT_WORKSPACE_KEY),
            business_context=scope_context.get(
                "business_context",
                DEFAULT_BUSINESS_CONTEXT,
            ),
            scope_mode=scope_context.get("scope_mode", DEFAULT_SCOPE_MODE),
        )
    else:
        base = default_scope_context()

    return KScopeContext(
        workspace_key=_non_empty_or_default(workspace_key, base.workspace_key),
        business_context=_non_empty_or_default(
            business_context,
            base.business_context,
        ),
        scope_mode=_non_empty_or_default(scope_mode, base.scope_mode),
    )


def apply_scope_filters(
    query: QueryT,
    model: type[Any],
    scope_context: KScopeContext | Mapping[str, str] | None = None,
) -> QueryT:
    """Constrain a SQLAlchemy select/query by the adapter-pending shim fields."""

    context = normalize_scope_context(scope_context)
    conditions = (
        model.workspace_key == context.workspace_key,
        model.business_context == context.business_context,
        model.scope_mode == context.scope_mode,
    )
    scoped_query: Any = query
    for condition in conditions:
        if hasattr(scoped_query, "where"):
            scoped_query = scoped_query.where(condition)
        elif hasattr(scoped_query, "filter"):
            scoped_query = scoped_query.filter(condition)
        else:
            raise TypeError("Query object does not support scope filtering.")
    return cast(QueryT, scoped_query)


def _non_empty_or_default(value: str | None, default: str) -> str:
    if value is None:
        return default
    normalized = value.strip()
    return normalized or default
