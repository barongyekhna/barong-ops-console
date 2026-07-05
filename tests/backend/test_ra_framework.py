from backend.app.core.modules import MODULE_MANIFESTS_V1
from r_system_v2.ra.framework import RA_REQUIRED_TABLES, RA_STAGES
from r_system_v2.ra.providers import RAnalysisProviderKeys
from r_system_v2.ra.skill_loader import (
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


def test_ra_provider_keys_route_gpt_and_opus_through_foursapi() -> None:
    configured = RAnalysisProviderKeys(
        deepseek="deepseek-key",
        foursapi="foursapi-key",
        serper="serper-key",
    ).configured()

    assert configured["deepseek"] is True
    assert configured["gpt"] is True
    assert configured["opus"] is True
    assert configured["foursapi"] is True
    assert configured["serper"] is True
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
    ]
    assert set(manifest["data_boundary"]["writes"]) == {
        table_name for table_name, _label in RA_REQUIRED_TABLES
    }
    assert "r-a execution workers inactive" in manifest["release_requirements"][
        "required_checks"
    ]


def test_ra_framework_stages_are_non_executing_skeleton() -> None:
    statuses = {stage["status"] for stage in RA_STAGES}

    assert "framework_ready" in statuses
    assert "pending_integration" in statuses
    assert all("running" not in stage["status"] for stage in RA_STAGES)
