from types import SimpleNamespace

from backend.app.core.key_registry import key_type_allows_module, key_type_definition
from backend.app.core.modules import MODULE_MANIFESTS_V1
from r_system_v2.core.secret_manager import (
    R_ANALYSIS_MODULE_ID,
    SERVICE_BINDING_CANDIDATES,
    SecretManager,
)
from r_system_v2.ra.framework import RA_REQUIRED_TABLES, RA_STAGES
from r_system_v2.ra.providers import RAnalysisProviderKeys
from r_system_v2.ra.providers import RAnalysisProviderBinding
from r_system_v2.ra.providers import google_ads_runtime_gate
from r_system_v2.ra.skill_loader import (
    load_ra_skill_bundle,
    load_ra_skill_manifest,
    skill_file_keys_for_channel,
)


def test_ra_skill_manifest_loads_product_selection_documents() -> None:
    manifest = load_ra_skill_manifest()

    assert manifest["loaded"] is True
    assert manifest["name"] == "product-selection"
    assert manifest["version"] == "v1"
    assert {item["key"] for item in manifest["files"]} == {
        "skill",
        "amazon",
        "dtc",
        "dtc_data",
        "ra_supplier_keyword",
        "shared",
    }
    assert manifest["prompt_content_exposed"] is False


def test_ra_skill_channel_file_map_keeps_amazon_and_dtc_separate() -> None:
    assert skill_file_keys_for_channel("amazon") == ("skill", "amazon", "shared")
    assert skill_file_keys_for_channel("dtc_seo") == (
        "skill",
        "dtc",
        "dtc_data",
        "shared",
    )
    assert skill_file_keys_for_channel("both") == (
        "skill",
        "amazon",
        "dtc",
        "dtc_data",
        "shared",
    )


def test_ra_skill_bundle_loads_prompt_files_with_combined_hash() -> None:
    bundle = load_ra_skill_bundle("amazon")

    assert bundle.name == "product-selection"
    assert bundle.version == "v1"
    assert [item.key for item in bundle.files] == ["skill", "amazon", "shared"]
    assert len(bundle.combined_hash) == 64
    assert "亚马逊 FBA 选品准则" in bundle.prompt_text


def test_ra_provider_keys_route_gpt_and_opus_through_foursapi() -> None:
    configured = RAnalysisProviderKeys(
        deepseek="deepseek-key",
        foursapi="foursapi-key",
        serper="serper-key",
        rainforest="rainforest-key",
        google_ads="google-ads-key",
    ).configured()

    assert configured["deepseek"] is True
    assert configured["gpt"] is True
    assert configured["opus"] is True
    assert configured["foursapi"] is True
    assert configured["serper"] is True
    assert configured["rainforest"] is True
    assert configured["google_ads"] is True
    assert "openai" not in configured


def test_ra_manifest_exposes_framework_api_without_execution_enablement() -> None:
    manifest = next(
        item for item in MODULE_MANIFESTS_V1 if item["module_key"] == "r.analysis"
    )

    assert manifest["api_namespace"] == "/r/analysis"
    assert manifest["no_api"] is False
    assert manifest["execution_provider_required"] is False
    assert manifest["external_dependencies"] == [
        "deepseek",
        "chatgpt",
        "claude_opus",
        "serper",
        "alibaba1688",
        "rainforest",
        "google_ads",
    ]
    assert set(manifest["data_boundary"]["writes"]) == {
        table_name for table_name, _label in RA_REQUIRED_TABLES
    }
    required_checks = manifest["release_requirements"]["required_checks"]
    assert "r-a real ai e2e pipeline pass" in required_checks
    assert "r-a provider key binding audit pass" in required_checks
    assert "r-a execution workers inactive" not in required_checks


def test_ra_framework_stages_expose_real_ai_pipeline() -> None:
    statuses = {stage["status"] for stage in RA_STAGES}
    ai_stages = {
        stage["id"]: stage["status"]
        for stage in RA_STAGES
        if stage["id"] in {"deepseek", "gpt", "opus", "rainforest_competition", "final_report"}
    }

    assert "framework_ready" in statuses
    assert ai_stages == {
        "deepseek": "real_provider_ready",
        "gpt": "real_provider_ready",
        "opus": "real_provider_ready",
        "rainforest_competition": "real_provider_ready",
        "final_report": "real_provider_ready",
    }
    assert all("running" not in stage["status"] for stage in RA_STAGES)


def test_ra_key_types_can_bind_to_analysis_module() -> None:
    expected_key_types = (
        "deepseek",
        "openai",
        "chatgpt",
        "claude_opus",
        "serp",
        "alibaba1688",
        "rainforest",
        "google_ads",
    )

    for key_type in expected_key_types:
        definition = key_type_definition(key_type)
        assert "R-A" in definition["scope"]
        assert key_type_allows_module(key_type, R_ANALYSIS_MODULE_ID)

    assert not key_type_allows_module("keepa", R_ANALYSIS_MODULE_ID)


