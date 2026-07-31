"""SEO 内容引擎——护住的是**判断**,不是实现细节。

每条测试对应一个"想错了就会出 AI 垃圾 / 自我竞争 / 线上 404"的决策点。
"""

from __future__ import annotations

import inspect

import pytest

import backend.app.models  # noqa: F401

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- 反垃圾家规


def test_anti_slop_rules_are_shared_not_copied() -> None:
    """GEO 与 SEO 的反垃圾条款必须是**同一批常量**。

    各抄一份迟早漂:一边改了「不值得那段不许推销收尾」,另一边还留旧版,
    而两边都还是合法提示词——没有任何测试会发现。
    """
    from backend.app.modules.content_core import writing_rules as W
    from backend.app.modules.geo_series.content.prompt_skills import (
        geo_content_instruction,
        geo_revise_instruction,
    )
    from backend.app.modules.seo_series.content.prompt_skills import (
        seo_content_instruction,
        seo_revise_instruction,
    )

    geo_gen = geo_content_instruction()
    seo_gen = seo_content_instruction(item_kind="craft_story", audience="brand")
    for clause in (W.ANSWER_THE_QUESTION_EN, W.JUDGEMENT_STRUCTURE_EN, W.ARITHMETIC_EN):
        assert clause in geo_gen
        assert clause in seo_gen

    geo_rev = geo_revise_instruction()
    seo_rev = seo_revise_instruction()
    for clause in (
        W.NO_FABRICATION_ZH,
        W.ARITHMETIC_ZH,
        W.ANSWER_THE_QUESTION_ZH,
        W.JUDGEMENT_STRUCTURE_ZH,
    ):
        assert clause in geo_rev
        assert clause in seo_rev


def test_seo_prompt_refuses_to_pad_for_length() -> None:
    """长文在 AI 搜索时代贬值:被引用的是自足段落,不是第 2100 个字。"""
    from backend.app.modules.seo_series.content.prompt_skills import (
        seo_content_instruction,
    )

    text = seo_content_instruction(item_kind="buying_guide", audience="consumer")
    assert "Do NOT pad to hit a length" in text
    assert "stand alone" in text
    # 内链只给意图不给 URL——给 URL 等于让模型编 URL
    assert "Give the INTENT, not a URL" in text


# ---------------------------------------------------------------- 去重门


def test_geo_reachable_topics_never_enter_the_seo_queue() -> None:
    """同一话题两边都写 = 自我竞争。三项全中才算 GEO 领地。"""
    from backend.app.modules.seo_series.content.geo_reachability import GeoReachability

    src = inspect.getsource(GeoReachability.judge)
    assert "GEO 已经写过这题了" in src
    assert "没有对应的 GEO 类目簇" in src
    assert "_accept" in src
    # 每条路径都要给理由——「无类目」和「被 GEO 收了」要做的事完全不同
    assert src.count("return ") >= 5

    radar = inspect.getsource(
        __import__(
            "backend.app.modules.seo_series.content.topic_radar",
            fromlist=["run_radar"],
        ).run_radar
    )
    assert "if reachable:" in radar
    assert "geo_blocked += 1" in radar
    assert "continue" in radar


def test_the_radar_says_out_loud_how_many_it_dropped() -> None:
    """雷达只出 3 条时,别让它看起来像故障。"""
    from backend.app.modules.seo_series.content.topic_radar import run_radar

    src = inspect.getsource(run_radar)
    assert "geo_blocked" in src
    assert "避免自我竞争" in src


# ---------------------------------------------------------------- B 端选题


def test_b_side_topics_are_ranked_by_coverage_not_search_volume() -> None:
    """采购词量小到测不出来,拿搜索量排会把最赚钱的题排到最后。"""
    from backend.app.modules.seo_series.content.topic_radar import score_topic

    gap = score_topic(
        audience="wholesale",
        searches=0,
        attackability=None,
        has_support=True,
        store_type_gap=True,
    )
    covered = score_topic(
        audience="wholesale",
        searches=0,
        attackability=None,
        has_support=True,
        store_type_gap=False,
    )
    popular_consumer = score_topic(
        audience="consumer",
        searches=5000,
        attackability=60,
        has_support=True,
        store_type_gap=False,
    )
    assert gap > covered
    # 一个还没被覆盖的店型,压得过一个高量 C 端词
    assert gap > popular_consumer


