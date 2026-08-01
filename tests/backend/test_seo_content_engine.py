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


def test_content_links_is_an_aggregator_above_the_series() -> None:
    """content_core 在**下面**(被 geo/seo 依赖),content_links 在**上面**
    (依赖 geo/seo)。方向相反,所以不能塞进同一个包——
    2026-07-31 把链接图放进 content_core，被下面那条依赖方向测试当场抓住。"""
    from pathlib import Path

    text = Path("backend/app/modules/content_links/link_graph.py").read_text()
    assert "geo_series" in text and "seo_series" in text  # 它就是要依赖上层
    # 但必须**函数内**惰性导入,否则和各系列的触发点互相成环
    assert "\nfrom ..geo_series" not in text
    assert "\nfrom ..seo_series" not in text


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


# ===================================================================
# Woo 批量同步（产品卡片的图与真实链接）
# ===================================================================


def test_woo_fetch_is_batched_and_asks_for_the_attachment_id() -> None:
    """控制台本地没有可用的公网图 URL（磁盘路径 / 要鉴权的端点 / 会过期的 job token），
    所以带图卡片的图只能来自 Woo。一次调用拿四样：在不在线、真实地址、主图、**附件 id**。

    附件 id 最值钱：插件用 wp_get_attachment_image 能出 srcset/width/height，
    零布局抖动，而且走 WP 已生成的缩略图而不是把 2000px 原图塞进 300px 卡片。
    """
    import inspect

    from backend.app.modules.content_core import wc_sync

    assert wc_sync._BATCH == 50
    src = inspect.getsource(wc_sync.fetch_product_states)
    assert "include" in src and "per_page" in src
    for field in ("permalink", "status", "images"):
        assert field in src
    assert '"image_id"' in src


def test_woo_fetch_failing_returns_none_not_empty() -> None:
    """打不通返回 None **不是空字典**——空字典会让调用方以为"这些产品全没了"，
    一次网络抖动就能把全站产品卡片清空。"""
    import inspect

    from backend.app.modules.content_core import wc_sync

    src = inspect.getsource(wc_sync.fetch_product_states)
    assert "reached_any" in src
    assert "return out if reached_any else None" in src
    assert wc_sync.fetch_product_states(None, [1]) is None


def test_product_links_use_the_real_permalink() -> None:
    """?p=4148 靠 WP 的 301 才到得了，多一跳、难看、分享出去看不出是什么。
    latest_public_url 不出网，优先用它。"""
    import inspect

    from backend.app.modules.seo_series.content import links

    src = inspect.getsource(links._product_links)
    assert "latest_public_url" in src
    assert "pretty or f" in src  # 真链接优先，?p= 只是兜底


# ===================================================================
# 链接图（整套自动化的核心）
# ===================================================================


def test_link_map_is_keyed_by_post_id_not_wp_term_id() -> None:
    """B2B 那套用 WP 分类 term id 做键，因为 GEO 指南的分类**就是**谷歌类目。
    但 SEO 文章故意不落谷歌类目（落了会被 barong-geo-archive 连坐排除出博客归档），
    它们拿到的是**体裁分类**（6 个）。照抄 term id 会让一个体裁下所有文章
    拿到同一批产品卡片。"""
    import inspect

    from backend.app.modules.content_links import link_graph

    src = inspect.getsource(link_graph._live_articles)
    assert "wp_post_id" in src
    assert "str(item.wp_post_id)" in src
    # 只收线上真可见的
    assert 'wp_status == "publish"' in src


def test_link_map_is_deterministic() -> None:
    """指纹短路（"内容没变就一个字节都不发"）只在图完全确定时才有意义。
    任何不稳定排序都会让指纹每次都变 → 每 15 分钟往 WP 写一次，护栏形同虚设。"""
    import inspect

    from backend.app.modules.content_links import link_graph

    src = inspect.getsource(link_graph.build_link_map)
    assert "sorted(" in src
    canon = inspect.getsource(link_graph.canonical_json)
    assert "sort_keys=True" in canon
    # 内部绝不放时间戳
    assert "内部绝不放时间戳" in canon


def test_link_map_never_carries_a_price() -> None:
    """GMC 因为"页面价 ≠ feed 价"封过两次，只剩一次申诉。
    文章页出现产品价格 = 又开一个价格面。契约层就不放这个字段。"""
    import inspect

    from backend.app.modules.content_links import link_graph

    src = inspect.getsource(link_graph)
    assert "绝不放价格" in src
    built = inspect.getsource(link_graph.build_link_map)
    for forbidden in ("price", "regular_price", "sale_price"):
        assert f'"{forbidden}"' not in built


