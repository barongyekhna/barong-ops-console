import inspect

from backend.app.modules.k_series.product_knowledge import models

MODEL_CLASS_NAMES = (
    "KProductKnowledgeProduct",
    "KProductKnowledgeAttribute",
    "KProductKnowledgeTranslation",
    "KProductKnowledgeKeyword",
    "KProductKnowledgeRiskTerm",
    "KProductKnowledgeResearchRun",
    "KProductKnowledgeAIEvent",
    "KProductKnowledgeVersion",
    "KProductKnowledgeMediaAsset",
    "KProductKnowledgeReviewItem",
)


def _k_model_classes() -> tuple[type[object], ...]:
    return tuple(getattr(models, class_name) for class_name in MODEL_CLASS_NAMES)


def test_current_model_classes_exist() -> None:
    for class_name in MODEL_CLASS_NAMES:
        assert hasattr(models, class_name)


def test_model_table_names_use_k_product_knowledge_prefix() -> None:
    for model_class in _k_model_classes():
        assert model_class.__tablename__.startswith("k_product_knowledge_")


def test_product_model_has_scope_shim_columns() -> None:
    columns = models.KProductKnowledgeProduct.__table__.columns.keys()

    assert "workspace_key" in columns
    assert "business_context" in columns
    assert "scope_mode" in columns


def test_models_do_not_foreign_key_to_formal_scope_or_core_users() -> None:
    for model_class in _k_model_classes():
        for foreign_key in model_class.__table__.foreign_keys:
            assert foreign_key.column.table.name.startswith("k_product_knowledge_")

    source = inspect.getsource(models)
    forbidden_foreign_key_targets = (
        'ForeignKey("users.',
        "ForeignKey('users.",
        'ForeignKey("organizations.',
        "ForeignKey('organizations.",
        'ForeignKey("operation_logs.',
        "ForeignKey('operation_logs.",
        'ForeignKey("scopes.',
        "ForeignKey('scopes.",
    )
    for target in forbidden_foreign_key_targets:
        assert target not in source


def test_models_contract_does_not_import_alembic_or_open_db_connections() -> None:
    source = inspect.getsource(models)

    assert "alembic" not in source.lower()
    assert "create_engine" not in source
    assert "SessionLocal" not in source
    assert "get_db" not in source