def test_a_topic_with_no_fact_support_sinks_to_the_bottom() -> None:
    from backend.app.modules.seo_series.content.topic_radar import score_topic

    assert (
        score_topic(
            audience="consumer",
            searches=99999,
            attackability=90,
            has_support=False,
            store_type_gap=False,
        )
        == 0
    )


def test_planner_is_only_spent_on_consumer_seeds() -> None:
    """B 端打 Planner 换回一个 0,毫无信息,还占着和 R-A 共用的桶。"""
    from backend.app.modules.seo_series.content import topic_radar

    src = inspect.getsource(topic_radar._planner_metrics)
    assert 'audience"] == C.AUDIENCE_CONSUMER' in src
    assert "try_consume" in src  # 每次调用都记台账
    assert "db.commit()" in src  # 出网前放掉事务


def test_radar_releases_the_transaction_before_going_out() -> None:
    """出网调用绝不能圈在事务里(本仓库踩过四次)。"""
    from backend.app.modules.seo_series.content import topic_radar

    src = inspect.getsource(topic_radar._planner_metrics)
    commit_at = src.index("db.commit()")
    key_at = src.index("SecretManager")
    call_at = src.index("client.keyword_ideas")
    assert commit_at < key_at < call_at, "必须 commit → 取钥匙 → 出网"


# ---------------------------------------------------------------- 事实门禁


def test_generation_refuses_when_the_main_fact_source_is_empty() -> None:
    """宁可不写,也不写正确的废话——而且必须说清楚去补什么。"""
    from backend.app.modules.seo_series.content.orchestrator import (
        SeoContentOrchestrator,
    )

    src = inspect.getsource(SeoContentOrchestrator._fact_gate)
    assert "SEO_NO_CRAFT_FACTS" in src
    assert "去「工艺事实」页录几条" in src
    assert "SEO_NO_PRODUCT_FACTS" in src
    assert "去 K 补规格" in src


def test_craft_facts_are_grounded_and_ledgered() -> None:
    from backend.app.modules.seo_series.content.orchestrator import (
        SeoContentOrchestrator,
    )

    gen = inspect.getsource(SeoContentOrchestrator.generate)
    assert "evidence_number_corpus(" in gen and "craft_payload" in gen
    assert "_record_craft_usage" in gen
    rev = inspect.getsource(SeoContentOrchestrator.revise)
    assert "_record_craft_usage" in rev


def test_published_slug_is_locked_on_rewrite() -> None:
    """改地址 = 把已积累的权重丢掉。内容可以重写,地址不行。"""
    from backend.app.modules.seo_series.content.orchestrator import (
        SeoContentOrchestrator,
    )

    src = inspect.getsource(SeoContentOrchestrator.revise)
    assert "item.wp_post_id and isinstance(item.seo_json, dict)" in src
    assert 'new_seo["url_slug"] = old_slug' in src


# ---------------------------------------------------------------- 发布 / 内链


def test_factory_posts_are_excluded_from_the_blog_archive() -> None:
    """/posts 是博客;工艺文有自己的区。排除名单是数据,插件零改动。"""
    from backend.app.modules.seo_series.content import wp_terms

    src = inspect.getsource(wp_terms.sync_factory_category_exclusions)
    assert "GEO_CATEGORY_IDS_OPTION" in src
    assert "DESTINATION_FACTORY" in src
    # C 端博文**不能**被排除,否则博客永远是空的
    assert "geo_ids | factory_ids" in src


def test_consumer_posts_do_not_reuse_the_google_taxonomy() -> None:
    """C 端博文若落在谷歌类目下,会被 GEO 的排除名单连坐,博客永远空。"""
    from backend.app.modules.seo_series.content import constants as C
    from backend.app.modules.seo_series.content.wp_terms import (
        BLOG_CATEGORIES,
        FACTORY_CATEGORIES,
    )

    assert C.ITEM_BUYING_GUIDE in BLOG_CATEGORIES
    assert C.ITEM_BUYING_GUIDE not in FACTORY_CATEGORIES
    assert C.destination_for(C.AUDIENCE_CONSUMER) == C.DESTINATION_POSTS
    assert C.destination_for(C.AUDIENCE_BRAND) == C.DESTINATION_FACTORY
    assert C.destination_for(C.AUDIENCE_WHOLESALE) == C.DESTINATION_FACTORY


