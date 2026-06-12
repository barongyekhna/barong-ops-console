import inspect

from backend.app.modules.k_series.product_knowledge import feature_flags


def test_k_product_knowledge_feature_flag_defaults_to_false() -> None:
    assert feature_flags.is_k_product_knowledge_enabled() is False


def test_feature_flag_is_module_local_and_does_not_read_env_or_core_config() -> None:
    source = inspect.getsource(feature_flags)

    forbidden_tokens = (
        "import os",
        "os.environ",
        "getenv(",
        "environ[",
        "core.config",
        "get_settings",
        "Settings(",
    )

    for token in forbidden_tokens:
        assert token not in source