def test_link_map_caps_links_per_post() -> None:
    from backend.app.modules.content_links import link_graph

    assert link_graph.MAX_PRODUCTS_PER_POST == 3
    assert link_graph.MAX_GUIDES_PER_POST == 3
    assert link_graph.MAX_FACTORY_PER_POST == 3


def test_token_matched_cards_are_flagged_for_human_review() -> None:
    """词面匹配现在变成一张带图大卡片，猜错的代价比一行小字大得多
    （2026-07-30「包子捏捏挂到户外店批发文」）。至少要让人能扫一眼。"""
    import inspect

    from backend.app.modules.content_links import link_graph

    pick = inspect.getsource(link_graph._pick_products)
    assert "overlap >= 2" in pick  # 一个通用词的重合不构成相关
    assert '"tokens"' in pick and '"category"' in pick
    assert "token_matched" in inspect.getsource(link_graph.summarize)


def test_link_map_only_normalizes_cards_that_are_actually_used() -> None:
    """卡片只存一份，posts 里放 id 引用。这个 JSON 要塞进一个 WP option，
    大小直接决定站点快慢。"""
    import inspect

    from backend.app.modules.content_links import link_graph

    src = inspect.getsource(link_graph.build_link_map)
    assert "used_products" in src
    assert "别把整个目录塞进 option" in src


def test_push_has_all_four_guardrails() -> None:
    """指纹短路 / 15 分钟间隔 / dirty 标志 / 出网前放事务——缺一条都会出事。"""
    import inspect

    from backend.app.modules.content_links import link_push

    push = inspect.getsource(link_push.push_link_map)
    # ① 指纹短路
    assert "new_fingerprint == _get(db, FINGERPRINT_KEY)" in push
    assert "内容没有变化，未推送" in push
    # ④ 出网前放掉事务
    assert push.index("db.commit()") < push.index("_resolve_credentials")

    due = inspect.getsource(link_push.refresh_if_due)
    # ② 间隔，手动不受限
    assert "if manual:" in due
    assert "_waited_long_enough" in due
    # ③ 被挡下要置 dirty
    assert 'DIRTY_KEY, "1"' in due
    assert "丢掉最后几个" in due

    assert link_push.MIN_LINK_MAP_INTERVAL_MINUTES == 15


def test_push_failure_marks_dirty_so_it_retries() -> None:
    import inspect

    from backend.app.modules.content_links import link_push

    src = inspect.getsource(link_push.push_link_map)
    assert src.index("推送失败") > src.index('DIRTY_KEY, "1"') or 'DIRTY_KEY, "1"' in src
    # 挂在回报里的版本绝不许把回报带崩
    assert "except Exception" in inspect.getsource(link_push.refresh_link_map_safely)


# ===================================================================
# barong-content-cta 瘦插件（本地 bywp2 已跑通九条清单）
# ===================================================================


def _cta_plugin_source() -> str:
    from pathlib import Path

    return Path(
        "backend/app/modules/content_links/wordpress/plugins/barong-content-cta.php"
    ).read_text()


def test_cta_plugin_option_name_matches_the_console() -> None:
    """跨文件断言。option 名一旦漂移，控制台推的东西插件读不到，
    而且两边各自都"看起来对"——这是唯一能真正抓住这种漂移的测试。"""
    from backend.app.modules.content_links.link_push import (
        CTA_STYLE_OPTION,
        LINK_MAP_OPTION,
    )

    php = _cta_plugin_source()
    assert f"'{LINK_MAP_OPTION}'" in php
    assert f"'{CTA_STYLE_OPTION}'" in php


def test_cta_plugin_never_shows_a_price_or_schema() -> None:
    """GMC 因为「页面价 ≠ feed 价」封过两次，只剩一次申诉。
    文章页出现产品价格 = 又开一个价格面。结构化数据只能从产品页出。"""
    import re

    # 把注释剥掉再查——文件头正是在解释"绝不出现这些",别把说明当违规
    # （2026-07-31 第一版断言就这么自己绊了自己）。
    php = _cta_plugin_source()
    php = re.sub(r"/\*.*?\*/", "", php, flags=re.S)
    php = re.sub(r"^\s*//.*$", "", php, flags=re.M)
    for forbidden in ("regular_price", "sale_price", "itemprop", "schema.org"):
        assert forbidden not in php.lower()


