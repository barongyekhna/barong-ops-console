"""工艺事实库——重点全在「事实会变」这件事上。

用户 2026-07-29 明确:工艺事实会不断更新。于是真正的风险不是写错,而是
**今天引用的事实明天变了,文章悄悄变成错的**——过期的真话和编造一样有害,
而且没有任何输出护栏会报警(每句话都还是通顺、有据、品牌正确的)。
"""

from __future__ import annotations

import pytest

import backend.app.models  # noqa: F401,E402

pytestmark = pytest.mark.unit


def test_material_change_bumps_version_and_leaves_a_snapshot() -> None:
    from backend.app.modules.content_core.facts import service

    assert "claim" in service.MATERIAL_FIELDS
    assert "value" in service.MATERIAL_FIELDS
    assert "basis" in service.MATERIAL_FIELDS
    # 归类改动不影响已发布内容的正确性,不该升版
    assert "topic" not in service.MATERIAL_FIELDS

    import inspect

    src = inspect.getsource(service.update_fact)
    assert "fact.version += 1" in src
    assert "CraftFactRevision(" in src
    # 实质改动后必须退回待批准——已批准的旧结论不该顺着改动自动生效
    assert 'fact.status = "draft"' in src


def test_a_fact_without_basis_cannot_be_approved() -> None:
    """没有依据的"事实"是主张。它会被内容引擎当可核事实用,所以挡在批准这一关。"""
    import inspect

    from backend.app.modules.content_core.facts import service

    src = inspect.getsource(service.approve_fact)
    assert "fact.basis" in src
    assert "CraftFactError" in src


def test_stale_detection_is_a_version_comparison() -> None:
    """过期判据只有一条:引用时的版本 < 当前版本。"""
    import inspect

    from backend.app.modules.content_core.facts import service

    src = inspect.getsource(service.stale_content)
    assert "ContentFactUsage.fact_version < CraftFact.version" in src


def test_usage_is_replaced_not_accumulated() -> None:
    """重写一篇内容后,它不再引用的事实必须从台账里消失,否则会永远误报过期。"""
    import inspect

    from backend.app.modules.content_core.facts import service

    src = inspect.getsource(service.record_usage)
    assert "db.delete(row)" in src
    assert "fact_id not in seen" in src


def test_only_approved_facts_reach_content() -> None:
    import inspect

    from backend.app.modules.content_core.facts import service

    assert 'CraftFact.status == "approved"' in inspect.getsource(service.approved_facts)


def test_craft_numbers_reach_the_grounding_corpus_without_touching_guards() -> None:
    """工艺事实里的数字要能被护栏认作已接地,否则写"30 分钟浸泡"会被判成编造。
    evidence_number_corpus 本就是变参,所以护栏一行都不用改。"""
    from types import SimpleNamespace

    from backend.app.modules.content_core.facts.service import grounding_texts
    from backend.app.modules.content_core.guards import evidence_number_corpus

    fact = SimpleNamespace(
        claim="IPX8 verified by a 30 minute submersion test",
        detail="Main unit only",
        value="30",
        unit="minutes",
    )
    corpus = evidence_number_corpus(*grounding_texts([fact]))
    assert "30" in corpus


def test_fact_library_lives_in_the_shared_core() -> None:
    """工艺库不是 SEO 专有:GEO 指南会引用它,B2B 批发页更要靠它证明有真工厂。"""
    from pathlib import Path

    assert Path("backend/app/modules/content_core/facts/models.py").exists()
    assert not Path("backend/app/modules/seo_series/facts/models.py").exists()


def test_generation_feeds_craft_facts_into_grounding_and_the_ledger() -> None:
    """接进生成链的两件事:数字进接地语料、引用进台账。少任何一件这套设计就断了。"""
    import inspect

    from backend.app.modules.geo_series.content.orchestrator import (
        GeoContentOrchestrator,
    )

    gen = inspect.getsource(GeoContentOrchestrator.generate_cluster)
    assert "evidence_numbers |= craft_numbers" in gen
    assert '"craft_facts": craft_payload' in gen
    assert "_record_craft_usage(cluster_id, craft_rows)" in gen

    # 重写链同样要给,否则同一段话生成时合规、重写时反被判无据。
    rev = inspect.getsource(GeoContentOrchestrator.revise_item)
    assert "revise_craft_numbers" in rev
    assert '"craft_facts": revise_craft_payload' in rev
    assert "_record_craft_usage_for" in rev


def test_an_empty_craft_library_never_blocks_generation() -> None:
    """工艺库是增益不是前置:取不到就当没有,绝不拖垮已经跑通的生成链。"""
    import inspect

    from backend.app.modules.geo_series.content.orchestrator import (
        GeoContentOrchestrator,
    )

    src = inspect.getsource(GeoContentOrchestrator._craft_facts)
    assert "return [], [], set()" in src
    assert 'CraftFact.status == "approved"' not in src  # 走 service，不重复写筛选


def test_the_approval_gate_message_survives_production_sanitizing() -> None:
    """「没有依据的事实不许批准」本身就是产品——被消毒成 Request failed. 就白做了。

    同时确认口径卡死:换个状态码、换条路径都不放行。
    """
    from types import SimpleNamespace

    from backend.app.main import _craft_fact_detail_for_production

    def req(path: str):
        return SimpleNamespace(url=SimpleNamespace(path=path))

    msg = "「双道 O 圈」没有填依据(basis)——自测?供应商规格?标准号?"
    assert (
        _craft_fact_detail_for_production(req("/api/app/seo/facts/x/approve"), 400, msg)
        == msg
    )
    # 只放 400，其它状态码照常消毒
    assert (
        _craft_fact_detail_for_production(req("/api/app/seo/facts"), 403, msg) is None
    )
    # 只放 /seo/facts，别的路径蹭不到
    assert _craft_fact_detail_for_production(req("/api/app/k/products"), 400, msg) is None
    # 只放纯字符串，结构化 detail 不外泄
    assert (
        _craft_fact_detail_for_production(
            req("/api/app/seo/facts"), 400, {"secret": "x"}
        )
        is None
    )