def test_category_lookup_never_creates_a_duplicate_on_a_wp_blip() -> None:
    """查不通就不要建——一超时就新建,等于每次超时多一个重复分类。"""
    from backend.app.modules.seo_series.content import wp_terms

    src = inspect.getsource(wp_terms._find_or_create_term)
    assert "本次不新建" in src


def test_internal_links_never_point_at_a_draft_or_an_unlisted_product() -> None:
    """published_url 非空 ≠ 线上可见;没上架的产品挂了就是 404。"""
    from backend.app.modules.seo_series.content import links

    guides = inspect.getsource(links._guide_links)
    assert 'wp_status == "publish"' in guides
    products = inspect.getsource(links._product_links)
    assert "text.isdigit()" in products
    assert "还没上架的产品不挂链" in products


def test_unresolved_link_intents_are_reported_not_hidden() -> None:
    """解析不出来是常态(目标页还不存在),但要如实说,别假装挂上了。"""
    from backend.app.modules.seo_series.content.links import resolve_link_intents

    src = inspect.getsource(resolve_link_intents)
    assert "unresolved" in src
    assert "这个类目还没有已发布的指南" in src


def test_factory_hub_only_lists_live_articles() -> None:
    from backend.app.modules.seo_series.content import factory_index

    src = inspect.getsource(factory_index.factory_groups)
    assert 'SeoContentItem.wp_status == "publish"' in src


def test_live_state_refresh_never_blanks_on_a_wp_outage() -> None:
    """WP 不可达时清空状态,会让线上文章从枢纽页凭空消失。"""
    from backend.app.modules.seo_series.content import live_state

    src = inspect.getsource(live_state.refresh_item_live_state)
    assert "if not states:" in src
    assert "什么都不改" in src


def test_publish_queue_commits_before_dispatch() -> None:
    """n8n 毫秒级就来取包,行没落库会 401(2026-07-23 的竞态,继承过来)。"""
    from backend.app.modules.seo_series.content import publish_jobs

    src = inspect.getsource(publish_jobs.kick_queue)
    commit_at = src.index("db.commit()")
    send_at = src.index("_send_to_n8n")
    assert commit_at < send_at
    assert "IN_FLIGHT_TIMEOUT_MINUTES" in inspect.getsource(publish_jobs)


def test_only_approved_and_clean_articles_can_be_published() -> None:
    from backend.app.modules.seo_series.router import create_publish

    src = inspect.getsource(create_publish)
    assert 'review_status != "approved"' in src
    assert "没过品牌/接地审查" in src


# ---------------------------------------------------------------- n8n


def test_both_publish_workflows_come_from_one_generator() -> None:
    """复制一份改名字更快,但那意味着 n8n 那三个教训以后只会在一边被修。"""
    from backend.app.modules.geo_series.n8n import build_workflow as geo_wf
    from backend.app.modules.seo_series.n8n import build_workflow as seo_wf

    assert "n8n.build_publish_workflow" in inspect.getsource(geo_wf.build)
    assert "n8n.build_publish_workflow" in inspect.getsource(seo_wf.build)

    geo = geo_wf.build()
    seo = seo_wf.build()
    assert sorted(geo["connections"]) == sorted(seo["connections"])
    # 节点 id 绝不能撞——n8n 按 id 认节点
    assert not ({n["id"] for n in geo["nodes"]} & {n["id"] for n in seo["nodes"]})
    assert seo["id"] == "barongSEOpublish001"


def test_seo_workflow_keeps_the_three_n8n_lessons() -> None:
    from backend.app.modules.seo_series.n8n.build_workflow import build

    wf = build()
    js = " ".join(
        str(n["parameters"].get("jsCode") or "")
        for n in wf["nodes"]
        if n["type"].endswith("code")
    )
    assert "$input.all().map(" in js  # ① 不能只取第一条
    assert "needs_backfill" in js  # ② 两个分支都能走到回报
    assert "_yoast_wpseo_title" in js  # ③ Yoast 走 meta 对象
    assert "body.meta = meta" in js and "body.meta_data" not in js
    # 每篇自带分类,且拿不到就整单失败——绝不发成无类目
    assert "拒绝发布：文章没有带分类 id" in js


def test_machine_endpoints_do_not_leak_which_jobs_exist() -> None:
    from backend.app.modules.seo_series.machine_router import _require_job

    src = inspect.getsource(_require_job)
    assert "不泄漏哪个任务存在" in src
    assert "401" in src


# ---------------------------------------------------------------- 监测


