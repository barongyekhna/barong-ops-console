"""SM 系列(sm.social)单元守卫。

钉住的是规矩，不是实现细节：
- 登记点漏一处 = 隐身或测试红（manifest / 权限种子 / 组织门 / 内容台源表 / 主页卡 / 台账）
- 渠道档案是硬约束（配比和为 100、Pinterest 0 标签、IG ≤5）
- 排期器确定性 + 工厂/品牌不连发 + 配比偏差 ≤10 点 + 冷却
- 写手输出解析不「顺手修正」
- facts_used 解析、口径黑名单、平台规则进审计
- 迁移单头 + 清单收录
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- 登记


def test_module_is_registered_everywhere_and_org_gated() -> None:
    from backend.app.core.modules import MODULE_MANIFESTS_V1
    from backend.app.core.permissions import BASE_PERMISSION_REGISTRY_SEED
    from backend.app.services.module_control_center import TRADE_ONLY_MODULE_IDS
    from backend.app.services.module_registry import INTL_TRADE_ONLY_MODULE_KEYS

    manifest = next(m for m in MODULE_MANIFESTS_V1 if m["module_key"] == "sm.social")
    assert manifest["route_namespace"] == "/sm"
    assert manifest["api_namespace"] == "/sm"
    assert manifest["category"] == "business"
    assert manifest["denied_behavior"] == "show_locked"
    seeded = {p["permission_key"] for p in BASE_PERMISSION_REGISTRY_SEED if p["module_key"] == "sm.social"}
    assert seeded == {"sm.social.read", "sm.social.execute", "sm.social.manage"}
    assert "sm.social" in INTL_TRADE_ONLY_MODULE_KEYS
    assert "sm.social" in TRADE_ONLY_MODULE_IDS


def test_router_is_mounted_once_and_never_bare() -> None:
    source = (REPO / "backend/app/main.py").read_text(encoding="utf-8")
    assert source.count("app.include_router(sm_social_router") == 1
    assert "app.include_router(sm_social_router, prefix=APPLICATION_API_PREFIX)" in source


def test_content_desk_has_social_as_third_source_with_external_publish_unit() -> None:
    from backend.app.modules.content_desk.sources import SOURCE_BY_KEY

    social = SOURCE_BY_KEY["social"]
    assert social.kind_column == "post_kind"
    assert social.parent_fk == "slot_id"
    assert social.publish_unit == "external"
    assert social.review_requires_clean is True
    assert social.manage_permission == "sm.social.manage"
    assert social.review_permission == "sm.social.execute"


def test_publishing_skips_external_sources_and_refuses_to_dispatch() -> None:
    source = (REPO / "backend/app/modules/content_desk/publishing.py").read_text(encoding="utf-8")
    assert 'if source.publish_unit == "external":' in source
    assert "社媒帖子不在内容台派发" in source


def test_home_card_is_registered_before_approvals() -> None:
    from backend.app.modules.home.registry import STORE_CARDS

    ids = [spec.card_id for spec in STORE_CARDS]
    assert "sm-todo" in ids
    assert ids[-1] == "approvals", "approvals 必须排最后(唯一带语句超时的卡)"
    spec = next(s for s in STORE_CARDS if s.card_id == "sm-todo")
    assert spec.module_key == "sm.social"
    assert spec.needs_target_org is False  # 表带 workspace_key，靠 scope 隔离


def test_writer_has_a_quota_bucket() -> None:
    from r_system_v2.ra import quota_ledger

    assert quota_ledger.PROVIDER_SM_WRITER in quota_ledger.DEFAULT_DAILY_BUDGETS
    assert quota_ledger.PROVIDER_SM_WRITER in quota_ledger.BUDGET_ENV_NAMES
    assert quota_ledger.daily_budget(quota_ledger.PROVIDER_SM_WRITER) > 0


def test_models_are_imported_for_alembic_metadata() -> None:
    from backend.app import models
    from backend.app.modules.sm_series.models import SmPost

    assert models.SmPost is SmPost


# ---------------------------------------------------------------- 迁移


def test_migrations_exist_chain_and_are_in_manifest() -> None:
    versions = REPO / "backend/alembic/versions"
    tables = (versions / "20260906_01_sm_social_tables.py").read_text(encoding="utf-8")
    perms = (versions / "20260906_02_sm_social_permissions.py").read_text(encoding="utf-8")
    assert 'down_revision = "20260905_01_w_traffic"' in tables
    assert 'down_revision: str | Sequence[str] | None = "20260906_01_sm_social_tables"' in perms
    for name in ("sm_channels", "sm_calendar_slots", "sm_posts", "sm_media_usage", "sm_image_requests", "sm_rejections", "sm_generation_jobs"):
        assert name in tables
    manifest = json.loads((REPO / "migration_manifest.json").read_text(encoding="utf-8"))
    assert manifest["migration_order"][-2:] == ["20260906_01_sm_social_tables", "20260906_02_sm_social_permissions"]
    from scripts import staging_stabilization

    assert staging_stabilization.EXPECTED_ALEMBIC_HEAD == "20260906_02_sm_social_permissions"


# ---------------------------------------------------------------- 档案


def test_profiles_are_hard_constraints() -> None:
    from backend.app.modules.sm_series.profiles import PLATFORM_PROFILES, validate_profiles

    assert validate_profiles() == []
    assert PLATFORM_PROFILES["pinterest"].hashtags_max == 0
    assert PLATFORM_PROFILES["instagram"].hashtags_max <= 5
    assert PLATFORM_PROFILES["facebook"].link_mode == "first_comment"
    assert PLATFORM_PROFILES["instagram"].link_mode == "bio_only"
    for prof in PLATFORM_PROFILES.values():
        assert sum(prof.pillar_mix.values()) == 100


def test_every_pillar_platform_pair_that_gets_scheduled_has_an_image_requirement() -> None:
    from backend.app.modules.sm_series.constants import PILLARS
    from backend.app.modules.sm_series.profiles import PLATFORM_PROFILES, image_requirement

    for platform, prof in PLATFORM_PROFILES.items():
        for pillar in PILLARS:
            if prof.pillar_mix.get(pillar, 0) > 0:
                assert image_requirement(pillar, platform) is not None, (pillar, platform)


# ---------------------------------------------------------------- 排期器


def _inventory(*, products: int = 3, guides: int = 4, facts: int = 1, factory_photos: int = 0, brand: int = 0):
    from backend.app.modules.sm_series.inventory import FactSource, GuideSource, InventorySnapshot, ProductSource

    approved = datetime(2026, 8, 1, tzinfo=timezone.utc)
    prods = [
        ProductSource(
            product_id=uuid4(), sku=f"SKU-{i:03d}", name=f"Product {i}", public_url=f"https://x/product/p{i}/",
            stock_status="instock", approved_at=approved, brand_clean=True,
            asset_counts={"main": 1, "gallery": 4, "description": 2},
            last_posted={"pinterest": None, "instagram": None, "facebook": None},
        )
        for i in range(products)
    ]
    gds = [
        GuideSource(
            item_id=uuid4(), cluster_id=uuid4(), seed_product_id=prods[0].product_id if prods else None,
            title=f"Guide {i}", item_type="hub", public_url=f"https://x/guide-{i}/", section_count=5,
            published_at=approved, last_posted={"pinterest": None, "instagram": None, "facebook": None},
        )
        for i in range(guides)
    ]
    fcs = [
        FactSource(fact_id=uuid4(), topic=f"topic {i}", claim=f"claim {i}", product_ids=[], approved_at=approved,
                   last_posted={"pinterest": None, "instagram": None, "facebook": None})
        for i in range(facts)
    ]
    return InventorySnapshot(products=prods, guides=gds, facts=fcs, factory_photo_count=factory_photos, brand_asset_count=brand)


def _ctx(inv=None, created_days_ago: int = 60):
    from backend.app.modules.sm_series.planner import PlanContext

    created = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    return PlanContext(inventory=inv or _inventory(), channels={"pinterest": created, "instagram": created, "facebook": created})


def test_planner_is_deterministic() -> None:
    from backend.app.modules.sm_series.planner import compute_slots

    inv = _inventory()
    start = date(2026, 9, 7)
    a = compute_slots(_ctx(inv), start_day=start, days=28)
    b = compute_slots(_ctx(inv), start_day=start, days=28)
    key = lambda s: (s.day, s.platform, s.slot_index, s.pillar, str(s.source_id), s.status)  # noqa: E731
    assert [key(s) for s in a] == [key(s) for s in b]
    assert len(a) > 0


def test_planner_respects_pillar_mix_within_ten_points() -> None:
    from backend.app.modules.sm_series.planner import compute_slots, pillar_mix_deviation

    # 库存够用时（7 天冷却下 P1+P4 每周最多 = 产品数）配比必须在 ±10 点内。
    slots = compute_slots(_ctx(_inventory(products=24, guides=12, facts=6)), start_day=date(2026, 9, 7), days=28)
    deviation = pillar_mix_deviation(slots, "pinterest")
    assert deviation, "Pinterest 必须排出格子"
    for pillar, delta in deviation.items():
        assert abs(delta) <= 10, deviation


def test_thin_inventory_bends_the_mix_but_never_invents_sources() -> None:
    """库存薄时配比可以偏（诚实反映能发什么），但每一格的源头必须真实存在。"""
    from backend.app.modules.sm_series.planner import compute_slots

    inv = _inventory(products=3, guides=4, facts=1)
    known = {str(p.product_id) for p in inv.products} | {str(g.item_id) for g in inv.guides} | {str(f.fact_id) for f in inv.facts}
    slots = compute_slots(_ctx(inv), start_day=date(2026, 9, 7), days=28)
    for s in slots:
        if s.status == "blocked":
            continue
        if s.source_type != "none":
            assert str(s.source_id) in known, s.label


def test_punctuation_pillars_never_land_on_consecutive_days() -> None:
    from backend.app.modules.sm_series.constants import PUNCTUATION_PILLARS
    from backend.app.modules.sm_series.planner import compute_slots

    slots = compute_slots(_ctx(_inventory(facts=5, brand=1)), start_day=date(2026, 9, 7), days=28)
    for platform in ("pinterest", "instagram"):
        days = sorted({s.day for s in slots if s.platform == platform and s.pillar in PUNCTUATION_PILLARS and s.status != "blocked"})
        for a, b in zip(days, days[1:]):
            assert (b - a).days >= 2, (platform, a, b)


def test_pinterest_factory_pins_only_on_weekends() -> None:
    from backend.app.modules.sm_series.planner import compute_slots

    slots = compute_slots(_ctx(_inventory(facts=5)), start_day=date(2026, 9, 7), days=28)
    for s in slots:
        if s.platform == "pinterest" and s.pillar == "P3" and s.status != "blocked":
            assert s.day.weekday() >= 5, s.day


def test_same_source_same_platform_respects_cooldown() -> None:
    from backend.app.modules.sm_series.planner import compute_slots

    inv = _inventory(products=1, guides=0, facts=0)
    slots = [s for s in compute_slots(_ctx(inv), start_day=date(2026, 9, 7), days=28) if s.platform == "pinterest" and s.pillar == "P1" and s.status != "blocked"]
    days = sorted(s.day for s in slots)
    for a, b in zip(days, days[1:]):
        assert (b - a).days >= 7, (a, b)


def test_seeding_period_uses_pinterest_daily_minimum() -> None:
    from backend.app.modules.sm_series.planner import compute_slots
    from backend.app.modules.sm_series.profiles import PLATFORM_PROFILES

    low, _high = PLATFORM_PROFILES["pinterest"].per_day
    slots = compute_slots(_ctx(_inventory(products=8, guides=10), created_days_ago=1), start_day=date.today(), days=3)
    per_day = {}
    for s in slots:
        if s.platform == "pinterest":
            per_day[s.day] = per_day.get(s.day, 0) + 1
    assert per_day and all(n == low for n in per_day.values()), per_day


def test_out_of_stock_products_are_never_scheduled() -> None:
    from backend.app.modules.sm_series.planner import compute_slots

    inv = _inventory(products=2, guides=0, facts=0)
    inv.products[0].stock_status = "outofstock"
    slots = compute_slots(_ctx(inv), start_day=date(2026, 9, 7), days=14)
    used = {s.source_id for s in slots if s.source_type == "k_product"}
    assert inv.products[0].product_id not in used
    assert inv.products[1].product_id in used


def test_facebook_mirrors_instagram_and_blocks_without_it() -> None:
    from backend.app.modules.sm_series.planner import PlanContext, compute_slots

    inv = _inventory()
    created = datetime.now(timezone.utc) - timedelta(days=60)
    ctx = PlanContext(inventory=inv, channels={"facebook": created})
    slots = compute_slots(ctx, start_day=date(2026, 9, 7), days=7)
    assert slots and all(s.status == "blocked" and s.swap_reason == "no_instagram_post" for s in slots)
    both = compute_slots(_ctx(inv), start_day=date(2026, 9, 7), days=7)
    fb = [s for s in both if s.platform == "facebook" and s.status != "blocked"]
    assert fb and all(s.mirror_of is not None and s.post_kind == "facebook_mirror" for s in fb)


def test_planner_blocks_instead_of_inventing_when_inventory_is_empty() -> None:
    from backend.app.modules.sm_series.planner import compute_slots

    slots = compute_slots(_ctx(_inventory(products=0, guides=0, facts=0)), start_day=date(2026, 9, 7), days=7)
    assert slots
    assert all(s.status == "blocked" for s in slots)


# ---------------------------------------------------------------- 季节


def test_black_friday_boost_starts_sixty_days_ahead() -> None:
    from backend.app.modules.sm_series.seasons_us import season_weights

    assert season_weights(date(2026, 9, 25)).get("P1", 1.0) > 1.0  # 黑五提前 60 天
    # 1 月 10 日：黑五/节礼季已过，露营季（4/1 提前 60 天 = 1/31 起）还没到
    assert season_weights(date(2026, 1, 10)) == {}


# ---------------------------------------------------------------- skill / 写手


def test_skill_is_loaded_from_disk_with_a_digest_and_house_rules_first() -> None:
    from backend.app.modules.sm_series.constants import SM_POST_SKILL_VERSION
    from backend.app.modules.sm_series.prompt_skills import build_messages, skill_context, skill_sections
    from backend.app.modules.sm_series.profiles import PLATFORM_PROFILES

    ctx = skill_context()
    assert ctx["version"] == SM_POST_SKILL_VERSION
    assert len(ctx["content_sha256"]) == 64
    sections = skill_sections(ctx["skill_markdown"])
    assert "§0" in sections and "§8" in sections
    messages = build_messages(
        skill_markdown=ctx["skill_markdown"], profile=PLATFORM_PROFILES["pinterest"], pillar="P1",
        post_kind="pinterest_pin", source_snapshot={"k": {"sku": "X"}}, media_plan=[], keyword_hints={},
    )
    system = messages[0]["content"]
    assert system.index("品牌家规") < system.index("PLATFORM PROFILE")
    # 提示词里不许写死任何产品名（derive, don't ask）
    for banned in ("PSPE-001", "camping shower", "stress ball", "花洒"):
        assert banned not in system


def test_writer_parse_does_not_silently_fix_violations() -> None:
    from backend.app.modules.sm_series.writer import parse_output

    raw = '```json\n{"platform":"instagram","pillar":"P2","title":"t","caption":"c","first_line":"f","alt_text":"a","hashtags":["#A","b","c","d","e","f","g"],"board":"","cta":"x","keyword_primary":"kw","keywords_secondary":"k1, k2","facts_used":["k.sku"],"overlay_texts":[],"derived_numbers":[],"blocked_reason":""}\n```'
    out = parse_output(raw)
    assert out["hashtags"] == ["a", "b", "c", "d", "e", "f", "g"]  # 7 个照录，审计去标
    assert out["keywords_secondary"] == ["k1", "k2"]


def test_writer_rejects_non_json() -> None:
    from backend.app.modules.sm_series.writer import WriterError, parse_output

    with pytest.raises(WriterError):
        parse_output("sorry, I cannot do that")


# ---------------------------------------------------------------- 审计


class _Product:
    sku = "SKU-1"
    product_name_en = "Portable Widget"
    product_type = "widget"
    primary_use_case_en = None
    target_customer_en = None
    primary_keyword = "portable widget"
    secondary_keywords_json = None
    long_tail_keywords_json = None
    structured_specs_json = {"flow_gpm": {"value": "2.11", "unit": "GPM"}}
    selling_points_approved_json = {"review_status": "approved", "bullets": [{"text": "Runs 90 minutes per charge"}]}
    package_includes_json = ["pump", "hose"]
    dimensions_json = None
    weight_json = None
    certifications_json = None
    warranty_note_en = None
    safety_note_en = None
    stock_status = "instock"
    detected_brand_terms = ["Acme"]
    brand_audit_json = {"clean": True}


def test_facts_used_paths_resolve_or_are_reported() -> None:
    from backend.app.modules.sm_series.audits import resolve_facts_used

    resolved, unresolved = resolve_facts_used(
        ["k.structured_specs_json.flow_gpm", "k.selling_points[0]", "k.nope.nothing", "craft_facts.abc"],
        product=_Product(), guide=None, facts_by_id={"abc": {"claim": "x"}},
    )
    assert "k.selling_points[0]" in resolved
    assert "craft_facts.abc" in resolved
    assert "k.nope.nothing" in unresolved


def test_audit_flags_forbidden_phrases_platform_rules_and_empty_facts() -> None:
    from backend.app.modules.sm_series.audits import audit_post
    from backend.app.modules.sm_series.profiles import PLATFORM_PROFILES

    fields = {
        "title": "Portable widget for camping – 2.11 GPM",
        "caption": "Made at our Guangzhou factory, 2.11 GPM, 90 minutes runtime.",
        "first_line": "x" * 130,
        "alt_text": "widget",
        "hashtags": ["a", "b", "c", "d", "e", "f"],
        "facts_used": [],
        "keyword_primary": "portable widget",
    }
    audit = audit_post(
        db=None, post_fields=fields, pillar="P1", profile=PLATFORM_PROFILES["instagram"], product=_Product(),
        guide=None, facts=[], previous_audit=None, user=None, ai_check=False,
    )
    terms = {(v["surface"], v["term"]) for v in audit["brand_violations"]}
    assert ("phrase", "guangzhou factory") in terms
    assert ("platform", "hashtags") in terms
    assert ("platform", "first_line") in terms
    assert ("facts_used", "empty") in terms
    assert audit["clean"] is False
    # 数字接地：2.11 和 90 都在证据语料里，不应被判编造
    assert audit["ungrounded_numbers"] == []


def test_audit_is_clean_when_everything_is_grounded() -> None:
    from backend.app.modules.sm_series.audits import audit_post
    from backend.app.modules.sm_series.profiles import PLATFORM_PROFILES

    fields = {
        "title": "Portable widget for camping – 2.11 GPM flow",
        "caption": "A portable widget that runs 90 minutes per charge. Product page in bio.",
        "first_line": "",
        "alt_text": "portable widget standing beside a tent",
        "hashtags": [],
        "facts_used": ["k.structured_specs_json.flow_gpm", "k.selling_points[0]"],
        "keyword_primary": "portable widget",
    }
    audit = audit_post(
        db=None, post_fields=fields, pillar="P1", profile=PLATFORM_PROFILES["pinterest"], product=_Product(),
        guide=None, facts=[], previous_audit=None, user=None, ai_check=False,
    )
    assert audit["clean"] is True, audit


# ---------------------------------------------------------------- K 位号


def test_k_social_specs_start_at_201_and_are_never_main() -> None:
    from backend.app.modules.sm_series.constants import SOCIAL_POSITION_BASE

    source = (REPO / "backend/app/modules/k_series/product_knowledge/image_render_jobs.py").read_text(encoding="utf-8")
    assert "_social_specs(db, product, known_positions)" in source
    assert '"role": "proof_scene"' in source
    assert SOCIAL_POSITION_BASE == 200


def test_utm_is_appended_to_every_link() -> None:
    from backend.app.modules.sm_series.service import with_utm

    url = with_utm("https://barongyekhna.com/product/x/?ref=1", platform="pinterest", pillar="P1", post_id=uuid4())
    assert url and "utm_source=pinterest" in url and "utm_medium=social" in url and "utm_campaign=p1" in url and "ref=1" in url
    assert with_utm(None, platform="pinterest", pillar="P1", post_id=uuid4()) is None


def test_layout_renderer_produces_vertical_webp() -> None:
    pytest.importorskip("PIL")
    import io

    from PIL import Image

    from backend.app.modules.sm_series.layout_render import render_card

    square = Image.new("RGB", (400, 400), (200, 30, 30))
    buf = io.BytesIO()
    square.save(buf, format="PNG")
    out = render_card(buf.getvalue(), ratio="2:3", headline="Five portable shower mistakes first-timers make often")
    image = Image.open(io.BytesIO(out))
    assert image.format == "WEBP"
    assert image.size == (1000, 1500)
    card = Image.open(io.BytesIO(render_card(None, ratio="4:5", headline="Guide", lines=["one", "two"])))
    assert card.size == (1080, 1350)
