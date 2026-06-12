import inspect

from backend.app.modules.k_series.product_knowledge import service

SERVICE_FUNCTIONS = (
    "list_products",
    "create_product",
    "get_product",
    "update_product",
    "archive_product",
    "get_attributes",
    "patch_attributes",
    "get_keywords",
    "patch_keywords",
    "get_risk_terms",
    "patch_risk_terms",
)


def test_service_functions_exist_and_are_callable() -> None:
    for function_name in SERVICE_FUNCTIONS:
        function = getattr(service, function_name)
        assert callable(function)


def test_service_functions_keep_db_as_explicit_first_parameter() -> None:
    for function_name in SERVICE_FUNCTIONS:
        signature = inspect.signature(getattr(service, function_name))
        parameter_names = list(signature.parameters)

        assert parameter_names[0] == "db"


def test_service_contract_checks_do_not_execute_database_operations() -> None:
    for function_name in SERVICE_FUNCTIONS:
        signature = inspect.signature(getattr(service, function_name))

        assert "db" in signature.parameters
        assert "scope_context" in signature.parameters


def test_service_layer_has_no_live_provider_or_external_workflow_touchpoints() -> None:
    source = inspect.getsource(service).lower()
    forbidden_tokens = (
        "requests",
        "httpx",
        "aiohttp",
        "n8n",
        "woocommerce",
        "google sheets",
        "gspread",
        "openai",
        "deepseek",
        "claude",
        "serp",
        "wecom",
        "minio",
        "filebrowser",
    )

    for token in forbidden_tokens:
        assert token not in source
