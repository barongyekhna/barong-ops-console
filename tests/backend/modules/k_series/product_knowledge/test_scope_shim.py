from typing import Any

from backend.app.modules.k_series.product_knowledge import constants, scope_shim


class _FakeColumn:
    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, value: object) -> tuple[str, object]:  # type: ignore[override]
        return (self.name, value)


class _FakeModel:
    workspace_key = _FakeColumn("workspace_key")
    business_context = _FakeColumn("business_context")
    scope_mode = _FakeColumn("scope_mode")


class _WhereQuery:
    def __init__(self) -> None:
        self.conditions: list[Any] = []

    def where(self, condition: Any) -> "_WhereQuery":
        self.conditions.append(condition)
        return self


class _FilterQuery:
    def __init__(self) -> None:
        self.conditions: list[Any] = []

    def filter(self, condition: Any) -> "_FilterQuery":
        self.conditions.append(condition)
        return self


def test_default_scope_context_matches_adapter_pending_defaults() -> None:
    context = scope_shim.default_scope_context()

    assert context.workspace_key == "default_independent_store"
    assert context.business_context == "independent_store"
    assert context.scope_mode == "adapter_pending"


def test_normalize_scope_context_without_values_returns_defaults() -> None:
    assert scope_shim.normalize_scope_context() == scope_shim.default_scope_context()


def test_normalize_scope_context_preserves_custom_values() -> None:
    context = scope_shim.normalize_scope_context(
        {
            "workspace_key": "custom_workspace",
            "business_context": "custom_business",
            "scope_mode": "custom_scope",
        }
    )

    assert context.workspace_key == "custom_workspace"
    assert context.business_context == "custom_business"
    assert context.scope_mode == "custom_scope"


def test_apply_scope_filters_is_callable_and_uses_where_interface() -> None:
    query = _WhereQuery()
    context = scope_shim.KScopeContext(
        workspace_key="workspace_a",
        business_context="business_a",
        scope_mode="scope_a",
    )

    result = scope_shim.apply_scope_filters(query, _FakeModel, context)

    assert callable(scope_shim.apply_scope_filters)
    assert result is query
    assert query.conditions == [
        ("workspace_key", "workspace_a"),
        ("business_context", "business_a"),
        ("scope_mode", "scope_a"),
    ]


def test_apply_scope_filters_uses_filter_fallback_without_mutating_defaults() -> None:
    before = scope_shim.default_scope_context()
    query = _FilterQuery()

    result = scope_shim.apply_scope_filters(query, _FakeModel)

    assert result is query
    assert query.conditions == [
        ("workspace_key", constants.DEFAULT_WORKSPACE_KEY),
        ("business_context", constants.DEFAULT_BUSINESS_CONTEXT),
        ("scope_mode", constants.DEFAULT_SCOPE_MODE),
    ]
    assert scope_shim.default_scope_context() == before