def test_rank_monitoring_reuses_geo_tables_instead_of_a_second_set() -> None:
    """再造一套表 = Serper 台账和守门人识别也复制一份,迟早漂。"""
    from pathlib import Path

    from backend.app.modules.seo_series.content import rank_monitor

    assert "GeoMonitorQuestion" in inspect.getsource(
        rank_monitor.seed_from_picked_topics
    )
    assert not Path("backend/app/modules/seo_series/monitor").exists()
    # 可攻度反过来喂回选题排序 —— 打不动的题会自己沉下去
    assert "score_topic" in inspect.getsource(rank_monitor.apply_terrain_to_topics)


# ---------------------------------------------------------------- 依赖方向


def test_content_core_never_imports_a_series() -> None:
    """共享底座反过来依赖某个系列,就不再是底座了。"""
    from pathlib import Path

    import ast

    for path in Path("backend/app/modules/content_core").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            for name in names:
                assert "geo_series" not in name, f"{path}: {name}"
                assert "seo_series" not in name, f"{path}: {name}"


def test_every_borrowed_orm_column_actually_exists() -> None:
    """SEO 大量读别人的表(K / GEO / B2B)。列名写错在源码检查里看不出来,
    只有真跑一次才炸——2026-07-30 就这么炸在生产上(``keyword`` 其实叫
    ``keyword_text``、产品的类目 id 其实叫 ``google_product_category``)。

    所以这里做真正的解析:把 SEO 源码里所有 ``<Model>.<attr>`` 的引用挑出来,
    逐个对着真模型查。跨模块借表越多,这道门越值钱。
    """
    import re
    from pathlib import Path

    import backend.app.models as M

    models = {
        name: getattr(M, name)
        for name in dir(M)
        if name.startswith(("KProduct", "Geo", "B2B", "PUpload", "Craft", "Content"))
        and hasattr(getattr(M, name), "__table__")
    }
    pattern = re.compile(r"\b(" + "|".join(models) + r")\.([a-z_][a-z0-9_]*)\b")

    missing: list[str] = []
    for path in Path("backend/app/modules/seo_series").rglob("*.py"):
        for model_name, attr in pattern.findall(path.read_text()):
            model = models[model_name]
            if attr in {"id", "metadata", "registry"}:
                continue
            if not hasattr(model, attr):
                missing.append(f"{path.name}: {model_name}.{attr}")
    assert not missing, "引用了不存在的列：\n" + "\n".join(missing)


def test_seed_quota_stops_one_audience_from_eating_the_whole_round() -> None:
    """2026-07-30 首跑:5 个店型 × 5 个采购决策正好 25 条,把 C 端和工艺题
    一条不剩地挤出去。先到先得在这里是错的。"""
    from backend.app.modules.seo_series.content import topic_radar as R

    assert set(R._AUDIENCE_QUOTA) == {"consumer", "wholesale", "brand"}
    assert abs(sum(R._AUDIENCE_QUOTA.values()) - 1.0) < 0.01
    src = inspect.getsource(R.collect_seeds)
    # 某一池不够时,名额要让出去而不是空着
    assert src.count("for seed in pools.get(audience") == 2
    # 手输永远优先
    assert src.index("for seed in manual") < src.index("_AUDIENCE_QUOTA.items()")


def test_store_type_keywords_are_english() -> None:
    """label 是给中国人看的中文标签(「礼品店」),拿它当关键词会写出中英混排
    的标题。面向美国买家的内容一律英文(死规矩)。"""
    from backend.app.modules.seo_series.content.topic_radar import _store_type_seeds

    src = inspect.getsource(_store_type_seeds)
    assert "store.key" in src
    assert "store.label" not in src


def test_b_side_support_is_capability_not_word_overlap() -> None:
    """采购词和工艺库一个字都不重叠,但采购方问的本来就不是品类词,
    是"你们到底有没有工厂"。按词面判会把整条 B 端线判死。"""
    from backend.app.modules.seo_series.content.fact_match import FactMatcher

    matcher = FactMatcher.__new__(FactMatcher)
    matcher.sources = {
        "craft": [("工艺：dual O-ring", {"dual", "ring", "seal"})],
        "product": [("产品：Camping Shower", {"camping", "shower"})],
        "store_type": [],
    }
    b = matcher.support_for("gift shop wholesale minimum order quantity", audience="wholesale")
    assert b["has_support"] is True
    assert b["missing"] == []

    # C 端仍按词面判——它问的就是具体品类的事,对不上就是真没得写
    c = matcher.support_for("gift shop wholesale minimum order quantity", audience="consumer")
    assert c["has_support"] is False
    assert c["missing"]

    # 品牌题只认工艺事实:没有工艺库,工艺文只能是形容词
    empty = FactMatcher.__new__(FactMatcher)
    empty.sources = {"craft": [], "product": [("产品：X", {"x"})], "store_type": []}
    assert empty.support_for("injection molding", audience="brand")["has_support"] is False
    assert empty.support_for("anything", audience="wholesale")["has_support"] is True