def test_ra_secret_manager_prefers_analysis_bindings_for_required_services() -> None:
    assert (R_ANALYSIS_MODULE_ID, "deepseek") in SERVICE_BINDING_CANDIDATES["deepseek"]
    assert (R_ANALYSIS_MODULE_ID, "serp") in SERVICE_BINDING_CANDIDATES["serper"]
    assert (R_ANALYSIS_MODULE_ID, "serper") in SERVICE_BINDING_CANDIDATES["serper"]
    assert (R_ANALYSIS_MODULE_ID, "4sapi") in SERVICE_BINDING_CANDIDATES["openai"]
    assert (
        R_ANALYSIS_MODULE_ID,
        "alibaba1688",
    ) in SERVICE_BINDING_CANDIDATES["alibaba1688"]
    assert (R_ANALYSIS_MODULE_ID, "rainforest") in SERVICE_BINDING_CANDIDATES["rainforest"]
    assert (R_ANALYSIS_MODULE_ID, "google_ads") in SERVICE_BINDING_CANDIDATES["google_ads"]


def test_ra_provider_binding_resolves_keys_from_api_key_orchestration(monkeypatch) -> None:
    class FakeIsolationError(Exception):
        pass

    class FakeOrchestrationError(Exception):
        pass

    calls: list[tuple[str, str]] = []

    def fake_resolver(_db, *, org_id: str, module_id: str, key_alias: str):
        assert org_id == "org-ra"
        calls.append((module_id, key_alias))
        values = {
            (R_ANALYSIS_MODULE_ID, "deepseek"): "deepseek-secret",
            (R_ANALYSIS_MODULE_ID, "4sapi"): "foursapi-secret",
            (R_ANALYSIS_MODULE_ID, "serper"): "serper-secret",
            (R_ANALYSIS_MODULE_ID, "alibaba1688"): "alibaba-secret",
            (R_ANALYSIS_MODULE_ID, "rainforest"): "rainforest-secret",
            (R_ANALYSIS_MODULE_ID, "google_ads"): "google-ads-secret",
        }
        value = values.get((module_id, key_alias))
        if value is None:
            raise FakeOrchestrationError("missing")
        return SimpleNamespace(
            module_id=module_id,
            key_alias=key_alias,
            key_id=f"{key_alias}-id",
            url="https://api.example.test",
            header_value=f"Bearer {value}",
            query_param_value=None,
        )

    monkeypatch.setattr(
        "r_system_v2.core.secret_manager._backend_resolver",
        lambda: (fake_resolver, FakeIsolationError, FakeOrchestrationError),
    )
    binding = RAnalysisProviderBinding(
        org_id="org-ra",
        secret_manager=SecretManager(db_session=object()),
    )

    keys = binding.all_keys()
    status = binding.status()

    assert keys.deepseek == "deepseek-secret"
    assert keys.foursapi == "foursapi-secret"
    assert keys.serper == "serper-secret"
    assert keys.alibaba1688 == "alibaba-secret"
    assert keys.rainforest == "rainforest-secret"
    assert keys.google_ads == "google-ads-secret"
    assert status["supplier_cost_provider_ready"] is True
    assert status["competition_provider_ready"] is True
    assert status["google_ads_provider_ready"] is False
    assert status["routing"]["google_ads"] == "pending_basic_review"
    assert status["google_ads_review"]["runtime_status"] == "pending_basic_review"
    role_configured = {item["role"]: item["configured"] for item in status["roles"]}
    assert role_configured["gpt"] is True
    assert role_configured["opus"] is True
    assert role_configured["rainforest"] is True
    assert role_configured["google_ads"] is True
    google_ads_role = next(item for item in status["roles"] if item["role"] == "google_ads")
    assert google_ads_role["runtime_enabled"] is False
    assert google_ads_role["review_status"] == "pending_basic_review"
    assert (R_ANALYSIS_MODULE_ID, "4sapi") in calls


def test_google_ads_basic_review_gate_requires_manual_runtime_enable(monkeypatch) -> None:
    monkeypatch.delenv("RA_GOOGLE_ADS_BASIC_REVIEW_STATUS", raising=False)
    monkeypatch.delenv("RA_GOOGLE_ADS_ENABLE_REAL_CALLS", raising=False)

    pending = google_ads_runtime_gate(configured=True)

    assert pending["review_status"] == "pending_basic_review"
    assert pending["runtime_enabled"] is False
    assert pending["routing"] == "pending_basic_review"

    monkeypatch.setenv("RA_GOOGLE_ADS_BASIC_REVIEW_STATUS", "approved")
    approved_without_runtime = google_ads_runtime_gate(configured=True)

    assert approved_without_runtime["runtime_status"] == "approved_manual_enable_required"
    assert approved_without_runtime["runtime_enabled"] is False
    assert approved_without_runtime["routing"] == "manual_enable_required"

    monkeypatch.setenv("RA_GOOGLE_ADS_ENABLE_REAL_CALLS", "true")
    enabled = google_ads_runtime_gate(configured=True)

    assert enabled["runtime_status"] == "enabled"
    assert enabled["runtime_enabled"] is True
    assert enabled["routing"] == "google_ads_keyword_planner"
