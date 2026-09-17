"""A 系列(amz.ops)A0 的登记守卫、门禁、种子解析、凭据形状、探针——全部 unit,不碰库。"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- 登记


def test_module_is_registered_everywhere_and_org_gated() -> None:
    from backend.app.core.modules import MODULE_MANIFESTS_V1
    from backend.app.core.permissions import BASE_PERMISSION_REGISTRY_SEED
    from backend.app.services.module_registry import (
        AMAZON_ONLY_MODULE_KEYS,
        FACTORY_ONLY_MODULE_KEYS,
        INTL_TRADE_ONLY_MODULE_KEYS,
    )

    manifest = next(m for m in MODULE_MANIFESTS_V1 if m["module_key"] == "amz.ops")
    assert manifest["route_namespace"] == "/amz"
    assert manifest["api_namespace"] == "/amz"
    assert manifest["category"] == "business"
    assert manifest["denied_behavior"] == "show_locked"
    assert manifest["required_permissions"] == ["amz.ops.read"]
    seeded = {p["permission_key"] for p in BASE_PERMISSION_REGISTRY_SEED if p["module_key"] == "amz.ops"}
    assert seeded == {"amz.ops.read", "amz.ops.execute", "amz.ops.manage"}
    # 零交集:三份白名单两两不交。
    assert AMAZON_ONLY_MODULE_KEYS == {"amz.ops"}
    assert not (AMAZON_ONLY_MODULE_KEYS & INTL_TRADE_ONLY_MODULE_KEYS)
    assert not (AMAZON_ONLY_MODULE_KEYS & FACTORY_ONLY_MODULE_KEYS)
    # 数据边界里一列 org_id 都不该出现在 A 的表名里,表都以 amz_ 开头。
    for table in manifest["data_boundary"]["reads"] + manifest["data_boundary"]["writes"]:
        assert table.startswith("amz_")


def test_router_is_mounted_once_and_never_bare() -> None:
    source = (REPO / "backend/app/main.py").read_text(encoding="utf-8")
    assert source.count("app.include_router(amz_ops_router") == 1
    assert "app.include_router(amz_ops_router, prefix=APPLICATION_API_PREFIX)" in source
    assert '"amz-worker",' in source and '"amz-agents-worker",' in source


def test_models_are_imported_for_alembic_metadata() -> None:
    from backend.app import models
    from backend.app.modules.amz_series import models as amz_models

    for name in amz_models.__all__:
        assert getattr(models, name) is getattr(amz_models, name)


def test_amz_tables_never_carry_an_org_id_column() -> None:
    """家规 14:C18G 按 org_id 列自动过滤;A 的表带了这列,王创鑫在深圳上下文下就看不到店铺。"""
    from backend.app.modules.amz_series import models as amz_models

    for name in amz_models.__all__:
        table = getattr(amz_models, name).__table__
        assert table.name.startswith("amz_")
        assert "org_id" not in table.c, f"{table.name} 不能有 org_id 列"


def test_home_registry_has_amazon_cards_with_approvals_last() -> None:
    from backend.app.modules.home.factory_registry import AMAZON_CARDS, _BY_ORG_TYPE

    assert _BY_ORG_TYPE["amazon"] is AMAZON_CARDS
    assert [spec.card_id for spec in AMAZON_CARDS] == ["amz-stores", "amz-agents", "approvals"]
    assert AMAZON_CARDS[0].module_key == "amz.ops"


def test_migrations_exist_chain_and_are_in_manifest() -> None:
    versions = REPO / "backend/alembic/versions"
    tables = (versions / "20260915_01_amz_tables.py").read_text(encoding="utf-8")
    perms = (versions / "20260915_02_amz_permissions.py").read_text(encoding="utf-8")
    assert 'down_revision = "20260911_03_rd_remote_desktop"' in tables
    assert 'down_revision: str | Sequence[str] | None = "20260915_01_amz_tables"' in perms
    for name in ("amz_stores", "amz_store_grants", "amz_jobs", "amz_seed_imports", "amz_fx_rates", "amz_ad_search_terms", "amz_transactions"):
        assert name in tables
    assert 'sa.Column("org_id"' not in tables  # 家规 14
    manifest = json.loads((REPO / "migration_manifest.json").read_text(encoding="utf-8"))
    order = manifest["migration_order"]
    i = order.index("20260915_01_amz_tables")
    assert order[i : i + 7] == ["20260915_01_amz_tables", "20260915_02_amz_permissions", "20260916_01_amz_suggestions", "20260916_02_amz_work_log", "20260916_03_amz_reports", "20260916_04_amz_fact_sheets", "20260917_01_amz_images"]
    assert order[i + 7] == "20260917_02_amz_experience" and order[i + 8] == "20260917_03_amz_launches"
    launch_mig = (versions / "20260917_03_amz_launches.py").read_text(encoding="utf-8")
    assert 'down_revision = "20260917_02_amz_experience"' in launch_mig and 'sa.Column("org_id"' not in launch_mig
    exp_mig = (versions / "20260917_02_amz_experience.py").read_text(encoding="utf-8")
    assert 'down_revision = "20260917_01_amz_images"' in exp_mig and 'sa.Column("org_id"' not in exp_mig
    images_mig = (versions / "20260917_01_amz_images.py").read_text(encoding="utf-8")
    assert 'down_revision = "20260916_04_amz_fact_sheets"' in images_mig and 'sa.Column("org_id"' not in images_mig and "amz_image_briefs" in images_mig
    sheets_mig = (versions / "20260916_04_amz_fact_sheets.py").read_text(encoding="utf-8")
    assert 'down_revision = "20260916_03_amz_reports"' in sheets_mig and 'sa.Column("org_id"' not in sheets_mig and "amz_fact_sheets" in sheets_mig
    reports_mig = (versions / "20260916_03_amz_reports.py").read_text(encoding="utf-8")
    assert 'down_revision = "20260916_02_amz_work_log"' in reports_mig and 'sa.Column("org_id"' not in reports_mig
    for name in ("amz_sales_daily", "amz_sqp", "amz_report_runs"):
        assert name in reports_mig
    work_log_mig = (versions / "20260916_02_amz_work_log.py").read_text(encoding="utf-8")
    assert 'down_revision = "20260916_01_amz_suggestions"' in work_log_mig and "amz_work_log" in work_log_mig
    assert 'sa.Column("org_id"' not in work_log_mig
    from scripts import staging_stabilization

    assert staging_stabilization.EXPECTED_ALEMBIC_HEAD == order[-1]


# ---------------------------------------------------------------- 组织类型门


def _org(org_type: str) -> SimpleNamespace:
    return SimpleNamespace(org_id="org_" + "0" * 32, org_type=org_type, status="active")


def test_control_center_gate_by_org_type() -> None:
    from backend.app.services.module_control_center import _module_allowed_for_organization
    from backend.app.services.module_registry import list_module_manifests_snapshot

    by_key = {m.module_key: m for m in list_module_manifests_snapshot()}
    amz, mfg, k, sm = by_key["amz.ops"], by_key["mfg.inventory"], by_key["k.product_knowledge"], by_key["sm.social"]
    # amazon 组织:只有 amz;任何贸易/制造模块都不给。
    assert _module_allowed_for_organization(_org("amazon"), amz)
    assert not _module_allowed_for_organization(_org("amazon"), k)
    assert not _module_allowed_for_organization(_org("amazon"), sm)
    assert not _module_allowed_for_organization(_org("amazon"), mfg)
    # store / factory 与今天完全一样。
    assert _module_allowed_for_organization(_org("store"), k)
    assert _module_allowed_for_organization(_org("store"), sm)
    assert not _module_allowed_for_organization(_org("store"), amz)
    assert not _module_allowed_for_organization(_org("store"), mfg)
    assert _module_allowed_for_organization(_org("factory"), mfg)
    assert not _module_allowed_for_organization(_org("factory"), amz)
    assert not _module_allowed_for_organization(_org("factory"), k)
    # 核心模块人人有。
    assert _module_allowed_for_organization(_org("amazon"), by_key["core.dashboard"])


def test_org_type_enum_and_rule_include_amazon() -> None:
    from backend.app.schemas.organization import OrganizationType, get_organization_type_constraints

    assert OrganizationType.AMAZON.value == "amazon"
    rules = {rule.org_type for rule in get_organization_type_constraints().rules}
    assert OrganizationType.AMAZON in rules


# ---------------------------------------------------------------- 店铺级门


class _FakeDb:
    def __init__(self, *, grant=None, store=None, has_any_grant: bool = False) -> None:
        self._grant = grant
        self._store = store
        self._has_any = has_any_grant

    def scalar(self, _query):
        return "01us" if self._has_any else None

    def get(self, model, key):
        from backend.app.modules.amz_series.models import AmzStore, AmzStoreGrant

        if model is AmzStore:
            return self._store
        if model is AmzStoreGrant:
            return self._grant
        return None


def _user(role: str, user_id: int = 168) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=role, is_active=True)


def test_require_amz_access_only_owner_bypasses() -> None:
    from backend.app.modules.amz_series.deps import require_amz_access

    assert require_amz_access(db=_FakeDb(), user=_user("owner")).role == "owner"
    # 王维:super_admin,没有任何店铺授权 → 403。SM 的门会放他,A 的门刻意不放。
    with pytest.raises(HTTPException) as exc:
        require_amz_access(db=_FakeDb(), user=_user("super_admin"))
    assert exc.value.status_code == 403
    assert require_amz_access(db=_FakeDb(has_any_grant=True), user=_user("super_admin", 2)).id == 2


def test_require_store_ranks_roles_and_owner_is_grant() -> None:
    from backend.app.modules.amz_series.deps import require_store

    store = SimpleNamespace(store_code="05us", status="active")
    view_grant = SimpleNamespace(role="view")
    dep_view = require_store("view")
    dep_operate = require_store("operate")
    dep_grant = require_store("grant")

    access = dep_view("05US", db=_FakeDb(store=store, grant=view_grant), user=_user("viewer", 300))
    assert access.store is store and access.role == "view"
    with pytest.raises(HTTPException) as exc:
        dep_operate("05us", db=_FakeDb(store=store, grant=view_grant), user=_user("viewer", 300))
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        dep_view("05us", db=_FakeDb(store=store, grant=None), user=_user("super_admin", 168))
    assert exc.value.status_code == 403
    assert dep_grant("05us", db=_FakeDb(store=store, grant=None), user=_user("owner", 1)).role == "grant"
    with pytest.raises(HTTPException) as exc:
        dep_view("02us", db=_FakeDb(store=None), user=_user("owner", 1))
    assert exc.value.status_code == 404
    with pytest.raises(ValueError):
        require_store("admin")


# ---------------------------------------------------------------- 名单


def test_catalog_is_four_companies_five_stores_and_no_store_02() -> None:
    from backend.app.modules.amz_series.catalog import COMPANIES, STORES, STORE_CODES
    from backend.app.schemas.organization import ORG_ID_PATTERN

    assert len(COMPANIES) == 4 and len({c.org_id for c in COMPANIES}) == 4
    assert all(ORG_ID_PATTERN.match(c.org_id) for c in COMPANIES)
    assert STORE_CODES == ("01us", "01de", "03us", "04us", "05us")
    assert "02us" not in STORE_CODES
    assert {s.company.org_id for s in STORES} == {c.org_id for c in COMPANIES}
    assert next(s for s in STORES if s.store_code == "01de").currency == "EUR"
    assert next(s for s in STORES if s.store_code == "01de").region == "eu"
    # 心跳名 worker_name 是 String(64)。
    for code in STORE_CODES:
        assert len(f"amz-worker:{code}:brand_analytics_sqp") < 64


# ---------------------------------------------------------------- 种子解析


def test_seed_parsers_handle_us_and_german_transaction_rows() -> None:
    from backend.app.modules.amz_series import seed_import as si

    assert si._parse_posted("Aug 1, 2026 2:48:39 AM PDT", german=False) == datetime.fromisoformat("2026-08-01T09:48:39+00:00")
    assert si._parse_posted("31.07.2026 23:35:56 UTC", german=True) == datetime.fromisoformat("2026-07-31T23:35:56+00:00")
    assert si._parse_posted("", german=False) is None
    assert si._dec("1.234,56", german=True) == Decimal("1234.56")
    assert si._dec("1,234.56") == Decimal("1234.56")
    assert si._dec("-9.99") == Decimal("-9.99")
    assert si._dec("") == Decimal(0)

    store = SimpleNamespace(store_code="01de", currency="EUR")
    headers = ["Datum/Uhrzeit", "Typ", "Gesamt"]
    rows = [{
        "Datum/Uhrzeit": "31.07.2026 23:35:56 UTC", "Abrechnungsnummer": "1", "Typ": "Bestellung", "Bestellnummer": "305-1",
        "SKU": "DE-LYQ-03", "Beschreibung": "B013", "Menge": "1", "Marketplace": "amazon.de", "Versand": "Amazon",
        "Umsätze": "24,33", "Produktumsatzsteuer": "4,62", "Gutschrift für Versandkosten": "0", "Rabatte aus Werbeaktionen": "0",
        "Einbehaltene Steuer auf Marketplace": "-4,62", "Verkaufsgebühren": "-4,33", "Gebühren zu Versand durch Amazon": "-3,68",
        "Andere Transaktionsgebühren": "0", "Andere": "0", "Gesamt": "16,32",
    }]
    class _Db:
        def get(self, *_): return None
        def get_bind(self): return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    parsed = list(si._txn_rows(_Db(), store, rows, headers=headers))
    assert len(parsed) == 1
    row = parsed[0]
    assert row["total"] == Decimal("16.32") and row["currency"] == "EUR"
    assert row["fx_source"] == "seed_fixed" and row["total_usd"] == (Decimal("16.32") * si.DEFAULT_EUR_USD).quantize(Decimal("0.01"))
    assert row["txn_type"] == "Bestellung" and row["fba_fees"] == Decimal("-3.68")
    # 同一行两次 → 同一个 row_key(幂等靠它)。
    assert row["row_key"] == list(si._txn_rows(_Db(), store, rows, headers=headers))[0]["row_key"]


def test_seed_ads_rows_use_chinese_headers_and_stable_row_key() -> None:
    from backend.app.modules.amz_series import seed_import as si

    store = SimpleNamespace(store_code="03us", currency="USD")
    row = {
        "日期": "2026-08-01", "广告组合名称": "No Portfolio", "货币": "USD", "广告活动名称": "黑色泵 自动0712", "广告组名称": "黑色泵 自动0712",
        "投放": "loose-match", "匹配类型": "-", "客户搜索词": "camping shower", "展示量": "1,234", "点击量": "12", "单次点击成本 (CPC)": "0.73",
        "花费": "8.76", "7天总销售额": "56.97", "7天总订单数(#)": "2", "7天总销售量(#)": "2", "7天内广告SKU销售量(#)": "2",
        "7天内其他SKU销售量(#)": "0", "7天内广告SKU销售额": "56.97", "7天内其他SKU销售额": "0",
    }
    parsed = list(si._ads_rows(store, [row]))
    assert parsed[0]["report_date"] == date(2026, 8, 1)
    assert parsed[0]["impressions"] == 1234 and parsed[0]["clicks"] == 12
    assert parsed[0]["spend"] == Decimal("8.76") and parsed[0]["orders_7d"] == 2
    assert parsed[0]["row_key"] == list(si._ads_rows(store, [row]))[0]["row_key"]
    assert si.ADS_FILE.match("ads__01de.csv") and si.TXN_FILE.match("txn__03us__2026-08.csv")
    assert si.ADS_FILE.match("ads__02us.csv") is not None  # 文件名合法,但 02us 由 catalog.store_spec 拦下
    assert si.ADS_FILE.match("ads__01us.xlsx") is None


# ---------------------------------------------------------------- 凭据形状 / 密钥登记


def test_amazon_credential_json_shape_validation() -> None:
    from backend.app.services.api_key_orchestration import validate_api_key_value

    good_sp = json.dumps({"client_id": "amzn1.application-oa2-client.x", "client_secret": "s", "refresh_token": "Atzr|x", "region": "NA"})
    assert validate_api_key_value(key_type="amazon_sp_api", key_value=good_sp)["valid"] is True
    assert validate_api_key_value(key_type="sp_api", key_value=good_sp)["valid"] is True
    assert validate_api_key_value(key_type="amazon_sp_api", key_value="not json")["reason"] == "json_invalid"
    assert validate_api_key_value(key_type="amazon_sp_api", key_value=json.dumps({"client_id": "a"}))["reason"] == "json_missing_fields"
    assert validate_api_key_value(key_type="amazon_sp_api", key_value=json.dumps({"client_id": "a", "client_secret": "b", "refresh_token": "c", "region": "us"}))["reason"] == "region_invalid"
    good_ads = json.dumps({"client_id": "a", "client_secret": "b", "refresh_token": "c", "region": "eu", "profile_ids": ["123"]})
    assert validate_api_key_value(key_type="amazon_ads_api", key_value=good_ads)["valid"] is True
    assert validate_api_key_value(key_type="amazon_ads_api", key_value=good_ads.replace('["123"]', "[]"))["reason"] == "profile_ids_empty"


def test_key_registry_has_amazon_types_bound_to_amz_module() -> None:
    from backend.app.core.key_registry import key_type_definition, list_key_type_definitions, normalize_key_type

    types = {d["type"] for d in list_key_type_definitions()}
    assert {"amazon_sp_api", "amazon_ads_api"} <= types
    assert key_type_definition("amazon_sp_api")["module_ids"] == ["amz.ops"]
    assert key_type_definition("amazon_ads_api")["auth_type"] == "oauth_json"
    assert "amz.ops" in key_type_definition("keepa")["module_ids"]
    assert normalize_key_type("spapi") == "amazon_sp_api" and normalize_key_type("amazon_ads") == "amazon_ads_api"


# ---------------------------------------------------------------- 探针


def _probe_target(key_type: str, secret: dict) -> object:
    from backend.app.modules.key_health.probes import ProbeTarget

    return ProbeTarget(
        key_id="key_" + "0" * 32, org_id="org_" + "0" * 32, name="t", url="https://sellingpartnerapi-na.amazon.com",
        key_hash_prefix="abcdef123456", key_type=key_type, aliases=(), secret_value=json.dumps(secret),
    )


def test_amazon_probes_refresh_lwa_then_read_cheapest_endpoint() -> None:
    from backend.app.modules.key_health.probes import adapter_for_target, probe_target

    sp = _probe_target("amazon_sp_api", {"client_id": "c", "client_secret": "s", "refresh_token": "r", "region": "na"})
    ads = _probe_target("amazon_ads_api", {"client_id": "c", "client_secret": "s", "refresh_token": "r", "region": "eu", "profile_ids": ["111"]})
    assert adapter_for_target(sp) == "amazon_sp_api" and adapter_for_target(ads) == "amazon_ads_api"

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.host}{request.url.path}")
        if request.url.host == "api.amazon.com":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path == "/reports/2021-06-30/reports":
            assert request.headers["x-amz-access-token"] == "tok"
            return httpx.Response(200, json={"reports": []})
        if request.url.path == "/v2/profiles":
            assert request.headers["Authorization"] == "Bearer tok"
            return httpx.Response(200, json=[{"profileId": 222}])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    result = probe_target(sp, enforce_public_network=False, transport=transport)
    assert result.status == "healthy" and result.reason_code == "reports_list_ok"
    assert seen[:2] == ["POST api.amazon.com/auth/o2/token", "GET sellingpartnerapi-na.amazon.com/reports/2021-06-30/reports"]

    result = probe_target(ads, enforce_public_network=False, transport=transport)
    assert result.status == "invalid" and result.reason_code == "profile_not_in_account"
    assert result.details["missing_profile_ids"] == ["111"]
    assert "GET advertising-api-eu.amazon.com/v2/profiles" in seen

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    result = probe_target(sp, enforce_public_network=False, transport=httpx.MockTransport(refuse))
    assert result.status == "invalid" and result.reason_code == "oauth_refresh_rejected"

    bad = _probe_target("amazon_sp_api", {"client_id": "c"})
    result = probe_target(bad, enforce_public_network=False, transport=transport)
    assert result.status == "malformed" and result.reason_code == "oauth_payload_incomplete"


# ---------------------------------------------------------------- A2:规则引擎(纯函数部分)


def test_product_line_and_season_calendar() -> None:
    from backend.app.modules.amz_series.rules import PRODUCT_LINE_LABELS, SEASON_CALENDAR, product_line_of

    assert product_line_of("蓝色泵 广泛 0804") == "pump"
    assert product_line_of("热水棒 自动0615") == "heater"
    assert product_line_of("175 太阳能关键词 广泛 0822") == "flash"
    assert product_line_of("磨甲器 多关键词 0514") == "nail"
    assert product_line_of("DE-LYQ-01-900自动") == "pump"
    assert product_line_of("随便什么") == "other"
    assert set(SEASON_CALENDAR) == {"pump", "heater", "bundle"} and set(PRODUCT_LINE_LABELS) >= {"pump", "heater"}


def test_suggestion_draft_dedupe_key_is_stable_per_store_action_subject() -> None:
    from backend.app.modules.amz_series.rules import SuggestionDraft

    a = SuggestionDraft("D", "03us", "harvest", "warn", "t", "w", "p", "camping shower")
    b = SuggestionDraft("D", "03us", "harvest", "warn", "t2", "w2", "p2", "camping shower")
    c = SuggestionDraft("D", "04us", "harvest", "warn", "t", "w", "p", "camping shower")
    assert a.dedupe_key == b.dedupe_key and a.dedupe_key != c.dedupe_key and len(a.dedupe_key) == 64


def test_rules_and_jobs_are_registered() -> None:
    from backend.app.modules.amz_series import jobs, rules

    assert len(rules.RULES) == 7
    from backend.app.modules.amz_series import rules_cross

    assert [r.__name__ for r in rules_cross.CROSS_RULES] == ["rule_listing_cvr_gap", "rule_screen_ctr_gap"]
    from backend.app.modules.amz_series import rules_c

    assert [r.__name__ for r in rules_c.C_RULES] == ["rule_detail_page_leak", "rule_share_drop", "rule_weekly_brief"]
    assert jobs.JOB_INTERVALS == {"rules_daily": 86400, "sales_traffic": 86400, "sqp_weekly": 7 * 86400, "image_lookback": 86400, "experience_weekly": 7 * 86400, "launch_daily": 86400}
    assert jobs.API_JOBS == {"sales_traffic", "sqp_weekly"} and set(jobs.HANDLERS) == set(jobs.JOB_INTERVALS)
    assert jobs.heartbeat_name("01de", "rules_daily") == "amz-worker:01de:rules_daily"
    compose = (REPO / "docker-compose.production.yml").read_text(encoding="utf-8")
    assert "backend.app.modules.amz_series.worker_main" in compose and "container_name: amz-worker" in compose
    # A2 表也不能带 org_id 列(家规 14)
    migration = (REPO / "backend/alembic/versions/20260916_01_amz_suggestions.py").read_text(encoding="utf-8")
    assert 'sa.Column("org_id"' not in migration
    assert 'down_revision = "20260915_02_amz_permissions"' in migration


# ---------------------------------------------------------------- 人物档案(焊死)


def test_personas_are_named_and_hard_gated() -> None:
    from backend.app.modules.amz_series.constants import EMPLOYEE_GENDERS, EMPLOYEE_NAMES
    from backend.app.modules.amz_series.persona import PERSONAS, display_name, enforce_style, system_prompt

    assert EMPLOYEE_NAMES == {"A": "殷笑笑", "B": "殷熊", "C": "殷长辰", "D": "殷素素"}
    assert EMPLOYEE_GENDERS == {"A": "女", "B": "男", "C": "男", "D": "女"}
    for key, persona in PERSONAS.items():
        assert persona.name == EMPLOYEE_NAMES[key] and persona.gender == EMPLOYEE_GENDERS[key]
        prompt = system_prompt(key, extra_context="店铺:03us · 数据截至 2026-09-14")
        assert persona.name in prompt and persona.character in prompt and "刷单" in prompt and "K / I / M" in prompt
        assert "数据截至 2026-09-14" in prompt
    assert display_name("A") == "殷笑笑 · Listing 文案"
    # 殷熊:不用表情、不用「~」「呀」
    out = enforce_style("B", "老板~这张图不对呀 😊😊,几何错了。")
    assert "~" not in out and "呀" not in out and "😊" not in out and "几何错了" in out
    # 殷笑笑:最多两个允许的表情,称呼带 ~
    out = enforce_style("A", "老板 我看了标题 ✨✨✨ 💡 🍔")
    assert out.count("✨") == 2 and "💡" not in out and "🍔" not in out and "老板~" in out
    # 殷素素:禁语被拿掉,最多一个温柔表情
    out = enforce_style("D", "老板,必须马上改,完蛋了 🌷🌷")
    assert "必须" not in out and "马上" not in out and "完蛋" not in out and out.count("🌷") == 1
    # 长度硬顶
    assert len(enforce_style("C", "长" * 5000)) <= 900


# ---------------------------------------------------------------- A2:事实表「够不够」(纯函数)


def test_sufficiency_checklists_fail_closed_and_flag_contradictions_and_questions() -> None:
    from backend.app.modules.amz_series import sufficiency
    from backend.app.modules.amz_series.fact_sheets import normalize_facts

    empty = sufficiency.judge_code({}, product_line="pump")
    assert all(not u["ok"] for u in empty["uses"].values())
    assert "它是什么" in empty["uses"]["copy"]["missing"] and "成本:出厂价(元)" in empty["uses"]["pnl"]["missing"]
    assert len(empty["questions"]) == 5  # 泵类五个常见预期一个都没答

    facts = normalize_facts(
        {
            "is": "便携淋浴泵,7800mAh,IPX8 防水,不加热,自带水温显示",
            "how_it_works": "整机入水才抽水,三档水压,一次充电洗 60 分钟",
            "is_not": "不是热水器,不加热;别入水,泵头露出",
            "specs": {"battery_mah": "7800", "ip_rating": "IPX8", "dimensions_cm": "10x10x20", "weight_g": "650"},
            "indicators": "红灯充电,绿灯充满,屏幕显示水温 °F",
            "package": "泵、软管、花洒、挂钩、USB-C 线",
            "audience": "露营、宠物洗澡、冲沙",
            "misreadings": "买家以为能加热",
            "cost": {"factory_cny": "60", "freight_cny": "7", "price_usd": "32.99"},
            "competitor_asins": "B0AAAAAAA1, b0bbbbbbb2",
            "notes": "",
        }
    )
    assert facts["competitor_asins"] == ["B0AAAAAAA1", "B0BBBBBBB2"] and facts["cost"]["price_usd"] == 32.99
    full = sufficiency.judge_code(facts, product_line="pump")
    assert all(u["ok"] for u in full["uses"].values())
    assert full["questions"] == []
    assert any("IPX7/IPX8" in c for c in full["contradictions"])  # 写了 IPX8 又说别入水

    merged = sufficiency.judge(facts, product_line="pump", title="泵", org_id="org_x", with_model=True, call=lambda messages, *, org_id: {"content": '{"contradictions": ["整机入水 vs 别入水"], "questions": ["软管多长?"], "missing_hints": {"copy": ["缺关键词"], "image": [], "faq": [], "pnl": []}}'})
    assert merged["ready"] == {"copy": True, "image": True, "faq": True, "pnl": True}
    assert merged["model"]["questions"] == ["软管多长?"] and merged["model"]["missing_hints"]["copy"] == ["缺关键词"]
    broken = sufficiency.judge(facts, product_line="pump", title="泵", org_id="org_x", with_model=True, call=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert broken["model"] is None and "down" in broken["model_error"] and broken["ready"]["copy"] is True  # 模型挂了判定不变
    assert sufficiency.is_ready(broken, "pnl") and not sufficiency.is_ready({}, "pnl")

    from r_system_v2.ra import quota_ledger as ql

    assert ql.PROVIDER_AMZ_SUFFICIENCY in ql.DEFAULT_DAILY_BUDGETS and ql.PROVIDER_AMZ_SUFFICIENCY in ql.BUDGET_ENV_NAMES


# ---------------------------------------------------------------- A4:经验库(纯函数)


def test_experience_judge_drift_and_draft_advice() -> None:
    from decimal import Decimal as _D

    from backend.app.modules.amz_series import experience as ex
    from backend.app.modules.amz_series.rules import SuggestionDraft

    W = ex.Window
    assert ex.judge("harvest", W(3, 1, _D(1), _D(10))) == "na"  # 点击太少不硬判
    assert ex.judge("harvest", W(20, 3, _D(10), _D(60))) == "right"
    assert ex.judge("harvest", W(20, 0, _D(10), _D(0))) == "wrong"
    assert ex.judge("negative", W(20, 0, _D(10), _D(0))) == "right"
    assert ex.judge("negative", W(20, 2, _D(10), _D(50))) == "wrong"
    assert ex.judge("bid_down", W(30, 1, _D(40), _D(50))) == "right"  # ACOS 80% 还是倒挂
    assert ex.judge("bid_down", W(30, 5, _D(10), _D(100))) == "wrong"
    assert ex.judge("listing_cvr_gap", W(99, 9, _D(1), _D(1))) == "na"

    # 一次一档、有上限、永不低于出厂值
    assert ex.drift_value(3, default=3, step=1, cap=5, precision=30, low=50, high=85) == 4
    assert ex.drift_value(5, default=3, step=1, cap=5, precision=10, low=50, high=85) == 5
    assert ex.drift_value(4, default=3, step=1, cap=5, precision=90, low=50, high=85) == 3
    assert ex.drift_value(3, default=3, step=1, cap=5, precision=95, low=50, high=85) == 3
    assert ex.drift_value(4, default=3, step=1, cap=5, precision=70, low=50, high=85) == 4

    draft = SuggestionDraft("D", "03us", "harvest", "warn", "t", "w", "p", "s", {"term": "x"})
    ex.apply_to_draft(draft, {"notes": [], "downgrade": False})
    assert draft.severity == "warn" and "experience" not in draft.evidence
    ex.apply_to_draft(draft, {"notes": ["03us 的收割 6 条里 1 条成立"], "downgrade": True})
    assert draft.severity == "info" and draft.evidence["experience"] == ["03us 的收割 6 条里 1 条成立"] and draft.evidence["experience_downgraded"] is True


# ---------------------------------------------------------------- A4:推新流程与评论簇(纯函数)


def test_launch_pnl_gate_day45_and_stock() -> None:
    from backend.app.modules.amz_series import launches as ln

    facts = {"cost": {"factory_cny": 60, "freight_cny": 7, "price_usd": 32.99}}
    missing = ln.compute_pnl({"price_usd": 32.99}, facts)
    assert missing["ok"] is False and missing["missing"] == ["FBA 配送费(美元)"]
    pnl = ln.compute_pnl({"price_usd": 32.99, "fba_fee_usd": 6}, facts)
    # 32.99 − 4.95 佣金 − 6 FBA − 9.31 出厂头程 − 8.25 推新广告 − 3.30 促销退款 ≈ 1.18,低于 $4 线
    assert pnl["ok"] is False and abs(pnl["margin_usd"] - 1.18) < 0.02 and pnl["floor_usd"] == 4.0
    assert pnl["breakeven_price_usd"] > 32.99  # 要卖到这个价才过线
    assert ln.compute_pnl({"price_usd": 49.99, "fba_fee_usd": 6}, facts)["ok"] is True

    assert ln.stock_days({"fba_units": 300, "expected_daily_units": 5}) == 60.0
    assert ln.stock_days({"fba_units": 300}) is None

    assert ln.judge_day45({"reviews": 20, "cvr_pct": 12.0, "main_rank": 8})["result"] == "pass"
    inc = ln.judge_day45({"reviews": 20, "cvr_pct": None, "main_rank": 8})
    assert inc["result"] == "incomplete" and inc["missing"]
    fail = ln.judge_day45({"reviews": 6, "cvr_pct": 7.5, "main_rank": 55, "main_term_click_share_pct": 0.4}, pits_expectation_share_pct=45.0)
    links = [b["link"] for b in fail["breaks"]]
    assert fail["result"] == "fail" and links == ["词", "预期", "评论"]
    assert "绝不做任何激励评论" in fail["breaks"][2]["fix"]
    assert [b["link"] for b in ln.judge_day45({"reviews": 30, "cvr_pct": 15.0, "main_rank": 40, "main_term_click_share_pct": 3.0})["breaks"]] == ["主图"]


def test_review_paste_splitting_and_keyword_fallback() -> None:
    from backend.app.modules.amz_series import reviews as rv

    raw = "2星: It does not heat the water at all\n\n★ leaked after two days\n\n5/5 great for camping\n\nok"
    items = rv.split_paste(raw)
    assert items == [(2, "It does not heat the water at all"), (1, "leaked after two days"), (5, "great for camping")]
    assert rv.fallback_cluster("It does not heat the water") == ("expectation", "以为能加热")
    assert rv.fallback_cluster("box arrived damaged, pump missing") == ("logistics", "到货损坏 / 缺件")
    assert rv.fallback_cluster("stopped working after a week") == ("defect", "用几次就坏")
    assert rv.fallback_cluster("nice color") == ("other", "其他")
    from r_system_v2.ra import quota_ledger as ql

    assert ql.PROVIDER_AMZ_REVIEWS in ql.DEFAULT_DAILY_BUDGETS and ql.PROVIDER_AMZ_REVIEWS in ql.BUDGET_ENV_NAMES