def test_shared_payload_accepts_both_item_type_and_item_kind() -> None:
    """GEO 叫 item_type,SEO 叫 item_kind——同一个概念的两个名字。
    共享组件认两种,不逼任何一边为了复用改自己的列名(2026-07-30 实跑炸过)。"""
    from types import SimpleNamespace

    from backend.app.modules.content_core.analysis import _item_payload

    geo = SimpleNamespace(item_type="qa", title="t", body_json={}, seo_json={})
    seo = SimpleNamespace(item_kind="craft_story", title="t", body_json={}, seo_json={})
    assert _item_payload(geo)["item_type"] == "qa"
    assert _item_payload(seo)["item_type"] == "craft_story"


def test_a_broken_analysis_never_costs_us_the_article() -> None:
    """内容已经生成好了(一次 AI 调用),解读只是阅读辅助——
    它抛异常绝不能让整篇回滚。2026-07-30 实跑丢过一篇。"""
    from backend.app.modules.content_core import analysis_persist

    src = inspect.getsource(analysis_persist.attach_analysis_to)
    snapshot_at = src.index("_item_payload(item)")
    guard_at = src.index("try:")
    assert guard_at < snapshot_at, "快照组装必须在 try 里"


def test_b_side_articles_get_the_real_purchasing_terms() -> None:
    """2026-07-30 首篇 B 端文章诚实但空洞——它自己列了 9 条缺失事实
    (起订量/交期/付款/验厂),因为当时只喂产品规格,而**产品规格答不了采购问题**。
    答案早就有,住在 B2B 的政策常量里(用户自己拍板的口径)。

    接过来的第二个好处:批发页、产品页小窗、SEO 文章从此同一个口径——
    同一件事两处说法不一,正是 GMC 判虚假陈述的那个病。
    """
    from backend.app.modules.seo_series.content.orchestrator import (
        SeoContentOrchestrator,
    )

    facts = SeoContentOrchestrator._policy_facts(object())
    topics = {f["topic"] for f in facts}
    assert {"minimum-order", "payment-terms", "shipping", "defects"} <= topics

    blob = " ".join(f["claim"] for f in facts)
    assert "300" in blob and "500" in blob and "50%" in blob
    # 死规矩:只讲瑕疵,绝不写成"X 天内可退"的结构化退货窗口(GMC 雷)
    import re

    assert not re.search(r"\b\d+[- ]day\b", blob, re.I)
    # 死规矩:绝不收信用卡/PayPal
    assert "do not accept credit" in blob

    gen = inspect.getsource(SeoContentOrchestrator.generate)
    # 只喂 B 端:C 端买家不关心起订量,给了只会污染文案
    assert 'topic.audience == C.AUDIENCE_WHOLESALE else []' in gen
    # 政策里的数字必须进接地语料,否则写 $300 会被判成编造
    assert "evidence_number_corpus(\n            craft_payload, product_payload, policy_payload\n        )" in gen


def test_callback_token_is_read_from_the_header_not_a_query_param() -> None:
    """FastAPI 不写 Header(...) 就会把它当 query 参数,n8n 送的 X-Job-Token
    永远读不到,回报一律 401——而且 WP 那边其实已经写成功了,任务白白卡死。
    2026-07-31 实测踩到。"""
    import inspect

    from backend.app.modules.seo_series import machine_router

    src = inspect.getsource(machine_router.publish_result)
    assert "x_job_token: str | None = Header(" in src


