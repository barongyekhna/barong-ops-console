from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import SecretStr

from backend.app.core.config import Settings
from backend.app.modules.p_series.upload.models import KCategoryWCMap


pytestmark = pytest.mark.unit


def test_wc_category_map_model_matches_control_plane_contract() -> None:
    table = KCategoryWCMap.__table__

    assert table.name == "k_category_wc_map"
    assert table.primary_key.columns.keys() == ["google_id"]
    assert table.c.google_id.type.length == 32
    assert table.c.wc_term_id.nullable is False
    assert table.c.synced_at.nullable is False


def test_wc_category_map_migration_is_the_only_head() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    config = Config(str(repo_root / "backend" / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    # 这条断言的真正意义是"迁移图永远只有一个 head"——追加迁移时把它
    # 移到新 head 即可,但绝不允许出现第二个 head(并行开工炸过库)。
    assert scripts.get_heads() == ["20260731_01_content_link_settings"]
    revision = scripts.get_revision("20260716_01_p_wc_category_map")
    assert revision is not None
    assert revision.down_revision == "20260715_01_h_site_health"


def test_wc_category_settings_are_loaded_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WP_BASE_URL", "https://shop.example.test")
    monkeypatch.setenv("WP_APP_USER", "category-sync-test")
    monkeypatch.setenv("WP_APP_PASSWORD", "example-only-app-password")
    monkeypatch.setenv("WP_REQUEST_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("WP_REQUEST_MAX_ATTEMPTS", "4")

    settings = Settings()

    assert settings.wp_base_url == "https://shop.example.test"
    assert settings.wp_app_user == "category-sync-test"
    assert isinstance(settings.wp_app_password, SecretStr)
    assert settings.wp_app_password.get_secret_value() == "example-only-app-password"
    assert settings.wp_request_timeout_seconds == 12
    assert settings.wp_request_max_attempts == 4