def test_cta_plugin_does_not_render_wholesale_links() -> None:
    """b2b 插件已经在 the_content @20 渲染批发那一行。两边都渲染就出现两遍。"""
    import re

    php = _cta_plugin_source()
    php = re.sub(r"/\*.*?\*/", "", php, flags=re.S)
    php = re.sub(r"^\s*//.*$", "", php, flags=re.M)
    assert "wholesale" not in php.lower()


def test_cta_plugin_hook_priorities_avoid_the_b2b_one() -> None:
    """阅读顺序：正文 → 产品卡片(15) → 相关内容(18) → 批发(b2b 的 20)。
    本地 bywp2 三方实测通过。"""
    php = _cta_plugin_source()
    assert "'by_cta_product_card', 15" in php
    assert "'by_cta_related_links', 18" in php
    assert ", 20 )" not in php.replace("'by_cta_ensure_autoload_off', 20", "")


def test_cta_plugin_guards_and_reentrancy() -> None:
    """the_content 一个请求会被摘要 / 相关文章 / SEO 插件触发多次。"""
    php = _cta_plugin_source()
    assert php.count("static $done = false;") == 2  # 两个 filter 各一个闩
    assert "static $printed = false;" in php  # 样式只输出一次
    for guard in ("is_admin()", "REST_REQUEST", "DOING_CRON", "is_feed()",
                  "is_singular( 'post' )", "in_the_loop()", "is_main_query()"):
        assert guard in php


def test_cta_plugin_turns_autoload_off_only_after_the_option_exists() -> None:
    """option 还不存在时 wp_set_option_autoload 无事可做。这时候落闩，
    以后控制台第一次推送创建它会带着 autoload=yes 永远关不掉——
    几十 KB 的链接图在每个请求里被加载。2026-07-31 本地实测踩到。"""
    php = _cta_plugin_source()
    assert "wp_set_option_autoload" in php
    assert "false === get_option( BY_CTA_LINKS_OPTION, false )" in php


def test_cta_plugin_uses_the_attachment_id_for_zero_cls() -> None:
    """附件 id 能出 srcset / width / height / loading=lazy，而且走 WP 已生成的
    缩略图——不会把 2000px 原图塞进 300px 卡片。附件被删才降级到原始 URL。"""
    php = _cta_plugin_source()
    assert "wp_get_attachment_image(" in php
    assert "wp_attachment_is_image(" in php
    assert "loading=\"lazy\"" in php or "'loading' => 'lazy'" in php


def test_cta_plugin_degrades_to_nothing_on_bad_data() -> None:
    """坏 JSON / 空 option → 什么都不渲染（**不是空盒子**）。本地实测通过。"""
    php = _cta_plugin_source()
    assert "is_array( $parsed ) ? $text : ''" in php
    assert "if ( '' === $html ) {" in php


def test_cta_plugin_strips_legacy_inline_blocks() -> None:
    """老文章正文里还留着早期直接拼进去的链接块。在渲染时摘掉，
    不用把所有文章重发一遍（重发要过审阅状态门）。"""
    php = _cta_plugin_source()
    assert "barong-seo-links" in php
    assert "preg_replace" in php


def test_cta_plugin_has_a_sentinel_ping() -> None:
    """插件被停用 = 全站文章的卡片一次性消失，必须能在哨兵面板看见。"""
    php = _cta_plugin_source()
    assert "by-cta-ping" in php
    assert "hash_equals" in php


# ===================================================================
# 自动刷新的接线
# ===================================================================


def test_all_three_triggers_use_the_safe_wrapper() -> None:
    """内链是增益，上架/发布回报是本职。内链出问题绝不许把那次回报带崩。"""
    import inspect

    from backend.app.modules.geo_series.content import (
        publish_jobs as geo_publish,
    )
    from backend.app.modules.p_series.upload import jobs as p_jobs
    from backend.app.modules.seo_series.content import publish_jobs as seo_publish

    for module, fn in (
        (p_jobs, p_jobs.record_result),
        (geo_publish, geo_publish.record_result),
        (seo_publish, seo_publish.record_result),
    ):
        src = inspect.getsource(fn)
        assert "refresh_link_map_safely" in src, module.__name__
        # 裸调 refresh_if_due 会把异常直接抛进回报路径
        assert "refresh_if_due(" not in src, module.__name__