def test_b_side_topics_carry_their_store_type_category() -> None:
    """店型本来就是**按谷歌类目前缀定义**的,所以类目不用问、不用猜。
    没有它,B 端文章挂产品链接只能靠词面猜——2026-07-31 实测挂上了「包子捏捏」,
    只因为两个标题里都有 Portable。"""
    import inspect

    from backend.app.modules.seo_series.content import topic_radar

    src = inspect.getsource(topic_radar._store_type_seeds)
    assert "_store_type_category" in src
    assert '"google_category_id": category_id' in src

    lookup = inspect.getsource(topic_radar._store_type_category)
    assert "full_path = :p" in lookup  # 前缀字符串 → 类目 id


def test_category_matching_walks_the_subtree_not_exact_equality() -> None:
    """店型类目往往是 "Toys & Games" 这种上层节点,没有产品会精确等于它。"""
    import inspect

    from backend.app.modules.seo_series.content import links

    products = inspect.getsource(links._product_links)
    assert "category_descendants" in products
    assert "google_product_category.in_(family)" in products

    # 店型子页也按子树判,不是字符串包含——
    # 包含会把 "Home & Garden > Decor" 和 "Home & Garden > Kitchen" 混为一谈
    wholesale = inspect.getsource(links._wholesale_links)
    assert "category_ancestors" in wholesale
    assert "covered_paths" in wholesale


def test_factory_hub_shows_empty_sections_on_purpose() -> None:
    """这一页的作用是让人一眼看到我们**打算证明哪几件事**。
    把空分区藏起来,页面就只剩"什么都没有"。"""
    from backend.app.modules.seo_series.content.factory_index import (
        render_factory_page,
    )

    html = render_factory_page(
        [
            ("craft_story", "Craft & Process", [{"title": "A", "url": "#"}]),
            ("testing", "Testing", []),
        ]
    )
    assert "Being written" in html  # 空分区照样出现
    assert 'type="search"' in html  # 和 /guides/ 同规:搜索在最前
    assert "by-fac-chip" in html  # 分区筛选
    # 关掉 JS 也要能用:文章链接直接在 HTML 里
    assert 'href="#"' in html


# ===================================================================
# 产品页 → 工艺文（kp-factory 块）
# ===================================================================


def test_factory_block_walks_category_ancestors_not_descendants() -> None:
    """工艺文讲"我们怎么做这一类东西"(防水密封、锂电组装),天然挂**上层类目**;
    产品在叶子。按子树找会得到"这个大类底下所有细分品的工艺文"——对一个具体
    产品全是噪音。"""
    import inspect

    from backend.app.modules.seo_series.content import product_backlink

    src = inspect.getsource(product_backlink.published_factory_articles_for_product)
    assert "category_ancestors" in src
    assert "category_descendants" not in src
    # 死规矩:published_url 非空 ≠ 线上可见
    assert 'wp_status == "publish"' in src
    # 没绑类目的工艺文 = 通用工艺,对任何产品都算数
    assert "if category and category not in family" in src


def test_factory_block_output_is_capped_and_deterministic() -> None:
    """链接图要算指纹,顺序不稳定就等于每次都往 WP 写一遍。"""
    import inspect

    from backend.app.modules.seo_series.content import product_backlink

    assert product_backlink.MAX_FACTORY_LINKS_ON_PRODUCT == 3
    src = inspect.getsource(product_backlink.published_factory_articles_for_product)
    assert "scored.sort(" in src


def test_both_pdp_block_producers_emit_identical_bytes() -> None:
    """P 组包和反链派单会在同一个线上产品上写同一个块。
    两边字节不一致就会每次刷新互相覆盖。"""
    from backend.app.modules.geo_series.content.backlink import build_guides_block
    from backend.app.modules.seo_series.content.product_backlink import (
        build_factory_block,
    )

    links = [("T", "https://x/a/")]
    # 两个块各自都只有一个生产函数——P 组包和派单调的是同一个
    import inspect

    from backend.app.modules.p_series.upload import assemble

    assert "factory_block_for_product" in inspect.getsource(
        assemble._append_factory_section
    )
    assert "build_guides_block" in inspect.getsource(
        assemble._append_related_guides_section
    )
    assert build_guides_block(links) != build_factory_block(links)  # class 不同
    assert "kp-factory" in build_factory_block(links)


def test_pdp_block_order_is_one_constant() -> None:
    """三个块的先后是运营判断(指南离购买近、工艺是信任兜底),
    改一行常量就能翻转,不该散在各处。"""
    from backend.app.modules.content_core.html_blocks import PDP_BLOCK_ORDER

    assert PDP_BLOCK_ORDER == ("kp-box", "kp-guides", "kp-factory")
