import pytest

from backend.app.api.routes.rw import _user_has_rw_role_access
from backend.app.models.user import User
from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
from r_system_v2.rw.core.rule_engine import RuleEngine
from r_system_v2.rw.core.warehouse_engine import WarehouseEngine
from r_system_v2.rw.providers.keepa_provider import (
    MAX_REQUESTS_PER_MINUTE,
    MOCK_MODE,
    USE_REAL_KEEPA_API,
    KeepaConfigurationError,
    KeepaProvider,
)
from r_system_v2.rw.scheduler.keepa_scheduler import KeepaScheduler
from r_system_v2.rw.storage.repository import MockWarehouseRepository


def test_keepa_provider_defaults_to_production_without_mock_fallback(monkeypatch):
    monkeypatch.delenv("KEEPA_API_KEY", raising=False)

    provider = KeepaProvider()

    assert MOCK_MODE is False
    assert USE_REAL_KEEPA_API is True
    assert provider.mock_mode is False
    with pytest.raises(KeepaConfigurationError, match="keepa_api_key_missing"):
        provider.status()


def test_keepa_scheduler_caps_requests_at_twenty_without_burst():
    provider = KeepaProvider(force_mock=True, tokens_per_min=200)
    repository = MockWarehouseRepository()
    engine = WarehouseEngine(provider=provider, rule_engine=RuleEngine(), repository=repository)
    records = engine.ingest([f"B0TEST{i:04d}" for i in range(30)])
    scheduler = KeepaScheduler(
        provider=provider,
        processor=engine.process_discovered_asin,
        rate_limit_per_min=200,
    )

    scheduler.enqueue(records)
    report = scheduler.run_once()

    assert report.rate_limit_per_min == MAX_REQUESTS_PER_MINUTE
    assert report.token_budget == MAX_REQUESTS_PER_MINUTE
    assert report.processed == MAX_REQUESTS_PER_MINUTE
    assert report.no_burst_mode is True
    assert report.queue_based_ingestion is True
    assert report.refill_aware is True


def test_deepseek_skill_loads_and_emits_strict_json_for_rule_passed_product():
    provider = KeepaProvider(force_mock=True)
    repository = MockWarehouseRepository()
    engine = WarehouseEngine(
        provider=provider,
        rule_engine=RuleEngine(),
        repository=repository,
        deepseek_skill=DeepSeekScreeningSkill(),
    )
    record = engine.ingest("portable door draft stopper")[0]

    result = engine.process_discovered_asin(record)

    assert result.rule_evaluation.passed is True
    assert result.deepseek_screening is not None
    assert result.deepseek_screening.skill_loaded is True
    assert result.deepseek_screening.quant_filter_enabled is True
    assert result.deepseek_screening.rule_based_scoring_active is True
    assert result.deepseek_screening.output_schema_strict_json is True
    assert set(result.deepseek_screening.strict_json) == {
        "score",
        "verdict",
        "competition_attackability",
        "demand_quality",
        "top_reason",
        "channel_guess",
    }
    assert repository.ai_evaluations
    assert result.transitions[:3] == ["discovered", "enriched", "rule_passed"]
    assert result.transitions[-1] == "ai1_passed"


def test_rw_role_gate_allows_only_owner_and_super_admin():
    assert _user_has_rw_role_access(User(username="owner", role="owner")) is True
    assert (
        _user_has_rw_role_access(User(username="super_admin", role="super_admin"))
        is True
    )
    assert (
        _user_has_rw_role_access(User(username="normal_user", role="normal_user"))
        is False
    )