def test_daily_endpoint_is_fail_closed() -> None:
    """密钥没配一律 403——绝不因为忘了配环境变量就变成裸端点。"""
    import inspect

    from backend.app.modules.content_links import machine_router

    src = inspect.getsource(machine_router.refresh_link_map)
    assert "compare_digest" in src
    assert "not expected" in src
    # 兜底那一轮必须先核线上真实发布状态,否则会把草稿挂进卡片
    assert src.index("refresh_geo(db)") < src.index("refresh_if_due(db)")
    assert "refresh_seo(db)" in src


def test_daily_workflow_is_offset_from_the_b2b_one() -> None:
    """两条流都要批量核 WordPress 状态，同时打会压 WP.com。
    03:00 b2b / 03:20 内链网。以后加第三条要继续错开。"""
    import json

    from backend.app.modules.b2b.n8n.build_republish_workflow import (
        build as b2b_build,
    )
    from backend.app.modules.content_links.n8n.build_content_links_workflow import (
        CONTENT_LINKS_TOKEN_VALUE,
        build,
    )

    wf, b2b = build(), b2b_build()
    assert wf["id"] == "barongContentLinks001"
    # n8n 按 id 认节点——撞了就是改了别人的流
    assert not ({n["id"] for n in wf["nodes"]} & {n["id"] for n in b2b["nodes"]})
    assert wf["versionId"] != b2b["versionId"]
    cron = [
        n["parameters"]["rule"]["interval"][0]["expression"]
        for n in wf["nodes"]
        if n["type"].endswith("scheduleTrigger")
    ]
    assert cron == ["20 3 * * *"]
    # 一把钥匙开两把锁等于没锁
    assert CONTENT_LINKS_TOKEN_VALUE not in json.dumps(b2b)


def test_manual_refresh_bypasses_the_interval_but_not_the_fingerprint() -> None:
    """人明确说了要立刻看效果就不该被 15 分钟挡住；
    但"内容没变"仍然不该往 WP 写——那是浪费也是噪音。"""
    import inspect

    from backend.app.modules.seo_series.router import link_net_refresh

    src = inspect.getsource(link_net_refresh)
    assert "manual=True" in src


def test_link_net_panel_state_costs_no_wp_calls() -> None:
    """面板要能随时打开。产品页的"过期数"靠上次写进去的块指纹算，零 WP 调用。"""
    import inspect

    from backend.app.modules.seo_series.router import link_net_state

    src = inspect.getsource(link_net_state)
    assert "stale_count" in src
    # 一处算不出来不该让整块面板打不开
    assert "except Exception" in src


def test_wholesale_link_is_rendered_in_exactly_one_place() -> None:
    """b2b 插件已经在 the_content @20 按文章实际挂的类目渲染批发那一行。
    文末块再出一次，同一篇文章末尾就会出现两遍。"""
    import inspect

    from backend.app.modules.seo_series.content import links

    src = inspect.getsource(links.links_block_html)
    assert '"wholesale"' not in src
    assert "Buying for a store" not in src
    # 解析器保留 wholesale 意图（生成提示词里写着这个 kind，改提示词会牵动
    # 已批准内容的重生成），只是不再渲染
    assert "wholesale" in inspect.getsource(links.resolve_link_intents)


def test_inline_link_block_is_kept_as_a_fallback() -> None:
    """插件停用 = 中段卡片全消失。正文里留一份裸链，文章不至于变孤岛。
    这是我和方案 agent 唯一的分歧处——它建议全删。"""
    import inspect

    from backend.app.modules.seo_series.content import assemble, links

    assert "links_block_html" in inspect.getsource(assemble.render_article_html)
    assert "保底裸链" in inspect.getsource(links.links_block_html)


def test_push_verifies_the_option_actually_landed() -> None:
    """🔴 WP 只接受 register_setting 注册过的 option。插件没装时 /settings 会
    **静默忽略**未知字段并照样返回 200。

    2026-07-31 线上实测：推送报告 changed=true / 1130 字节，而 WP 那边 option
    长度是 0——指纹却已经记下了。后果是以后装上插件，控制台因为指纹一致
    **再也不会推**，CTA 永远不出现，而且没人知道为什么。

    **外部副作用报告成功 ≠ 真的发生了。** 回读一次是唯一能分辨的办法。
    """
    import inspect

    from backend.app.modules.content_links import link_push

    src = inspect.getsource(link_push.push_link_map)
    # 回读必须在记指纹之前
    assert src.index("stored != payload") < src.index("_set(db, FINGERPRINT_KEY")
    # 没存住要置 dirty 并说人话，不能默默算成功
    assert "插件还没装" in src
    assert src.count('_set(db, DIRTY_KEY, "1")') >= 2


