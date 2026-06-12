from backend.app.modules.k_series.product_knowledge import constants


def test_module_key_and_api_prefix_are_k_scoped() -> None:
    assert constants.MODULE_KEY == "k.product_knowledge"
    assert constants.API_PREFIX == "/api/k/product-knowledge"


def test_scope_defaults_match_independent_store_shim() -> None:
    assert constants.DEFAULT_WORKSPACE_KEY == "default_independent_store"
    assert constants.DEFAULT_BUSINESS_CONTEXT == "independent_store"
    assert constants.DEFAULT_SCOPE_MODE == "adapter_pending"


def test_permission_keys_use_k_product_knowledge_prefix() -> None:
    assert constants.PERMISSION_KEYS
    assert set(constants.ACTION_PERMISSION_KEYS.values()) == set(
        constants.PERMISSION_KEYS
    )

    for permission_key in constants.PERMISSION_KEYS:
        assert permission_key.startswith("k.product_knowledge.")


def test_operation_log_actions_use_k_product_knowledge_prefix() -> None:
    assert constants.OPERATION_ACTIONS

    for action in constants.OPERATION_ACTIONS:
        assert action.startswith("k.product_knowledge.")