def test_fixed_failures_stop_showing_as_errors() -> None:
    """2026-07-31 用户看到「生成失败：'SeoContentItem' object has no attribute
    'item_type'」以为是新问题——其实是前一天的记录，bug 一分钟后就修了、
    后面两次都成功了。

    **修好的东西一直红着，比不显示更糟：它会让人对真正的报错脱敏。**

    判据不是"多久以前"，而是"这个选题后来成没成"——一个三天前失败、
    至今没成功过的任务仍然该显示。
    """
    import inspect

    from backend.app.modules.seo_series.content import generation_jobs

    src = inspect.getsource(generation_jobs.jobs_status)
    assert "superseded" in src
    assert "last_success" in src
    # 按选题比对，不是按时间窗
    assert 'r["topic_id"] in last_success' in src
    assert "脱敏" in src

    from pathlib import Path

    deck = Path("frontend/src/modules/seo/SeoDeck.tsx").read_text()
    assert "!j.superseded" in deck
    # 仍在显示的失败要带时间，否则还是看不出新旧
    assert "j.finished_at" in deck


def test_stranded_records_are_detected_and_resettable() -> None:
    """「标了完成，产物却不存在」必须有东西看着。

    2026-08-01 用户问「geo/seo/内链网是不是都做完了」，我一条条查库才发现
    SEO 选题 e52c512c 被标成 written、库里一篇文章都没有——07-30 那个
    item_type bug 的残留（文章回滚了，选题状态和 job 状态各自提交了）。

    后果不是"少一篇文章"，而是**它永远不会再被派出去生成**。这种记录不报错、
    不变红、不在任何列表里。那次的 bug 早修了，但"没人看着"才是真缺口。
    """
    import inspect

    from backend.app.modules.content_core import consistency

    kinds = {c.parent for c in consistency.CHECKS}
    # GEO 侧是同一个形状（簇标 ready/approved 却零条目），必须一起覆盖，
    # 否则下次在 GEO 重演一遍。
    assert "seo_topics" in kinds
    assert "geo_content_clusters" in kinds

    seo = next(c for c in consistency.CHECKS if c.parent == "seo_topics")
    # 复位回 picked 而不是 candidate——选题是人挑过的，别把那次决定也抹掉。
    assert seo.reset_to == "picked"
    assert "written" in seo.done_status

    reset_src = inspect.getsource(consistency.reset_stranded)
    # 写的时候自己再验一次，而不是信任读到的列表：否则一次误点就可能把已经
    # 有文章的记录打回去，让人重复生成（花钱）。
    assert "NOT EXISTS" in reset_src

    find_src = inspect.getsource(consistency.find_stranded)
    assert "NOT EXISTS" in find_src

    # 表名/列名虽是代码常量，仍要过白名单——成本为零，且是前提被打破时的唯一拦网
    import pytest

    with pytest.raises(consistency.ConsistencyError):
        consistency.ProductionCheck(
            label="x",
            parent="seo_topics; drop table users",
            child="seo_content_items",
            child_fk="topic_id",
            done_status=("written",),
            reset_to="picked",
            name_column="keyword",
        )


def test_link_net_panel_is_findable_in_seo_deck() -> None:
    """2026-08-01 用户原话：「我怎么没看到内链网在哪里？」

    直接原因：SeoDeck 里 LinkNetPanel 是光秃秃两张卡片飘在发布页签中间，
    **没有任何标题**；GEO 那边一直包在写着「内链网」的框里。同一个组件在
    两个面板里长得不一样，等于在一边把它藏了起来。
    """
    from pathlib import Path

    deck = Path("frontend/src/modules/seo/SeoDeck.tsx").read_text()
    panel_at = deck.index("<LinkNetPanel />")
    # 标题必须在组件之前、且离得足够近（在同一个框里）
    title_at = deck.rindex("内链网", 0, panel_at)
    assert panel_at - title_at < 400

    for path in (
        "frontend/src/modules/seo/SeoDeck.tsx",
        "frontend/src/modules/geo/content/GeoContentDeck.tsx",
    ):
        assert "<ContentHealthPanel />" in Path(path).read_text(), path
