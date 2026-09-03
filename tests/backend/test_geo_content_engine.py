"""GEO content engine — milestone 1 (content engine).

Behavioral tests for the output guards (the fail-closed core) + source/wiring
assertions for the skill, orchestrator, queue, and router.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

# Load the app model registry first so importing geo modules directly does not
# trip the (K-style) circular import through backend.app.models.
import backend.app.models  # noqa: F401,E402

pytestmark = pytest.mark.unit


# --------------------------------------------------------------- guards


def test_evidence_number_corpus_extracts_spec_numbers() -> None:
    from backend.app.modules.content_core.guards import evidence_number_corpus

    corpus = evidence_number_corpus(
        "2.11 GPM flow", "90 minutes runtime", "6.5 ft hose", "IPX8"
    )
    assert "2.11" in corpus
    assert "90" in corpus
    assert "6.5" in corpus


def test_audit_passes_clean_grounded_item() -> None:
    from backend.app.modules.content_core.guards import (
        audit_content_item,
        evidence_number_corpus,
    )

    corpus = evidence_number_corpus("2.11 GPM", "6.5 ft hose")
    item = {
        "title": "How the pump works",
        "sections": [
            {"heading": "Flow", "body": "It pushes 2.11 GPM through the 6.5 ft hose."}
        ],
        "seo": {"title": "t", "meta_description": "m"},
    }
    audit = audit_content_item(item, forbidden_terms=[], evidence_numbers=corpus)
    assert audit["clean"] is True


def test_audit_flags_third_party_brand() -> None:
    from backend.app.modules.content_core.guards import audit_content_item

    item = {"title": "The Ivation shower beats it", "sections": []}
    audit = audit_content_item(
        item, forbidden_terms=["ivation"], evidence_numbers=set()
    )
    assert audit["clean"] is False
    assert audit["brand_violations"]


def test_audit_flags_ungrounded_number() -> None:
    from backend.app.modules.content_core.guards import audit_content_item

    item = {
        "title": "Spec",
        "sections": [{"heading": "x", "body": "It delivers 9.99 GPM of flow."}],
    }
    audit = audit_content_item(
        item, forbidden_terms=[], evidence_numbers={"2.11"}
    )
    assert audit["clean"] is False
    assert any(u["number"] == "9.99" for u in audit["ungrounded_numbers"])


def test_audit_flags_cjk_leakage() -> None:
    from backend.app.modules.content_core.guards import audit_content_item

    item = {"title": "含中文的标题", "sections": []}
    audit = audit_content_item(item, forbidden_terms=[], evidence_numbers=set())
    assert audit["clean"] is False
    assert audit["cjk_surfaces"]


# --------------------------------------------------------------- skill


def test_geo_skill_enforces_grounding_brand_and_citability() -> None:
    from backend.app.modules.geo_series.content.prompt_skills import (
        geo_content_instruction,
    )

    prompt = geo_content_instruction()
    # grounding: no invented numbers/competitors
    assert "NEVER invent a number" in prompt
    # brand hard line
    assert "site_brand" in prompt
    # citability: self-contained extractable answers
    assert "self-contained" in prompt
    # Rail 1: name + link the product
    assert "source_products" in prompt
    # imperial + no CJK
    assert "imperial" in prompt


# --------------------------------------------------------------- orchestrator


def test_orchestrator_grounds_and_reuses_k_guards() -> None:
    from backend.app.modules.geo_series.content import orchestrator as orch

    src = inspect.getsource(orch)
    # reuses K brand/buyer-display guards
    assert "sanitize_snapshot_for_generation" in src
    assert "buyer_display_structured_specs" in src
    # borrows K's module gate/key binding for the AI call
    assert "MODULE_KEY as K_MODULE_KEY" in src
    assert "AIExecutionRouter" in src
    # releases the read txn before the long AI call (idle-in-txn rule)
    call = inspect.getsource(orch.GeoContentOrchestrator.generate_cluster)
    assert "self.db.commit()" in call
    # audits every generated item before persisting
    assert "audit_content_item" in inspect.getsource(
        orch.GeoContentOrchestrator._replace_items
    )


# --------------------------------------------------------------- queue/worker


def test_geo_queue_mirrors_k_worker_semantics() -> None:
    from backend.app.modules.geo_series.content import generation_jobs as gj

    src = inspect.getsource(gj)
    assert "FOR UPDATE SKIP LOCKED" in src
    assert "geo_generation_jobs" in src
    # a failed job must not strand the cluster in 'generating'
    assert "_reset_cluster_after_failure" in src
    # standalone worker entry
    from backend.app.modules.geo_series.content import worker_main

    assert callable(worker_main.main)


# --------------------------------------------------------------- router/wiring


def test_geo_router_endpoints_and_permission_gate() -> None:
    from backend.app.modules.geo_series.router import router, _require_geo_permission

    paths = {r.path for r in router.routes}
    assert "/geo/clusters" in paths
    assert "/geo/clusters/from-product" in paths
    assert "/geo/clusters/{cluster_id}/generate" in paths
    assert "/geo/items/{item_id}/review" in paths
    # execute/manage imply read
    gate_src = inspect.getsource(_require_geo_permission)
    assert "PERMISSION_EXECUTE" in gate_src
    assert "PERMISSION_MANAGE" in gate_src


def test_geo_module_registered_and_org_gated() -> None:
    from backend.app.core.modules import MODULE_MANIFESTS_V1
    from backend.app.services.module_registry import (
        INTL_TRADE_ONLY_MODULE_KEYS,
        validate_module_manifests,
    )

    validate_module_manifests(MODULE_MANIFESTS_V1)
    keys = {m["module_key"] if isinstance(m, dict) else m.module_key for m in MODULE_MANIFESTS_V1}
    assert "geo.content" in keys
    # 独立站系列——只属国际贸易组织
    assert "geo.content" in INTL_TRADE_ONLY_MODULE_KEYS


def test_geo_permission_sync_migration_exists() -> None:
    # The registry only auto-seeds when empty, so a table-creating module MUST
    # ship a permission-sync migration or it stays invisible on existing DBs.
    from pathlib import Path

    migration = Path(
        "backend/alembic/versions/20260728_02_geo_permissions.py"
    ).read_text(encoding="utf-8")
    assert "permission_registry" in migration
    assert "geo.content.read" in migration


# ===================================================================
# Milestone 2 — topic sourcing
# ===================================================================


def test_topic_sourcing_accept_gate_filters_garbage() -> None:
    from backend.app.modules.geo_series.content import topic_sourcing as ts

    # clean real buyer questions survive
    assert ts._accept("How does a portable camping shower pump draw water?")
    assert ts._accept("Can you use a portable camping shower for van life?")
    # garbage is rejected: malfunction, spec-paraphrase, 3rd-party brand, non-question
    assert not ts._accept("Why does my shower pump keep running but no leak?")
    assert not ts._accept("What are the dimensions of the camping shower?")
    assert not ts._accept("Is the Ivation shower any good?")
    assert not ts._accept("best portable camping shower")


def test_topic_sourcing_scores_paa_and_howto_higher() -> None:
    from backend.app.modules.geo_series.content import topic_sourcing as ts

    paa_howto = ts._score("people_also_ask", "operation", 1)
    organic_vague = ts._score("organic_question", "buyer_concern", 8)
    assert paa_howto > organic_vague
    # source weight + intent bonus both contribute
    assert ts._score("people_also_ask", "operation", 5) > ts._score(
        "organic_question", "operation", 5
    )


def test_topic_sourcing_reuses_only_existing_data() -> None:
    # reuse-only: no Serper client / network in the candidate sourcing module.
    from backend.app.modules.geo_series.content import topic_sourcing as ts

    src = inspect.getsource(ts)
    # no Serper client / network call / ledger consume — reads existing DB only
    assert "serper_client" not in src
    assert "serper_search" not in src
    assert "try_consume" not in src
    assert "faq_research_json" in src
    assert "FCategoryKeyword" in src


def test_orchestrator_injects_and_enforces_required_questions() -> None:
    from backend.app.modules.geo_series.content import orchestrator as orch

    gen = inspect.getsource(orch.GeoContentOrchestrator.generate_cluster)
    assert "required_questions" in gen
    assert "picked_questions_json" in gen
    # output enforcement: qa answer_blocks must match a picked question
    repl = inspect.getsource(orch.GeoContentOrchestrator._replace_items)
    assert "picked_norm" in repl
    # dedup projection helper
    rq = orch._required_questions(
        [{"question": "How does it work?", "intent": "operation"}, {"question": "how does it work"}]
    )
    assert len(rq) == 1


def test_geo_prompt_states_required_questions_are_server_owned() -> None:
    from backend.app.modules.geo_series.content.prompt_skills import (
        geo_content_instruction,
    )

    prompt = geo_content_instruction()
    assert "REQUIRED QUESTIONS" in prompt
    assert "SERVER-OWNED" in prompt
    assert "verbatim" in prompt.lower() or "EXACTLY" in prompt


def test_geo_topic_endpoints_wired() -> None:
    from backend.app.modules.geo_series.router import router

    paths = {r.path for r in router.routes}
    assert "/geo/clusters/{cluster_id}/topic-candidates" in paths
    assert "/geo/clusters/{cluster_id}/picked-questions" in paths


def test_geo_picked_questions_migration_exists() -> None:
    from pathlib import Path

    migration = Path(
        "backend/alembic/versions/20260728_04_geo_picked_questions.py"
    ).read_text(encoding="utf-8")
    assert "picked_questions_json" in migration
    assert "add_column" in migration


# ===================================================================
# Auto-cluster on P upload + one-cluster-per-category + spotlight
# ===================================================================


def test_p_upload_success_auto_attaches_geo_cluster() -> None:
    from backend.app.modules.p_series.upload import jobs

    src = inspect.getsource(jobs.record_result)
    assert "ensure_geo_cluster_for_product_safely" in src
    # GEO must never break the upload report (mirrors the B2B ingest wrapper)
    from backend.app.modules.geo_series.content import ingest_from_p

    wrapper = inspect.getsource(ingest_from_p.ensure_geo_cluster_for_product_safely)
    assert "except Exception" in wrapper


def test_one_cluster_per_category_attaches_instead_of_duplicating() -> None:
    # 5 near-identical stress balls share a category → ONE cluster, not five
    # duplicate ones (self-competition + thin content).
    from backend.app.modules.geo_series.content import ingest_from_p

    src = inspect.getsource(ingest_from_p.ensure_geo_cluster_for_product)
    # 类目 → 簇的解析已下沉 cluster_guard（它还多守了祖先/后代重叠）
    assert "resolve_cluster_for_category" in src
    from backend.app.modules.geo_series.content import cluster_guard

    assert "google_id in by_category" in inspect.getsource(
        cluster_guard.resolve_cluster_for_category
    )
    # attaching appends to the product list + records it as pending
    assert "product_ids_json" in src
    assert "pending_product_ids_json" in src


def test_attached_product_does_not_invalidate_approved_content() -> None:
    # Option A (user ruling): approved content is untouched when a product is
    # attached; only a pending hint is recorded for the operator to act on.
    from backend.app.modules.geo_series.content import ingest_from_p

    src = inspect.getsource(ingest_from_p.ensure_geo_cluster_for_product)
    # never touches generated content
    assert "GeoContentItem" not in src
    assert "delete" not in src.lower()
    # never silently resets an existing cluster's review state
    attach_branch = src.split("# Existing cluster")[-1]
    assert "cluster.status" not in attach_branch
    # and it does record the hint
    assert "pending_product_ids_json" in attach_branch


def test_cluster_products_flag_is_advisory_not_automatic() -> None:
    from backend.app.modules.geo_series.content import service

    src = inspect.getsource(service.cluster_products)
    # surfaces evidence for the operator; never auto-creates a spotlight
    assert "differentiated" in src
    assert "unique_points" in src
    assert "generate_product_spotlight" not in src


def test_differentiation_hint_is_conservative() -> None:
    # Copywriting always varies, so word novelty alone flags EVERY product (five
    # stress balls differing only in shape lit up 5/5 in production data). The
    # hint must require functional novelty — attributes the siblings lack.
    from backend.app.modules.geo_series.content import service

    src = inspect.getsource(service.cluster_products)
    assert "unique_specs" in src
    assert "len(unique_specs) >= 2" in src
    assert "unique_ratio > 0.5" in src
    # a product's own name words never count as novelty ("cheese", "butter", …)
    fingerprint = inspect.getsource(service._selling_point_set)
    assert "product_name_en" in fingerprint


def test_product_spotlight_is_opt_in_and_server_owned() -> None:
    from backend.app.modules.geo_series.content import orchestrator as orch

    src = inspect.getsource(orch.GeoContentOrchestrator.generate_product_spotlight)
    # the piece belongs to the requested product regardless of what the model wrote
    assert "source_product_ids_json=[product_key]" in src
    # contrasts against siblings, still guarded
    assert "sibling_products" in src
    assert "audit_content_item" in src
    # one spotlight per product (replaces its own, not the cluster's other content)
    assert "product_spotlight" in src


def test_spotlight_prompt_leads_with_the_difference() -> None:
    from backend.app.modules.geo_series.content.prompt_skills import (
        geo_product_spotlight_instruction,
    )

    prompt = geo_product_spotlight_instruction()
    assert "distinct" in prompt
    assert "sibling_products" in prompt
    assert "NEVER invent a number" in prompt
    assert "site_brand" in prompt


# ===================================================================
# Regenerate safety + DeepSeek-flash review aid
# ===================================================================


def test_regenerate_preserves_approved_content_and_spotlights() -> None:
    # A re-run must never silently delete what the operator already approved,
    # nor the opt-in per-product spotlights.
    from backend.app.modules.geo_series.content import orchestrator as orch

    src = inspect.getsource(orch.GeoContentOrchestrator._replace_items)
    assert 'GeoContentItem.review_status != "approved"' in src
    assert 'GeoContentItem.item_type != "product_spotlight"' in src


def test_analysis_uses_the_cheap_flash_tier() -> None:
    from backend.app.services.ai_provider_router import AIModelRouter

    assert (
        AIModelRouter.resolve_model(provider="deepseek", task_type="content_analysis")
        == "deepseek-v4-flash"
    )
    # generation stays on the pro tier
    assert (
        AIModelRouter.resolve_model(provider="deepseek", task_type="generate")
        == "deepseek-v4-pro"
    )


def test_analysis_demands_specific_reading_not_boilerplate() -> None:
    from backend.app.modules.content_core.analysis import analysis_instruction

    prompt = analysis_instruction()
    assert "禁止套话" in prompt
    for field in ("translation", "geo_role", "why_written_this_way", "strengths", "risks"):
        assert field in prompt


def test_analysis_is_fail_open_and_never_blocks_content() -> None:
    from backend.app.modules.geo_series.content import analysis

    src = inspect.getsource(analysis.analyze_content)
    assert "except Exception" in src
    assert "return None" in src
    # 持久化适配器已下沉 content_core(表名变成参数),GEO 侧只剩薄封装。
    # 性质不变,断言跟着代码走。
    from backend.app.modules.content_core import analysis_persist

    wrapper = inspect.getsource(analysis_persist.attach_analysis_to)
    assert "except Exception" in wrapper
    assert "attach_analysis_to" in inspect.getsource(analysis.attach_analysis_safely)
    # generation attaches it after content is persisted
    from backend.app.modules.geo_series.content import orchestrator as orch

    gen = inspect.getsource(orch.GeoContentOrchestrator.generate_cluster)
    assert "attach_analysis_safely" in gen


def test_source_products_resolve_to_sku_for_display() -> None:
    # A raw product UUID means nothing to the operator.
    from backend.app.modules.geo_series.content import service

    src = inspect.getsource(service.product_label_map)
    assert "product_key" in src
    assert "sku" in src
    serialize = inspect.getsource(service.serialize_item)
    assert "source_product_labels" in serialize
    assert "analysis" in serialize


def test_geo_analyze_endpoint_wired() -> None:
    from backend.app.modules.geo_series.router import router

    assert "/geo/items/{item_id}/analyze" in {r.path for r in router.routes}


def test_analysis_never_holds_a_transaction_across_network_calls() -> None:
    # 死规矩 (踩过两次): an outbound call must not run inside an open DB
    # transaction — the idle-in-transaction timeout kills the connection.
    # Snapshot payloads, COMMIT, then call, then write each result separately.
    from backend.app.modules.content_core import analysis_persist

    src = inspect.getsource(analysis_persist.attach_analysis_to)
    snapshot_at = src.index("_item_payload(item)")
    commit_at = src.index("db.commit()")
    call_at = src.index("analyze_content(")
    assert snapshot_at < commit_at < call_at, "must snapshot → commit → call"
    # each result persists in its own short-lived session
    assert "SessionLocal() as writer" in src


# ===================================================================
# Closing the loop: revise against critique / patterns / data gaps
# ===================================================================


def test_revise_refuses_to_invent_facts_and_reports_gaps() -> None:
    from backend.app.modules.geo_series.content.prompt_skills import (
        geo_revise_instruction,
    )

    prompt = geo_revise_instruction()
    assert "绝不编造事实" in prompt
    assert "unaddressed" in prompt
    assert "missing_fact" in prompt
    # "compare with other brands" can never be satisfied by naming a competitor
    assert "site_brand" in prompt


def test_revise_resets_approval_and_stale_analysis() -> None:
    from backend.app.modules.geo_series.content import orchestrator as orch

    src = inspect.getsource(orch.GeoContentOrchestrator.revise_item)
    # a rewrite invalidates the prior approval and the prior reading
    assert 'item.review_status = "pending"' in src
    assert "item.analysis_json = None" in src
    # re-audited + re-analysed
    assert "audit_content_item" in src
    assert "attach_analysis_safely" in src
    # idle-txn rule before the AI call
    assert "self.db.commit()" in src


def test_unaddressed_entries_carry_the_missing_fact() -> None:
    from backend.app.modules.geo_series.content.orchestrator import _clean_unaddressed

    cleaned = _clean_unaddressed(
        [{"critique": "应说明充电功率", "reason": "规格里没有", "missing_fact": "充电功率"}]
    )
    assert cleaned[0]["needs_data"] is True
    assert cleaned[0]["missing_fact"] == "充电功率"


def test_critique_collection_is_network_free() -> None:
    from backend.app.modules.content_core import critique

    for fn in (critique.collect_critiques, critique.collect_data_gaps):
        src = inspect.getsource(fn)
        assert "AIExecutionRouter" not in src
        assert "SessionLocal" not in src


def test_data_gaps_group_by_missing_fact() -> None:
    from types import SimpleNamespace

    from backend.app.modules.content_core.critique import collect_data_gaps

    items = [
        SimpleNamespace(
            id="1",
            title="a",
            revision_json={
                "unaddressed": [
                    {"critique": "c1", "reason": "r", "needs_data": True, "missing_fact": "充电功率"}
                ]
            },
        ),
        SimpleNamespace(
            id="2",
            title="b",
            revision_json={
                "unaddressed": [
                    {"critique": "c2", "reason": "r", "needs_data": True, "missing_fact": "充电功率"},
                    {"critique": "c3", "reason": "r", "needs_data": False, "missing_fact": ""},
                ]
            },
        ),
    ]
    gaps = collect_data_gaps(items)
    assert len(gaps) == 1
    assert gaps[0]["missing_fact"] == "充电功率"
    assert len(gaps[0]["items"]) == 2


def test_summary_only_reports_recurring_patterns() -> None:
    from backend.app.modules.content_core.critique import (
        summarize_patterns,
        summary_instruction,
    )

    prompt = summary_instruction()
    assert "至少影响 2 篇" in prompt
    assert "写作规范" in prompt
    # a single critique is not a pattern — no provider call at all
    assert summarize_patterns([{"item_type": "qa", "critique": "x"}], topic="t") == []


def test_loop_endpoints_wired() -> None:
    from backend.app.modules.geo_series.router import router

    paths = {r.path for r in router.routes}
    assert "/geo/items/{item_id}/revise" in paths
    assert "/geo/clusters/{cluster_id}/critique-summary" in paths


# ===================================================================
# Incremental generation: never write the same topic twice
# ===================================================================


def test_generation_skips_topics_already_covered_by_kept_items() -> None:
    from backend.app.modules.geo_series.content import orchestrator as orch

    gen = inspect.getsource(orch.GeoContentOrchestrator.generate_cluster)
    # only the not-yet-covered questions go to the model
    assert "pending_questions" in gen
    assert "covered_questions" in gen
    # and the types approved pieces occupy are declared off-limits
    assert "skip_item_types" in gen
    assert "existing_content" in gen


def test_covered_questions_read_from_kept_answer_blocks() -> None:
    from types import SimpleNamespace

    from backend.app.modules.geo_series.content.orchestrator import _covered_questions

    kept = [
        SimpleNamespace(
            item_type="qa",
            body_json={
                "answer_blocks": [
                    {"question": "How long do portable showers last?"},
                    {"question": "Are they worth it?"},
                ]
            },
        )
    ]
    covered = _covered_questions(kept)
    # normalised (lowercased, trailing ? stripped) so wording variants still match
    assert "how long do portable showers last" in covered
    assert "are they worth it" in covered


def test_kept_items_are_approved_pieces_and_spotlights() -> None:
    from backend.app.modules.geo_series.content import orchestrator as orch

    src = inspect.getsource(orch.GeoContentOrchestrator._kept_items)
    assert 'review_status == "approved"' in src
    assert 'item_type == "product_spotlight"' in src


def test_server_enforces_skip_types_and_covered_questions() -> None:
    # The model is told what to skip, but the server must not trust it.
    from backend.app.modules.geo_series.content import orchestrator as orch

    src = inspect.getsource(orch.GeoContentOrchestrator._replace_items)
    assert "if item_type in skip_item_types:" in src
    assert "not in covered_questions" in src


def test_nothing_to_generate_is_a_friendly_conflict() -> None:
    from backend.app.modules.geo_series.content import orchestrator as orch

    gen = inspect.getsource(orch.GeoContentOrchestrator.generate_cluster)
    assert "GEO_NOTHING_TO_GENERATE" in gen
    assert "按批评重写" in gen


# ===================================================================
# Milestone 3 — publishing
# ===================================================================


def test_only_pretty_product_permalinks_are_linkable() -> None:
    # Live data trap: P creates products as drafts, so early upload rows hold the
    # draft-era ?post_type=product&p=… permalink. Linking that hands the buyer an
    # ugly URL — or a 404 while the product is still a draft.
    from backend.app.modules.geo_series.content.product_links import (
        _is_public_permalink,
    )

    assert _is_public_permalink(
        "https://barongyekhna.com/product/portable-camping-shower-kit/"
    )
    assert not _is_public_permalink(
        "https://barongyekhna.com/?post_type=product&p=4148"
    )
    assert not _is_public_permalink("")
    assert not _is_public_permalink("/product/relative-only/")


def test_publish_gate_requires_approval_audit_slug_and_live_products() -> None:
    from backend.app.modules.geo_series.content import publish_gate

    src = inspect.getsource(publish_gate.publish_blockers)
    assert "没有已批准的内容" in src
    assert "未通过自动审查" in src
    assert "url_slug" in src
    assert "不能链到 404" in src
    # only approved AND generated pieces are publishable
    ready = inspect.getsource(publish_gate.publishable_items)
    assert 'review_status == "approved"' in ready
    assert 'generation_status == "generated"' in ready


def test_intra_cluster_links_are_placeholders_until_posts_exist() -> None:
    from types import SimpleNamespace

    from backend.app.modules.content_core.publish_html import (
        render_article_html,
        resolve_link_tokens,
        unresolved_link_tokens,
    )

    item = SimpleNamespace(
        body_json={"sections": [{"heading": "H", "body": "B"}]},
        source_product_ids_json=["PSPE-001"],
    )
    html = render_article_html(
        item,
        product_links={"PSPE-001": "https://site/product/x/"},
        product_labels={"PSPE-001": "Portable Camping Shower"},
        sibling_links=[("Sibling", "item-2")],
    )
    # the product page exists → real link; the sibling post does not → placeholder
    assert "https://site/product/x/" in html
    assert unresolved_link_tokens(html) == ["{{GEO_LINK_item-2}}"]
    assert not unresolved_link_tokens(
        resolve_link_tokens(html, {"item-2": "https://site/guide-2/"})
    )


def test_publish_queue_mirrors_p_serial_semantics() -> None:
    """GEO 发布队列必须和 P 用**同一套**串行语义。

    2026-09-03 之前这里断的是源码文本（`kick.index("db.commit()") <
    kick.index("_send_to_n8n(job")`）。那种断言两头都靠不住：换个写法就绕过去，
    纯重构又会让它变红。现在五个模块共用 `services/n8n_dispatch.py`，
    四条不变量由 `tests/backend/test_n8n_queue_contract.py` **真跑**验证，
    这里只需要钉住「GEO 确实用的是那一份，没有自己再抄一遍」。
    """
    from backend.app.modules.geo_series.content import publish_jobs
    from backend.app.services import n8n_dispatch

    assert publish_jobs.IN_FLIGHT_TIMEOUT_MINUTES == 15
    assert isinstance(publish_jobs._QUEUE, n8n_dispatch.QueueSpec)
    assert publish_jobs._QUEUE.model is publish_jobs.GeoPublishJob
    # 看门狗文案必须含「未回传」——P 的 record_result 靠这三个字区分
    # 「推测的失败」和「事实的失败」，改掉会让迟到的成功翻不了案。
    assert "未回传" in publish_jobs._QUEUE.stale_error
    # 载荷里 n8n 取包和回调要用的三样，缺一整单静默失败
    payload = publish_jobs._QUEUE.build_payload(
        SimpleNamespace(
            job_id="j1", cluster_id="c1", channel="wp", token="t1"
        ),
        "https://base.test",
    )
    assert payload["token"] == "t1"
    assert "publish-package?token=t1" in payload["package_url"]
    assert payload["callback_url"].endswith("/geo/publishes/j1/result")
    # 终态幂等（这条仍是模块自己的逻辑，刻意没有合并）
    rec = inspect.getsource(publish_jobs.record_result)
    assert 'if job.status in ("success", "failed")' in rec
    assert "invalid job token" in rec


def test_guide_categories_mirror_k_google_taxonomy() -> None:
    # Owner's ruling: guides use K's Google taxonomy, not hand-made site
    # categories — and the SAME hardened algorithm P uses for product categories,
    # so the two trees cannot drift apart.
    from backend.app.modules.geo_series.content import wp_categories

    src = inspect.getsource(wp_categories)
    assert "/wp-json/wp/v2/categories" in src
    assert "wc_categories import" in src or "from ...p_series.upload.wc_categories" in src
    assert "geo_wp_category_map" in src
    # 死命令(2026-07-29,推翻了原来的"尽力而为"):建不出类目就整单拒发,
    # 绝不退化成无类目上线——那会让文章掉在全站结构之外。
    ensure = inspect.getsource(wp_categories.ensure_cluster_category)
    assert "return None" not in ensure
    assert "raise GeoCategoryError" in ensure


def test_publish_contract_is_versioned_and_closed() -> None:
    from backend.app.modules.geo_series.contract.publish_package import (
        GEO_PUBLISH_PACKAGE_VERSION,
        GuidePackage,
    )

    assert GEO_PUBLISH_PACKAGE_VERSION == "geo-publish-package-v1"
    assert GuidePackage.model_config.get("extra") == "forbid"


def test_geo_publish_workflow_is_brand_new_and_isolated() -> None:
    import json
    from pathlib import Path

    workflow = json.loads(
        Path(
            "backend/app/modules/geo_series/n8n/geo_publish_workflow.json"
        ).read_text(encoding="utf-8")
    )
    assert workflow["id"] == "barongGEOpublish001"
    blob = json.dumps(workflow, ensure_ascii=False)
    # 死命令: must never reuse or touch the product upload flow
    assert "wc/v3/products" not in blob
    assert "aPB82hXe9Rxdvyfo" not in blob  # the WooCommerce credential
    # hard-asserts the contract version before writing anything
    assert "geo-publish-package-v1" in blob
    # first create lands as a draft for human publication
    assert "status = 'draft'" in blob or "status: 'draft'" in blob
    names = {n["name"] for n in workflow["nodes"]}
    assert set(workflow["connections"]) <= names


def _geo_workflow() -> dict:
    import json
    from pathlib import Path

    return json.loads(
        Path(
            "backend/app/modules/geo_series/n8n/geo_publish_workflow.json"
        ).read_text(encoding="utf-8")
    )


def _geo_node(name: str) -> dict:
    for node in _geo_workflow()["nodes"]:
        if node["name"] == name:
            return node
    raise AssertionError(f"节点不存在: {name}")


def test_publish_workflow_maps_every_article_not_just_the_first() -> None:
    """首跑实测: `$input.first()` 把整簇 5 篇压成 1 篇,只建出一个 post。"""

    code = _geo_node("决定建或更新")["parameters"]["jsCode"]
    assert "$input.all()" in code
    assert "$input.first()" not in code


def test_publish_workflow_never_backfills_a_null_post() -> None:
    """首跑实测: 无内链可回填时旧代码发 post_id=null → 打到 /posts/null 报错,
    执行中断 → 控制台永远收不到回报,任务卡死在 dispatched。"""

    collect = _geo_node("收集URL并回填内链")["parameters"]["jsCode"]
    assert "post_id: null" not in collect
    assert "needs_backfill" in collect

    workflow = _geo_workflow()
    gate = _geo_node("有内链要回填?")
    assert gate["type"] == "n8n-nodes-base.if"
    branches = workflow["connections"]["有内链要回填?"]["main"]
    assert [c["node"] for c in branches[0]] == ["回填内链"]
    # false 分支必须直达回报,否则单篇簇(无互链)会走进死路
    assert [c["node"] for c in branches[1]] == ["整理回报"]

    # 回报的台账取自收集节点——回填分支走过 HTTP 后 $json 已经是 WP 响应
    report = _geo_node("整理回报")["parameters"]["jsCode"]
    assert "$('收集URL并回填内链')" in report


def test_publish_workflow_never_bakes_a_date_based_permalink() -> None:
    """草稿的 post.link 是 ?p=ID。站点结构为 /%postname%/ 时可以直接算出发布后的网址;
    但模板含日期占位时算了会错(发布日期决定网址)——必须退回 ?p=ID 让 WP 去 301。"""

    code = _geo_node("收集URL并回填内链")["parameters"]["jsCode"]
    assert "permalink_template" in code
    assert "%(year|monthnum|day|hour|minute|second)%" in code
    assert "canonicalUrl(post)" in code
    # 已有正式链接时绝不重算
    assert "if (link && link.indexOf('?p=') === -1) return link;" in code


def test_publish_workflow_writes_yoast_via_wp_meta_object() -> None:
    """wp/v2 posts 只认 `meta` 对象;`meta_data` 数组是 Woo 的形状,WP 静默丢弃
    (线上实测: 用 meta 写入后 context=edit 能读回)。"""

    code = _geo_node("拆文章")["parameters"]["jsCode"]
    assert "body.meta = meta" in code
    assert "meta_data:" not in code
    assert "_yoast_wpseo_title" in code and "_yoast_wpseo_metadesc" in code


def test_machine_endpoints_are_token_authenticated() -> None:
    from backend.app.modules.geo_series import machine_router

    src = inspect.getsource(machine_router)
    # package endpoint: token must match a job for THIS cluster
    assert "GeoPublishJob.token == token" in src
    assert "GeoPublishJob.cluster_id == cluster_id" in src
    # callback: X-Job-Token header
    assert "x_job_token" in src
    paths = {r.path for r in machine_router.router.routes}
    assert "/geo/clusters/{cluster_id}/publish-package" in paths
    assert "/geo/publishes/{job_id}/result" in paths


def test_guide_html_labels_products_with_their_public_h1_never_a_uuid() -> None:
    """线上事故 2026-07-29: 正文出现「The product in this guide 33dabc7b-…」。
    产品标签必须等于产品页 H1;拿不到标题宁可不渲染,绝不退回 UUID。"""
    from backend.app.modules.content_core.publish_html import render_article_html

    pid = "33dabc7b-83ea-4409-8b92-c086e6e91c26"

    class _Item:
        body_json = {"sections": [{"heading": "H", "body": "B"}]}
        source_product_ids_json = [pid]

    html = render_article_html(
        _Item(),
        product_links={pid: "https://example.com/product/x/"},
        product_labels={pid: "Portable Camping Shower – Rechargeable off-grid rinses"},
        sibling_links=[],
    )
    assert "Portable Camping Shower" in html
    assert pid not in html

    # 没有标题 → 整条不渲染,而不是把 UUID 摆到读者面前
    bare = render_article_html(
        _Item(),
        product_links={pid: "https://example.com/product/x/"},
        product_labels={},
        sibling_links=[],
    )
    assert pid not in bare
    assert "The product in this guide" not in bare


def test_product_display_title_follows_the_same_h1_chain_as_p_upload() -> None:
    from backend.app.modules.geo_series.content.product_links import (
        product_display_title,
    )

    class _P:
        id = "id-1"
        marketing_copy_json = {"seo": {"h1": "The H1", "title": "The SEO title"}}
        product_name_en = "English name"
        sku = "PSPE-001"
        product_key = "pspe_001"

    assert product_display_title(_P()) == "The H1"

    p = _P()
    p.marketing_copy_json = {"seo": {"title": "The SEO title"}}
    assert product_display_title(p) == "The SEO title"

    p.marketing_copy_json = None
    assert product_display_title(p) == "English name"


def test_guides_hub_shows_big_categories_but_never_the_full_breadcrumb() -> None:
    """主页要像 help center:大类目成卡片、叶子类目在卡片里。
    整条 A > B > C > D > E 面包屑绝不进正文——那会让整站看起来只做一个类目。"""
    from backend.app.modules.geo_series.content.guides_index import render_index_html

    path = (
        "Sporting Goods > Outdoor Recreation > Camping & Hiking > "
        "Portable Toilets & Showers > Portable Showers & Privacy Enclosures"
    )
    html = render_index_html(
        [
            {
                "category_path": path,
                "clusters": [
                    {
                        "title": "portable camping shower — buyer guide",
                        "articles": [{"title": "T", "url": "https://x/a/"}],
                    }
                ],
            }
        ]
    )
    assert "<h3>Sporting Goods</h3>" in html
    assert "<h4>Portable Showers &amp; Privacy Enclosures</h4>" in html
    assert "Outdoor Recreation &gt; Camping" not in html
    assert "1 guide<" in html


def test_guides_hub_has_a_search_box_and_manual_category_chips() -> None:
    from backend.app.modules.geo_series.content.guides_index import render_index_html

    html = render_index_html(
        [
            {
                "category_path": "Sporting Goods > A > Portable Showers",
                "clusters": [
                    {"title": "c1", "articles": [{"title": "t1", "url": "https://x/1/"}]}
                ],
            },
            {
                "category_path": "Toys & Games > B > Executive Toys",
                "clusters": [
                    {"title": "c2", "articles": [{"title": "t2", "url": "https://x/2/"}]}
                ],
            },
        ]
    )
    assert 'type="search"' in html
    assert html.count('class="geo-hub-chip"') == 3  # All + 两个大类目
    assert 'data-top="sporting-goods"' in html
    assert 'data-top="toys-games"' in html
    assert 'data-search="' in html
    # JS 关掉也要能用:默认不隐藏任何内容
    assert " hidden>" not in html


def test_guides_hub_search_haystack_covers_titles_and_categories() -> None:
    import re

    from backend.app.modules.geo_series.content.guides_index import render_index_html

    html = render_index_html(
        [
            {
                "category_path": "Sporting Goods > A > Portable Showers",
                "clusters": [
                    {
                        "title": "buyer guide",
                        "articles": [
                            {"title": "How the pump works", "url": "https://x/1/"}
                        ],
                    }
                ],
            }
        ]
    )
    hay = re.search(r'data-search="([^"]*)"', html).group(1)
    for term in ["how the pump works", "buyer guide", "portable showers", "sporting goods"]:
        assert term in hay


def test_guides_hub_collapses_article_lists() -> None:
    """页面会随类目/文章增长,列表必须可折叠;用原生 <details>,JS 关掉也能展开。"""
    from backend.app.modules.geo_series.content.guides_index import render_index_html

    html = render_index_html(
        [
            {
                "category_path": "Sporting Goods > A > Portable Showers",
                "clusters": [
                    {
                        "title": "buyer guide",
                        "articles": [
                            {"title": "t1", "url": "https://x/1/"},
                            {"title": "t2", "url": "https://x/2/"},
                        ],
                    }
                ],
            }
        ]
    )
    assert '<details class="geo-hub-leaf">' in html
    assert "<summary>" in html
    assert '<span class="geo-hub-leaf-n">2</span>' in html
    # 默认收起(没有 open 属性)——这正是"不会越来越长"的关键
    assert "<details class=\"geo-hub-leaf\" open>" not in html
    # 搜索必须能把折叠的分组自动打开,否则搜了等于搜不到
    assert "leaf.open=true" in html


# ===================================================================
# 双向内链 — 新产品补链接（三步→一步）+ 产品页反向链接
# ===================================================================


def test_product_block_is_driven_by_the_cluster_not_the_frozen_copy() -> None:
    """新产品进老簇后,重推一次就该出现在已发布文章里——
    不重新生成、不重新审核、不动已批准的正文。"""
    from types import SimpleNamespace

    from backend.app.modules.content_core.publish_html import render_article_html

    item = SimpleNamespace(
        body_json={"sections": [{"heading": "H", "body": "B"}]},
        # 生成时 AI 只写死了老产品
        source_product_ids_json=["old-product"],
    )
    html = render_article_html(
        item,
        product_links={
            "old-product": "https://site/product/old/",
            "new-product": "https://site/product/new/",
        },
        product_labels={"old-product": "Old Shower", "new-product": "New Shower"},
        cluster_product_ids=["old-product", "new-product"],
        sibling_links=[],
    )
    assert "https://site/product/new/" in html
    assert "New Shower" in html
    # 正文引用的产品排在前面(文章讲的就是它)
    assert html.index("Old Shower") < html.index("New Shower")
    assert "The products in this guide" in html  # 复数


def test_product_block_dedupes_when_cluster_and_copy_use_different_ids() -> None:
    """簇存行 id、文案引用 product_key,同一个产品两种标识——只能出现一次。"""
    from types import SimpleNamespace

    from backend.app.modules.content_core.publish_html import render_article_html

    item = SimpleNamespace(
        body_json={"sections": []}, source_product_ids_json=["the-product-key"]
    )
    url = "https://site/product/x/"
    html = render_article_html(
        item,
        product_links={"the-product-key": url, "the-row-id": url},
        product_labels={"the-product-key": "Shower", "the-row-id": "Shower"},
        cluster_product_ids=["the-row-id"],
        sibling_links=[],
    )
    assert html.count(url) == 1
    assert "The product in this guide" in html  # 单数


def test_related_guides_ranks_hub_first_and_caps_the_list() -> None:
    from backend.app.modules.geo_series.content import related_guides as rg

    assert rg._ITEM_TYPE_ORDER["hub"] == 0
    assert rg.MAX_GUIDES_ON_PRODUCT == 5
    src = inspect.getsource(rg.published_guides_for_product)
    # 只挂已批准且真的上线的文章
    assert 'review_status == "approved"' in src
    assert "published_url.is_not(None)" in src
    # 行 id 与 product_key 两种标识都要认
    assert "product_key" in src


def test_product_description_gets_a_learn_more_block_that_cannot_break_upload() -> None:
    from backend.app.modules.p_series.upload import assemble as pa

    html = pa._append_related_guides_section(
        "<div class='kp'><section>body</section></div>",
        [("How it works", "https://site/how-it-works/")],
    )
    assert "Learn more" in html
    assert "https://site/how-it-works/" in html
    # 追加在描述最底部,不跟买家的下单动线抢位置
    assert html.index("body") < html.index("Learn more")
    assert html.rstrip().endswith("</div>")
    # 没有指南时绝不留空区块
    assert pa._append_related_guides_section("<div>x</div>", []) == "<div>x</div>"

    # 上架路径必须走 safely 包装——GEO 侧出问题不许带崩上架
    src = inspect.getsource(pa.assemble_upload_package)
    assert "published_guides_for_product_safely" in src


# ===================================================================
# 轨道2 — 产品页反链（独立工作流 barongGEObacklink001）
# ===================================================================


def test_backlink_never_links_the_guides_hub() -> None:
    """死命令(用户 2026-07-29):只挂对应类目的具体指南文章,
    绝不挂 /guides/ 主页——把买家丢进全站索引等于浪费这次点击。"""
    from backend.app.modules.geo_series.content.backlink import (
        article_guides_only,
        build_guides_block,
    )

    guides = [
        ("Buying Guide", "https://barongyekhna.com/portable-camping-shower-guide/"),
        ("All guides", "https://barongyekhna.com/guides/"),
        ("Hub no slash", "https://barongyekhna.com/guides"),
        ("Home", "https://barongyekhna.com/"),
    ]
    kept = article_guides_only(guides)
    assert [t for t, _ in kept] == ["Buying Guide"]

    block = build_guides_block(guides)
    assert "/guides/" not in block
    assert "portable-camping-shower-guide" in block

    # 全是主页链接 → 干脆不出区块,而不是出一个空盒子
    assert build_guides_block([("All", "https://barongyekhna.com/guides/")]) == ""


def test_backlink_block_is_idempotent() -> None:
    """读-改-写线上 HTML 的唯一安全前提:标记块「有则替换、无则追加」。"""
    from backend.app.modules.geo_series.content.backlink import (
        apply_guides_block,
        build_guides_block,
    )

    block = build_guides_block([("How it works", "https://site/how/")])
    desc = "<div class='kp'><section>body</section></div>"

    once = apply_guides_block(desc, block)
    twice = apply_guides_block(once, block)
    thrice = apply_guides_block(twice, block)
    assert once == twice == thrice
    assert once.count("kp-guides") == 1

    # 换成新的一批指南 → 替换而不是再加一块
    newer = build_guides_block([("Types compared", "https://site/types/")])
    swapped = apply_guides_block(once, newer)
    assert swapped.count("kp-guides") == 1
    assert "https://site/how/" not in swapped
    assert "https://site/types/" in swapped

    # 空区块 = 清掉陈旧的块
    assert "kp-guides" not in apply_guides_block(once, "")


def test_p_upload_and_backlink_emit_the_same_block() -> None:
    """两个写入方必须产出逐字相同的区块,否则每次跑都会互相覆盖。"""
    from backend.app.modules.geo_series.content.backlink import build_guides_block
    from backend.app.modules.p_series.upload import assemble as pa

    guides = [("How it works", "https://site/how/")]
    from_p = pa._append_related_guides_section("<div></div>", guides)
    assert build_guides_block(guides) in from_p


def test_backlink_workflow_is_brand_new_and_writes_only_description() -> None:
    import json
    from pathlib import Path

    wf = json.loads(
        Path(
            "backend/app/modules/geo_series/n8n/geo_backlink_workflow.json"
        ).read_text(encoding="utf-8")
    )
    assert wf["id"] == "barongGEObacklink001"
    names = {n["name"] for n in wf["nodes"]}
    assert set(wf["connections"]) <= names

    code = next(
        n["parameters"]["jsCode"] for n in wf["nodes"] if n["name"] == "拼描述"
    )
    # 只回写 description;绝不出现价格/库存/图片字段
    assert "wp_body: { description: next }" in code
    for forbidden in ("regular_price", "sale_price", "stock", "images", "categories"):
        assert forbidden not in code
    # Code 节点必须逐条 map(GEO 发布流踩过 $input.first() 压平)
    split = next(
        n["parameters"]["jsCode"] for n in wf["nodes"] if n["name"] == "拆产品"
    )
    assert "targets.map" in split
    # 契约版本硬断言,而且**从契约导入**不是写死一份
    from backend.app.modules.geo_series.contract.backlink_package import (
        GEO_BACKLINK_PACKAGE_VERSION,
    )

    assert GEO_BACKLINK_PACKAGE_VERSION in split
    assert "geo-backlink-package-v2" == GEO_BACKLINK_PACKAGE_VERSION


def test_backlink_queue_mirrors_serial_semantics() -> None:
    """反链队列同样共用 `services/n8n_dispatch.py`。见上一条的说明。"""
    from backend.app.modules.geo_series.content import backlink_jobs as bj
    from backend.app.services import n8n_dispatch

    assert bj.IN_FLIGHT_TIMEOUT_MINUTES == 15
    assert bj.N8N_WEBHOOK_ENV == "N8N_GEO_BACKLINK_WEBHOOK"
    assert isinstance(bj._QUEUE, n8n_dispatch.QueueSpec)
    assert bj._QUEUE.model is bj.GeoBacklinkJob
    assert "未回传" in bj._QUEUE.stale_error
    payload = bj._QUEUE.build_payload(
        SimpleNamespace(job_id="j2", channel="wp", token="t2"), "https://base.test"
    )
    assert "/geo/backlinks/j2/package?token=t2" in payload["package_url"]
    assert payload["callback_url"].endswith("/geo/backlinks/j2/result")
    # 终态幂等（模块自己的逻辑，刻意没有合并）
    assert 'if job.status in {"success", "failed"}' in inspect.getsource(bj.record_result)


def test_backlink_machine_endpoints_are_token_authenticated() -> None:
    from backend.app.modules.geo_series import machine_router

    paths = {r.path for r in machine_router.router.routes}
    assert "/geo/backlinks/{job_id}/package" in paths
    assert "/geo/backlinks/{job_id}/result" in paths
    src = inspect.getsource(machine_router)
    assert "GeoBacklinkJob.token == token" in src


# ===================================================================
# 死命令(2026-07-29): 指南必须落在谷歌类目里，绝不允许无类目上线
# ===================================================================


def test_publish_gate_blocks_a_cluster_without_a_google_category() -> None:
    from types import SimpleNamespace

    from backend.app.modules.geo_series.content.publish_gate import category_blockers

    blockers = category_blockers(None, cluster=SimpleNamespace(google_category_id=""))
    assert blockers and "类目" in blockers[0]

    blockers = category_blockers(None, cluster=SimpleNamespace(google_category_id=None))
    assert blockers


def test_ensure_cluster_category_raises_instead_of_publishing_uncategorised() -> None:
    """以前失败就返回 None、发布方省略 categories 字段 → 文章掉在全站结构之外。
    现在任何失败都必须抛,由端点转 409 整单拒发。"""
    from types import SimpleNamespace

    from backend.app.modules.geo_series.content.wp_categories import (
        GeoCategoryError,
        ensure_cluster_category,
    )

    with pytest.raises(GeoCategoryError):
        ensure_cluster_category(None, cluster=SimpleNamespace(google_category_id=""))

    src = inspect.getsource(ensure_cluster_category)
    assert "return None" not in src
    assert src.count("raise GeoCategoryError") >= 4


def test_package_endpoint_409s_when_the_category_cannot_be_created() -> None:
    from backend.app.modules.geo_series import machine_router

    src = inspect.getsource(machine_router)
    assert "except GeoCategoryError as exc:" in src
    assert "status_code=409" in src


def test_publish_workflow_refuses_a_package_without_a_category() -> None:
    """最后一道兜底:控制台门禁之外,n8n 也必须拒发无分类的包。"""
    code = _geo_node("拆文章")["parameters"]["jsCode"]
    assert "拒绝发布：发布包没有带分类 id" in code
    assert "Number.isInteger(categoryId)" in code


def test_guides_hub_keeps_text_off_the_card_edges() -> None:
    """用户反馈:文字完全贴着白色背景两边,读起来很挤。"""
    from backend.app.modules.geo_series.content.guides_index import render_index_html

    html = render_index_html(
        [
            {
                "category_path": "Sporting Goods > A > Portable Showers",
                "clusters": [
                    {"title": "c", "articles": [{"title": "t", "url": "https://x/1/"}]}
                ],
            }
        ]
    )
    assert "padding:clamp(" in html
    assert "box-sizing:border-box" in html


# ===================================================================
# 指南不进 /posts 博客归档（瘦插件 barong-geo-archive + 控制台遥控名单）
# ===================================================================


def test_archive_plugin_filters_only_the_blog_and_feeds() -> None:
    """本地 docker WP 实测过的行为,锁住:归档/RSS 排除,
    分类归档、站内搜索、单篇、后台一律不受影响。"""
    from pathlib import Path

    php = Path(
        "backend/app/modules/geo_series/wordpress/plugins/barong-geo-archive.php"
    ).read_text(encoding="utf-8")
    # 只动主查询,且只在博客归档/订阅
    assert "is_main_query()" in php
    assert "$query->is_home()" in php and "$query->is_feed()" in php
    assert "is_admin()" in php
    assert "category__not_in" in php
    # 分类归档/搜索/单篇不能出现在过滤条件里
    assert "is_search" not in php
    assert "is_category" not in php
    assert "is_single" not in php
    # 名单由控制台遥控,插件里不许有硬编码 id
    assert "show_in_rest" in php
    assert "barong_geo_category_ids" in php


def test_archive_plugin_sanitiser_drops_rather_than_coerces() -> None:
    """本地实测逮到的 bug: absint('-5') == 5,会误排除一个真实类目。"""
    from pathlib import Path

    php = Path(
        "backend/app/modules/geo_series/wordpress/plugins/barong-geo-archive.php"
    ).read_text(encoding="utf-8")
    assert "absint( trim( $part ) )" not in php
    assert "! preg_match( '/^[0-9]{1,10}$/', $part )" in php


def test_console_syncs_the_exclusion_list_and_never_blocks_publishing() -> None:
    from backend.app.modules.geo_series.content import wp_categories as wc

    src = inspect.getsource(wc.sync_geo_category_exclusions)
    # 名单来自类目缓存表,不是硬编码
    assert "GeoWpCategoryMap.wp_term_id" in src
    # 出网前必须先释放事务(idle-in-transaction 死规矩)
    assert src.index("db.commit()") < src.index("_resolve_credentials")
    # 发布链路上必须是 fail-open 的那个包装
    from backend.app.modules.geo_series import machine_router

    assert "sync_geo_category_exclusions_safely" in inspect.getsource(machine_router)


# ===================================================================
# 里程碑4 — 阵地监测
# ===================================================================


def test_terrain_reads_a_soft_page_as_attackable() -> None:
    """2026-07-29 实测的真实结果:Amazon/Facebook/Reddit/YouTube/eBay 占前五,
    一个权威榜单都没有 —— 这种阵地必须被判为可攻。"""
    from backend.app.modules.geo_series.monitor.terrain import summarize

    real = [
        {"position": 1, "url": "https://www.amazon.com/dp/B0D8SXJK"},
        {"position": 2, "url": "https://www.facebook.com/groups/1399025047071176/posts/1"},
        {"position": 3, "url": "https://www.reddit.com/r/camping/comments/1la22ch/x"},
        {"position": 4, "url": "https://www.youtube.com/watch?v=qMveX8COYtM"},
        {"position": 5, "url": "https://www.ebay.com/itm/406845861913"},
    ]
    v = summarize(real)
    assert v["terrain"] == "soft"
    assert v["attackability"] >= 70
    assert v["our_position"] is None


def test_terrain_reads_an_authority_page_as_hard() -> None:
    from backend.app.modules.geo_series.monitor.terrain import summarize

    hard = [
        {"position": 1, "url": "https://www.outdoorgearlab.com/topics/camping/best-camp-shower"},
        {"position": 2, "url": "https://www.rei.com/learn/expert-advice/showers.html"},
        {"position": 3, "url": "https://www.switchbacktravel.com/best-camping-showers"},
        {"position": 4, "url": "https://www.cleverhiker.com/best-camp-showers/"},
    ]
    v = summarize(hard)
    assert v["terrain"] == "hard"
    assert v["attackability"] < 40


def test_terrain_finds_our_own_position() -> None:
    from backend.app.modules.geo_series.monitor.terrain import summarize

    v = summarize(
        [
            {"position": 1, "url": "https://www.reddit.com/r/camping/x"},
            {"position": 2, "url": "https://barongyekhna.com/portable-camping-shower-guide/"},
        ]
    )
    assert v["our_position"] == 2
    assert v["holder_counts"].get("ours") == 1


def test_registrable_domain_handles_subdomains_and_cctlds() -> None:
    from backend.app.modules.geo_series.monitor.terrain import registrable_domain

    assert registrable_domain("https://www.amazon.com/x") == "amazon.com"
    assert registrable_domain("https://old.reddit.com/r/x") == "reddit.com"
    assert registrable_domain("https://www.amazon.co.uk/x") == "amazon.co.uk"
    assert registrable_domain("not a url") == ""


def test_monitor_consumes_quota_before_calling_and_refunds_on_failure() -> None:
    """烧钱铁律:新出网付费调用当天接台账;失败要退还,否则额度被白吃掉。"""
    from backend.app.modules.geo_series.monitor import service

    # 计量与事务纪律现在住在共享执行核心里(run_sweep 与候选探测都走它)
    src = inspect.getsource(service.sweep_questions)
    assert "PROVIDER_GEO_SERPER_MONITOR" in src
    # 先扣额度,再发请求
    assert src.index("try_consume(") < src.index("fetch_first_page(")
    # 请求失败要退还
    assert "refund(db, PROVIDER_GEO_SERPER_MONITOR" in src
    # 出网前必须释放事务(idle-in-transaction 死规矩)
    assert src.index("db.commit()") < src.index("fetch_first_page(")
    # 密钥解析也慢,必须在事务释放之后、且用独立短会话(2026-07-29 实测被 8s 掐断)
    assert src.index("db.commit()") < src.index("_serper_key(key_session")
    # 单条问句失败不能毁掉整轮
    assert "continue" in src


def test_monitor_bucket_is_metered_and_capped() -> None:
    from r_system_v2.ra.quota_ledger import (
        DEFAULT_DAILY_BUDGETS,
        PROVIDER_GEO_SERPER_MONITOR,
        provider_label,
    )

    assert DEFAULT_DAILY_BUDGETS[PROVIDER_GEO_SERPER_MONITOR] > 0
    assert provider_label(PROVIDER_GEO_SERPER_MONITOR) != PROVIDER_GEO_SERPER_MONITOR


def test_monitor_seeding_reuses_real_buyer_questions_and_is_idempotent() -> None:
    from backend.app.modules.geo_series.monitor import seed

    src = inspect.getsource(seed.seed_from_cluster)
    # 复用 M2 采到的真实问句,不让用户重新输
    assert "picked_questions_json" in src
    # 重复导入不许产生重复行
    assert "existing" in src and "skipped" in src


def test_topic_probe_is_cached_and_capped() -> None:
    """选题界面上的按钮:一次点击不能烧一片额度。
    一周内查过的候选不重查,单次最多探测 MAX_PROBE_PER_CALL 条。"""
    from backend.app.modules.geo_series.monitor import probe

    assert probe.MAX_PROBE_PER_CALL <= 50
    assert probe.CACHE_DAYS >= 1
    src = inspect.getsource(probe.probe_candidates)
    assert "fresh_ids" in src and "cached" in src
    assert "len(to_check) < max(0, limit)" in src
    # 探测出来的候选不加入常规监测名单
    assert "is_active=0" in src
    # 共享执行核心,不另起一套计量/事务逻辑
    assert "sweep_questions(" in src


def test_topic_candidates_carry_terrain_for_pick_time_decisions() -> None:
    """首轮监测的教训:四条选题全是 best X(守门人榜单主场),
    选的时候看不见阵地。现在候选自带阵地读数。"""
    from backend.app.modules.geo_series import router

    src = inspect.getsource(router.geo_topic_candidates)
    assert "terrain_by_question" in src
    assert 'candidate["terrain"]' in src
    paths = {r.path for r in router.router.routes}
    assert "/geo/clusters/{cluster_id}/topic-terrain" in paths


def test_terrain_lookup_matches_questions_loosely() -> None:
    """问号、大小写、空格不该让候选和监测记录对不上。"""
    from backend.app.modules.geo_series.monitor.probe import normalize_question

    a = normalize_question("How Long Do Portable Showers Last?")
    b = normalize_question("  how long do portable showers last  ")
    assert a == b


def test_question_answer_is_the_one_repeatable_item_type() -> None:
    """五个单例类型写满后簇就"封顶"了,新问句无处安放——而 M4 证明能赢的
    正是具体问句。单题深答必须可重复,且只在真有待写问句时才算工作量。"""
    from backend.app.modules.geo_series.content.constants import (
        ITEM_TYPES,
        REPEATABLE_ITEM_TYPES,
    )
    from backend.app.modules.geo_series.content import orchestrator as orch

    assert "question_answer" in ITEM_TYPES
    assert "question_answer" in REPEATABLE_ITEM_TYPES
    # 枢纽这类必须仍是单例,否则一个簇会长出两个 hub 自我竞争
    for singleton in ("hub", "how_it_works", "comparison", "scenario", "qa"):
        assert singleton not in REPEATABLE_ITEM_TYPES

    src = inspect.getsource(orch.GeoContentOrchestrator.generate_cluster)
    # 可重复类型不进 skip 名单
    assert "i.item_type not in REPEATABLE_ITEM_TYPES" in src
    # 但"只剩可重复类型"且没有待写问句时,仍要判定为无事可做
    assert "set(unwritten_types) <= REPEATABLE_ITEM_TYPES" in src


def test_prompt_defines_one_article_per_question() -> None:
    from backend.app.modules.geo_series.content.prompt_skills import (
        geo_content_instruction,
    )

    prompt = geo_content_instruction()
    assert "question_answer" in prompt
    assert "answering exactly ONE required question" in prompt


def test_server_computes_which_types_to_write_not_the_model() -> None:
    """2026-07-29 实测:列出全部类型再让模型减去 skip_item_types,
    当只剩一种时模型直接跑飞——自造 item_type 和响应形状。减法必须服务端做完。"""
    from backend.app.modules.geo_series.content import orchestrator as orch
    from backend.app.modules.geo_series.content.prompt_skills import (
        geo_content_instruction,
    )

    src = inspect.getsource(orch.GeoContentOrchestrator.generate_cluster)
    assert '"produce_item_types"' in src
    assert 't not in skip_item_types and t != "product_spotlight"' in src

    prompt = geo_content_instruction()
    assert "`produce_item_types` lists EXACTLY" in prompt
    assert "never invent an item_type" in prompt
    # 一条待写问句一篇深答
    assert "ONE PER pending required question" in prompt


def test_prompt_forbids_spec_recitation_as_an_answer() -> None:
    """用户 2026-07-29 指出最严重的问题:「值不值」被写成罗列产品参数。
    防编造的护栏挡住了讲道理,系统只剩规格表可用。写作家规必须明确禁止。"""
    from backend.app.modules.geo_series.content.prompt_skills import (
        geo_content_instruction,
    )

    prompt = geo_content_instruction()
    assert "ANSWER THE QUESTION — DO NOT DESCRIBE THE PRODUCT" in prompt
    assert "can now make it up" in prompt
    # 判断题必须给决策结构,而且"什么情况下不值得"这半边是强制的
    assert "JUDGEMENT QUESTIONS" in prompt
    assert "the conditions under which it is NOT worth it" in prompt
    assert "mandatory" in prompt
    # 条件判断不等于编造事实——这条要写进去,否则模型会因为怕违规而不敢下判断
    assert "it is a conditional, not a claim of fact" in prompt


def test_critique_flags_product_description_wearing_a_question_hat() -> None:
    """这类毛病语法全对、审查全清,正则和硬门禁抓不到,只能靠 LLM 评审员。"""
    from backend.app.modules.content_core.analysis import analysis_instruction

    prompt = analysis_instruction()
    assert "回答问句" in prompt and "介绍产品" in prompt
    assert "拿不定主意" in prompt or "拿定主意" in prompt
    assert "什么情况下不值得" in prompt


# ===================================================================
# 事实充分性:宁可不写,也不写正确的废话
# ===================================================================


def test_fact_gate_blocks_emptiness_but_not_low_density() -> None:
    """实测推翻了第一版设计:捏捏 5 个产品只有 0-3 个数字,却写出了具体、诚实、
    能区分五款的内容——因为事实密度的要求是分品类的(参数驱动 vs 偏好驱动)。
    所以只拦"根本没被描述过",低密度只警告。"""
    from backend.app.modules.content_core.fact_sufficiency import (
        fact_blockers,
        fact_warnings,
        product_fact_report,
    )

    shower = product_fact_report(
        {"sku": "PSPE-001", "specs": [1] * 3, "selling_points": [1] * 14},
        {str(n) for n in range(22)},
    )
    squishy = [
        product_fact_report(
            {"sku": f"ET-00{i}", "specs": [1] * 3, "selling_points": [1] * 5},
            {"1", "2", "3"} if i > 1 else set(),
        )
        for i in range(1, 6)
    ]
    # 两者都放行——低密度不是拒绝的理由
    assert fact_blockers([shower]) == []
    assert fact_blockers(squishy) == []
    # 但低密度要如实告知
    assert fact_warnings(squishy)
    assert fact_warnings([shower]) == []

    # 真正的空:没数字、没规格、没卖点
    blank = product_fact_report({"sku": "X-001", "specs": [], "selling_points": []}, set())
    blockers = fact_blockers([blank])
    assert blockers and "X-001" in blockers[0]
    assert "去 K" in blockers[0]

    # 部分为空:点名,让人补上或摘掉
    mixed = fact_blockers([shower, blank])
    assert mixed and "X-001" in mixed[0]

    assert fact_blockers([]) == [
        "这个话题簇下面没有产品——先从 P 上架一个产品把簇挂起来。"
    ]


def test_fact_gate_runs_before_the_ai_call() -> None:
    """拦在调用之前:既省钱,也避免把空洞内容写进库再靠人去发现。"""
    from backend.app.modules.geo_series.content import orchestrator as orch

    src = inspect.getsource(orch.GeoContentOrchestrator.generate_cluster)
    assert "GEO_INSUFFICIENT_FACTS" in src
    assert src.index("fact_blockers(") < src.index("self._call_ai(")


def test_not_worth_it_section_may_not_end_with_a_pitch() -> None:
    """一段专门讲「别买」的文字,以推销收尾就等于自毁可信度。"""
    from backend.app.modules.geo_series.content.prompt_skills import (
        geo_content_instruction,
    )

    prompt = geo_content_instruction()
    assert "NO sales language" in prompt
    assert "must NOT end" in prompt


def test_revise_prompt_carries_the_same_writing_rules() -> None:
    """只改主提示词不够:重写走的是另一套提示词,不同步的话重写出来还是老毛病。"""
    from backend.app.modules.geo_series.content.prompt_skills import (
        geo_revise_instruction,
    )

    p = geo_revise_instruction()
    assert "回答问句,不要介绍产品" in p
    assert "什么情况下不值得——这半边是强制的" in p
    assert "不许出现推销语言" in p
    assert "条件判断不是事实主张" in p
    # 句句写全称是原稿实测出来的毛病
    assert "别每句话都写产品全称" in p


def test_published_slug_is_locked_against_rewrites() -> None:
    """2026-07-29 实地踩到:重写时模型改了 seo.url_slug,发布流照着改了 WordPress
    固定链接,线上网址当场失效。内容可以重写,地址不行。两道锁。"""
    from types import SimpleNamespace

    from backend.app.modules.geo_series.content import assemble as asm
    from backend.app.modules.geo_series.content import orchestrator as orch

    # 一道锁:控制台侧,已发布的文章重写时不许改 slug
    src = inspect.getsource(orch.GeoContentOrchestrator.revise_item)
    assert "if item.wp_post_id:" in src
    assert 'new_seo["url_slug"] = old_slug' in src

    # 二道锁:发布包对已发布的 post 干脆不下发 slug
    src2 = inspect.getsource(asm.assemble_guide_package)
    assert "None\n                        if item.wp_post_id" in src2

    # n8n 侧:没有 slug 时不许把 slug 写成空字符串
    code = _geo_node("拆文章")["parameters"]["jsCode"]
    assert "if (seo.url_slug) body.slug = seo.url_slug;" in code


# ===================================================================
# 算术:护栏不该惩罚精确
# ===================================================================


def test_guard_used_to_punish_precision() -> None:
    """实地踩到:「约2分钟」通过(2 命中"2小时充电"),更准的「2.4分钟」被拦——
    含糊的过、精确的死。而 5÷2.11 正是这条问句的答案。"""
    from backend.app.modules.content_core.guards import audit_content_item

    item = {
        "title": "How long does a 5 gallon portable shower last?",
        "sections": [{"heading": "x", "body": "About 2.4 minutes at 2.11 GPM."}],
    }
    # 不声明算式 → 仍然被拦(护栏没有放松)
    bare = audit_content_item(
        item, forbidden_terms=[], evidence_numbers={"2.11"}, context_numbers={"5"}
    )
    assert bare["clean"] is False
    assert any(u["number"] == "2.4" for u in bare["ungrounded_numbers"])

    # 亮出算式 → 放行
    declared = {**item, "derived_numbers": [{"value": "2.4", "from": "5 / 2.11"}]}
    ok = audit_content_item(
        declared, forbidden_terms=[], evidence_numbers={"2.11"}, context_numbers={"5"}
    )
    assert ok["clean"] is True


def test_derivation_must_actually_compute() -> None:
    """依然 fail-closed:算错、操作数没来源、表达式不合法,一律拒。"""
    from backend.app.modules.content_core.guards import verify_derived_numbers

    ev, ctx = {"2.11"}, {"5"}

    ok, bad = verify_derived_numbers(
        [{"value": "2.4", "from": "5 / 2.11"}],
        evidence_numbers=ev, context_numbers=ctx,
    )
    assert ok == {"2.4"} and bad == []

    # 算错
    _, bad = verify_derived_numbers(
        [{"value": "9.9", "from": "5 / 2.11"}],
        evidence_numbers=ev, context_numbers=ctx,
    )
    assert bad and "算错了" in bad[0]["reason"]

    # 操作数凭空出现
    _, bad = verify_derived_numbers(
        [{"value": "7", "from": "3 + 4"}],
        evidence_numbers=ev, context_numbers=ctx,
    )
    assert bad and "没有来源" in bad[0]["reason"]

    # 不是算术(防注入)
    for evil in ["__import__('os').system('x')", "open('/etc/passwd')", "5 ** 999999"]:
        _, bad = verify_derived_numbers(
            [{"value": "1", "from": evil}], evidence_numbers=ev, context_numbers=ctx
        )
        assert bad, f"没拦住: {evil}"

    # 除以零
    _, bad = verify_derived_numbers(
        [{"value": "1", "from": "5 / 0"}], evidence_numbers=ev, context_numbers=ctx
    )
    assert bad


def test_bad_derivation_makes_the_item_dirty() -> None:
    from backend.app.modules.content_core.guards import audit_content_item

    audit = audit_content_item(
        {
            "title": "t",
            "sections": [{"heading": "h", "body": "It lasts 9.9 minutes."}],
            "derived_numbers": [{"value": "9.9", "from": "5 / 2.11"}],
        },
        forbidden_terms=[],
        evidence_numbers={"2.11"},
        context_numbers={"5"},
    )
    assert audit["clean"] is False
    assert audit["bad_derivations"]


def test_prompts_require_showing_the_work() -> None:
    from backend.app.modules.geo_series.content.prompt_skills import (
        geo_content_instruction,
        geo_revise_instruction,
    )

    gen = geo_content_instruction()
    assert "ARITHMETIC IS ALLOWED — BUT SHOW YOUR WORK" in gen
    assert "derived_numbers" in gen
    assert "Do NOT round a number into vagueness" in gen
    rev = geo_revise_instruction()
    assert "算术是允许的,但必须亮算式" in rev
    assert "不许为了躲开声明而把数字含糊掉" in rev


# ===================================================================
# P0 共享底座 + 两个共用件的 bug
# ===================================================================


def test_shared_core_never_imports_a_content_module() -> None:
    """依赖方向:共享底座不许反向依赖 geo/seo。抽层时我自己差点写反(wp_sync
    第一版直接 import 了 GeoContentItem),所以钉死它。"""
    from pathlib import Path

    core = Path("backend/app/modules/content_core")
    offenders = []
    for path in core.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue  # 注释里提到文件名不算依赖
            if "geo_series" in stripped or "seo_series" in stripped:
                offenders.append(f"{path.name}: {stripped}")
    assert offenders == [], offenders


def test_index_page_upsert_never_creates_a_duplicate_on_a_blip() -> None:
    """原缺陷:更新失败(任何原因)就新建 → WP 一超时就多出一个重复 /guides/ 页、
    旧页变孤儿。只有真 404 才允许恢复,且恢复前先按 slug 认领。"""
    import inspect

    from backend.app.modules.content_core import wp_pages

    src = inspect.getsource(wp_pages.upsert_page)
    assert 'if result.get("status") != 404:' in src
    assert "raise WpPageError" in src
    # 认领必须发生在创建之前
    assert src.index("_find_by_slug(") < src.index("_post(_PAGES_PATH)")

    # guides_index 必须走它，不再自己拼创建逻辑
    from backend.app.modules.geo_series.content import guides_index

    gsrc = inspect.getsource(guides_index)
    assert "upsert_page(" in gsrc
    assert "recreating" not in gsrc


def test_related_guides_requires_a_real_publish_status() -> None:
    """published_url 非空 ≠ 线上可见。n8n 首次建文落 draft,URL 那时就写库了。"""
    import inspect

    from backend.app.modules.geo_series.content import related_guides

    src = inspect.getsource(related_guides.published_guides_for_product)
    assert 'GeoContentItem.wp_status == "publish"' in src
    # 本函数被 B2B 逐产品循环调用,绝不能自己出网
    assert "wp_bridge" not in src and "httpx" not in src


def test_live_state_refresh_is_batched_and_fail_open() -> None:
    import inspect

    from backend.app.modules.content_core import wp_sync
    from backend.app.modules.geo_series.content import live_state

    # 批量:一次请求查多条,不是逐条
    fetch = inspect.getsource(wp_sync.fetch_post_states)
    assert '"include"' in fetch and "_BATCH" in fetch

    src = inspect.getsource(live_state.refresh_item_live_state)
    # 出网前释放事务
    assert src.index("db.commit()") < src.index("fetch_post_states(")
    # WP 挂了保留旧状态,绝不清空
    assert "if not states:\n        return 0" in src
    # 反链派单前必须先刷新
    from backend.app.modules.geo_series.content import backlink_targets

    assert "refresh_item_live_state_safely" in inspect.getsource(
        backlink_targets.collect_backlink_targets
    )


# ===================================================================
# 类目级选题深挖:把一个话题的问句挖到底
# ===================================================================


def test_mining_seeds_from_the_whole_category_subtree() -> None:
    """用户拍板(2026-07-30):「我要做最完整的产品链,所有产品都卖」。

    这家工厂没有固定品类,F 系列做的就是类目富化——同父类目下的相邻品今天没有、
    明天就会上。所以选题面是**整棵子树**,不是"我们现在卖的那一个叶子"。
    兄弟叶子必须查树:路径字符串里只有祖先,查不到兄弟。

    我一度按"我们只卖淋浴"把便携马桶当跑题挡掉——那是拿静态品类的假设
    去套一个动态扩张的品类。
    """
    from backend.app.modules.geo_series.content.topic_mining import (
        _subtree_categories,
        build_seeds,
    )

    tree = inspect.getsource(_subtree_categories)
    assert "c.parent_id = me.parent_id" in tree  # 兄弟叶子
    assert "c.id = me.parent_id" in tree  # 父级
    assert "fallback" in tree  # 查不到也别炸

    src = inspect.getsource(build_seeds)
    assert "_subtree_categories" in src
    # "&" 必须拆:淋浴帐篷和淋浴器在同一个叶子里
    assert 're.split(r"\\s*&\\s*", name)' in src


def test_paa_is_expanded_a_second_level() -> None:
    """Google 的「大家还在问」是棵树,长尾在第二层往下。只抓第一层就等于没挖。"""
    from backend.app.modules.geo_series.content import topic_mining

    src = inspect.getsource(topic_mining.mine_cluster_questions)
    assert "expansion_pool" in src
    # 只展开 PAA——它是 Google 认定的同意图问句,展开出来还在同一个话题里
    assert 'source_type in ("people_also_ask", "organic_question")' in src
    assert "MAX_EXPANSION_QUERIES" in src


def test_mining_is_metered_and_stops_cleanly_when_out_of_quota() -> None:
    """死规矩(Serper 12 天烧光 5 万次那次换来的):新增出网付费调用当天接台账,
    额度尽了优雅停下并说清楚,绝不打超额请求。"""
    from r_system_v2.ra.quota_ledger import (
        DEFAULT_DAILY_BUDGETS,
        PROVIDER_GEO_SERPER_TOPICS,
    )

    assert DEFAULT_DAILY_BUDGETS[PROVIDER_GEO_SERPER_TOPICS] > 0

    from backend.app.modules.geo_series.content import topic_mining

    src = inspect.getsource(topic_mining.mine_cluster_questions)
    assert "try_consume" in src
    assert "额度用尽" in src
    # 请求失败要退额度,否则一次网络抖动等于白扣一笔
    assert "refund" in src


def test_mining_never_holds_a_transaction_across_the_network() -> None:
    from backend.app.modules.geo_series.content import topic_mining

    src = inspect.getsource(topic_mining.mine_cluster_questions)
    key_at = src.index("_serper_key")
    commit_at = src.index("db.commit()")
    assert commit_at < key_at, "取钥匙也要在事务外(GEO 监测在这一步栽过)"
    inner = inspect.getsource(topic_mining.mine_cluster_questions)
    assert "db.commit()  # 出网前放掉" in inner


def test_mined_questions_are_persisted_because_they_cost_money() -> None:
    """原有候选是实时读出来的、零成本;深挖是花钱换的,不落表等于反复付钱
    买同一批问句。"""
    import backend.app.models as M

    assert hasattr(M, "GeoMinedQuestion")
    cols = {c.name for c in M.GeoMinedQuestion.__table__.columns}
    assert {"cluster_id", "normalized_question", "depth", "score", "seed_query"} <= cols
    # 同一簇同一问句只存一次
    names = {c.name for c in M.GeoMinedQuestion.__table__.constraints}
    assert any("cluster_norm" in str(n) for n in names)


def test_mined_questions_merge_into_the_existing_candidate_list() -> None:
    """挖到的问句要和 K/F 的候选合并成一个列表,按归一化问句去重——
    同一个问句从哪来都只出现一次。"""
    from backend.app.modules.geo_series.content import topic_sourcing

    src = inspect.getsource(topic_sourcing.list_topic_candidates)
    assert "mined_candidates" in src
    assert "_norm(candidate" in src


def test_mined_questions_pass_the_same_quality_gate() -> None:
    """深挖不是降低标准:真问句、品牌安全、不是规格复述,三道门一个不少。"""
    from backend.app.modules.geo_series.content import topic_mining

    src = inspect.getsource(topic_mining._accept)
    assert "is_faq_question_candidate" in src
    assert "is_faq_text_brand_safe" in src
    assert "is_specification_paraphrase_question" in src


def test_off_topic_questions_are_dropped_and_counted() -> None:
    """第二道防线:PAA 会自然漂到相邻品类。
    「best type of portable toilet」和淋浴只共享一个 portable,真淋浴问句共享两个以上。"""
    from backend.app.modules.geo_series.content.topic_mining import (
        _on_topic,
        head_nouns,
    )

    heads = head_nouns(
        [
            "Portable Showers",
            "Privacy Enclosures",
            "Portable Toilets",  # 父级——同类目扩张的下一批品
            "portable camping shower",
        ]
    )
    assert _on_topic("How long does a 5 gallon portable shower last?", heads)
    assert _on_topic("Do I need a privacy enclosure for camping?", heads)
    # 只共享一个中心词也要放行——"共享 2 个词"那版把它误杀过
    assert _on_topic("What is a solar shower?", heads)
    # 同父类目的相邻品要放行——那是下一批产品的选题储备
    assert _on_topic("What is the best type of portable toilet?", heads)
    # 真正漂出去的才挡:完全不同的购买场景
    assert not _on_topic("How do I replace my bathroom faucet cartridge?", heads)

    from backend.app.modules.geo_series.content import topic_mining

    src = inspect.getsource(topic_mining.mine_cluster_questions)
    # 挡掉多少要明说,别让"只挖到 20 个"看起来像挖不动
    assert "off_topic_dropped" in src
    assert "漂到相邻品类" in src


def test_mined_questions_file_themselves_under_the_right_category() -> None:
    """从淋浴簇顺带挖到的马桶问句,属于**马桶那个兄弟叶子**,不属于淋浴簇。

    记在发起簇名下两头都错:现在污染淋浴簇的候选列表,将来马桶簇建起来又拿不到
    ——等于那 18 条白挖了。2026-07-30 用户问"淋浴器和马桶进到几个簇"时查出来的。
    """
    import backend.app.models as M

    cols = {c.name for c in M.GeoMinedQuestion.__table__.columns}
    assert "google_category_id" in cols

    from backend.app.modules.geo_series.content import topic_mining

    subtree = inspect.getsource(topic_mining._subtree_categories)
    assert "is_leaf" in subtree

    # 归档按**问句里的中心词**,不是按种子——PAA 漂移是常态,
    # 从淋浴种子挖出来的马桶问句照样要归到马桶叶子去。
    heads = topic_mining.leaf_head_map(
        [
            ("Portable Showers & Privacy Enclosures", "502994"),
            ("Portable Toilets & Urination Devices", "503009"),
            ("Portable Toilets & Showers", None),  # 父级不带 id
        ]
    )
    assert heads["shower"] == "502994"
    assert heads["enclosure"] == "502994"
    assert heads["toilet"] == "503009"
    assert topic_mining._attribute("How to empty a portable toilet?", heads) == "503009"
    assert (
        topic_mining._attribute("How long does a portable shower last?", heads)
        == "502994"
    )

    take = inspect.getsource(topic_mining.mined_candidates)
    assert "google_category_id ==" in take
    # 没有类目归属的只给发起簇
    assert "google_category_id.is_(None)" in take


# ===================================================================
# 簇归属守卫:保证不同产品进对簇,且簇之间不互相抢词
# ===================================================================


def test_cluster_membership_is_an_exact_category_match_not_a_guess() -> None:
    """"同类目进同簇、不同类目进不同簇"是**结构保证**,不是靠谁记得:
    产品的 google_product_category 与簇的 google_category_id 精确字符串匹配,
    没有 AI、没有模糊匹配、没有人工判断。"""
    from backend.app.modules.geo_series.content import ingest_from_p

    src = inspect.getsource(ingest_from_p.ensure_geo_cluster_for_product)
    assert "google_product_category" in src
    assert "resolve_cluster_for_category" in src
    # 没有类目就不挂簇——绝不瞎猜一个
    assert "has no google category bound" in src


def test_leaf_only_is_deliberately_NOT_enforced() -> None:
    """强制"必须挂叶子"是错的:谷歌树里根本没有「捏捏」这个叶子,
    非叶子的 Executive Toys 恰恰是最准的节点。强制叶子只会逼出错误归类
    (把捏捏塞进 Magnet Toys)。要守的是重叠,不是层级。"""
    from pathlib import Path

    for path in (
        Path("backend/app/modules/geo_series/content/ingest_from_p.py"),
        Path("backend/app/modules/geo_series/content/service.py"),
    ):
        text = path.read_text()
        assert "is_leaf" not in text, f"{path}: 不该按叶子卡产品类目"


def test_ancestor_and_descendant_clusters_are_the_real_hazard() -> None:
    """谷歌类目是树。父类目和子类目各开一簇 = 写同一片话题、抢同一批词。
    精确匹配只认相等,漏的就是这个。"""
    from backend.app.modules.geo_series.content import cluster_guard

    resolve = inspect.getsource(cluster_guard.resolve_cluster_for_category)
    assert '"exact"' in resolve
    assert '"ancestor"' in resolve
    assert '"descendant"' in resolve
    # 祖先优先,而且要挑最近的
    assert resolve.index('"ancestor"') < resolve.index('"descendant"')

    up = inspect.getsource(cluster_guard.category_ancestors)
    down = inspect.getsource(cluster_guard.category_descendants)
    assert "WITH RECURSIVE" in up and "WITH RECURSIVE" in down


def test_a_broader_cluster_absorbs_instead_of_splitting() -> None:
    """已有祖先簇 → 挂上去。再开一个更细的簇就是把同一批词拆成两半自己打自己。
    真要细分,等那个子类目产品够多、由人明确决定拆。"""
    from backend.app.modules.geo_series.content import ingest_from_p

    src = inspect.getsource(ingest_from_p.ensure_geo_cluster_for_product)
    assert 'relation == "ancestor"' in src
    # 挂到祖先簇上之后不能又往下走建新簇
    assert src.index('relation == "ancestor"') < src.index('relation == "descendant"')


def test_building_a_parent_cluster_over_an_existing_child_is_refused() -> None:
    """自动合并会动到已发布内容,自动跳过又让产品无处可去——
    两种都是代码替人做决定。拦住,说清楚,让人判。"""
    from backend.app.modules.geo_series.content import cluster_guard

    src = inspect.getsource(cluster_guard.assert_no_overlapping_cluster)
    assert "ClusterOverlapError" in src
    assert "抢同一批词" in src
    assert "代码不替你选" in src

    # P 自动挂簇只关心后代方向(祖先方向它是吸收,不是拒绝)
    narrow = inspect.getsource(cluster_guard.assert_no_descendant_cluster)
    assert 'relation != "descendant"' in narrow

    # 手工建簇那条路走双向门
    from backend.app.modules.geo_series.content import service

    assert "assert_no_overlapping_cluster" in inspect.getsource(service.create_cluster)


def test_existing_overlaps_are_surfaced_not_left_to_rot() -> None:
    """守卫是后加的,历史数据可能已经重叠。要让它显形,
    而不是等排名被自己拖下去才发现。"""
    from backend.app.modules.geo_series.content import cluster_guard
    from backend.app.modules.geo_series.router import router

    assert "/geo/clusters/overlap-check" in {r.path for r in router.routes}
    assert "父簇和子簇写同一片话题" in inspect.getsource(
        cluster_guard.overlapping_cluster_pairs
    )


def test_manual_cluster_creation_refuses_both_directions() -> None:
    """2026-07-30 实测抓到我自己的漏:原来只拦了「要建父簇、底下已有子簇」。
    反过来「要建子簇、上面已有父簇」照样建得出来——而它一样和父簇抢同一批词。

    自动挂簇(P 上架)对祖先是**吸收**;手工建簇是人明确说"我要一个新簇",
    这时候静默改挂到别的簇上更吓人,该做的是拦住并说清楚。
    """
    from backend.app.modules.geo_series.content import cluster_guard, service

    src = inspect.getsource(cluster_guard.assert_no_overlapping_cluster)
    assert 'relation in ("none", "exact")' in src
    assert "**底下**" in src  # 后代方向
    assert "**上面**" in src  # 祖先方向
    # 两个方向的建议不一样,不能糊成一句
    assert "产品专属文章" in src

    assert "assert_no_overlapping_cluster" in inspect.getsource(service.create_cluster)


def test_static_cluster_routes_are_declared_before_the_uuid_route() -> None:
    """FastAPI 按声明顺序匹配。/clusters/overlap-check 排在 /clusters/{id} 后面
    会被当成 UUID 吃掉,返回 422(2026-07-30 线上实测踩到)。"""
    from backend.app.modules.geo_series.router import router

    paths = [r.path for r in router.routes]
    assert paths.index("/geo/clusters/overlap-check") < paths.index(
        "/geo/clusters/{cluster_id}"
    )


# ===================================================================
# 定界块设施（已下沉 content_core/html_blocks）
# ===================================================================


@pytest.mark.parametrize("block_class", ["kp-guides", "kp-factory"])
def test_block_apply_is_idempotent_for_any_class(block_class: str) -> None:
    """跑一百遍留下的永远是恰好一个块。这是"读改写线上 HTML"能安全重复的唯一理由。"""
    from backend.app.modules.content_core.html_blocks import (
        apply_block,
        build_link_block,
    )

    block = build_link_block(
        block_class=block_class, heading="H", links=[("T", "https://x/a/")]
    )
    html = '<div class="kp-desc"><p>body</p></div>'
    once = apply_block(html, block, block_class=block_class)
    thrice = apply_block(
        apply_block(once, block, block_class=block_class),
        block,
        block_class=block_class,
    )
    assert once == thrice
    assert thrice.count(block_class) == 1
    # 空块 = 摘掉,不是留空壳
    assert block_class not in apply_block(thrice, "", block_class=block_class)


def test_two_blocks_coexist_without_swallowing_each_other() -> None:
    """产品页上要同时挂指南块和工艺块。先插的绝不能吞掉后插的——
    这靠的是"块内没有 </div>",所以第二次 rfind 找到的仍是外层 .kp-desc 的收尾。"""
    from backend.app.modules.content_core.html_blocks import (
        apply_blocks,
        build_link_block,
    )

    guides = build_link_block(
        block_class="kp-guides", heading="Learn more", links=[("G", "https://x/g/")]
    )
    factory = build_link_block(
        block_class="kp-factory", heading="How we make it", links=[("F", "https://x/f/")]
    )
    out = apply_blocks(
        '<div class="kp-desc"><p>body</p></div>',
        [("kp-guides", guides), ("kp-factory", factory)],
    )
    assert out.count("kp-guides") == 1
    assert out.count("kp-factory") == 1
    # factory 不能落在 guides 的 <section>…</section> 内部
    g_start = out.index("kp-guides")
    g_end = out.index("</section>", g_start)
    assert out.index("kp-factory") > g_end


def test_block_shape_invariants_are_enforced_not_documented() -> None:
    """这两条破了,线上页面会被切坏而且**再也替换不掉**——所以是抛异常不是写注释。"""
    from backend.app.modules.content_core.html_blocks import (
        BlockError,
        assert_block_shape,
    )

    # </div> 会抢走 rfind 的定位,后插的块被塞进这个块内部
    with pytest.raises(BlockError):
        assert_block_shape('<section class="kp-box kp-x"><div>a</div></section>')
    # 嵌套 <section> 会让非贪婪正则在内层截断
    with pytest.raises(BlockError):
        assert_block_shape(
            '<section class="kp-box kp-x"><section>inner</section></section>'
        )


def test_wrong_class_raises_instead_of_appending_forever() -> None:
    """用 A 的 class 建的块拿去替换 B,会走"无则追加"——每刷新一次多一块,线上失控。"""
    from backend.app.modules.content_core.html_blocks import BlockError, apply_block, build_link_block

    block = build_link_block(
        block_class="kp-guides", heading="H", links=[("T", "https://x/")]
    )
    with pytest.raises(BlockError):
        apply_block("<div></div>", block, block_class="kp-factory")


def test_block_class_is_whitelisted_before_entering_a_regex() -> None:
    from backend.app.modules.content_core.html_blocks import BlockError, block_pattern

    for bad in ("kp guides", "kp.*", "KP", "", "kp/x"):
        with pytest.raises(BlockError):
            block_pattern(bad)


def test_replacement_never_interprets_backslashes_in_urls() -> None:
    """替换值直接传字符串的话,URL 里的 \\1 会被当反向引用解释。用 lambda 挡掉。"""
    from backend.app.modules.content_core.html_blocks import apply_block, build_link_block

    weird = build_link_block(
        block_class="kp-guides", heading="H", links=[("T", r"https://x/a\1b/")]
    )
    out = apply_block(
        '<div class="kp-desc"></div>', weird, block_class="kp-guides"
    )
    out = apply_block(out, weird, block_class="kp-guides")  # 走替换分支
    assert r"a\1b" in out


def test_js_regex_comes_from_the_same_source_as_python() -> None:
    """替换逻辑原本 Python 和 n8n 的 JS 各写一遍,要手工同步。
    让 JS 那份由 Python 生成之后,两边只有一个真相源。"""
    from backend.app.modules.content_core.html_blocks import js_block_regex_source

    src = js_block_regex_source("kp-guides")
    assert src.startswith("/<section class=")
    assert "kp-guides" in src
    assert src.endswith("/i")


# ===================================================================
# 契约 v2：一条 target 带多个块 + 指纹
# ===================================================================


def test_one_product_gets_exactly_one_target_with_all_its_blocks() -> None:
    """n8n 是「GET 全部 → 合并 → PUT 全部」。同一个产品拆成两条 target 会读到
    **同一份旧 description**，第二条 PUT 直接抹掉第一条——这就是 v1 不能沿用的原因。"""
    from backend.app.modules.geo_series.content import backlink_targets

    src = inspect.getsource(backlink_targets.collect_backlink_targets)
    assert '"blocks": [' in src
    # 一次循环只 append 一次
    assert src.count("targets.append(") == 1
    assert "第二条 PUT 抹掉第一条" in src


def test_stale_block_is_finally_removable() -> None:
    """契约里 block html 为空**明确定义为"摘掉块"**，但旧代码在收集目标时对空块
    直接 continue，导致这条语义永远走不到——指南全下线后产品页上的死链摘不掉。
    2026-07-31 查出，这是本轮优先级最高的一处 bug 修复。"""
    from backend.app.modules.geo_series.content import backlink_targets

    src = inspect.getsource(backlink_targets.collect_backlink_targets)
    # 两块都空 **但有历史指纹** → 照样派单
    assert "if not guides and not factory and not previous:" in src
    assert "死链永远摘不掉" in src or "摘不掉" in src
    # 旧的无条件跳过必须消失
    assert "还没有已发布的指南可挂" not in src


def test_fingerprint_short_circuits_and_is_order_stable() -> None:
    """指纹相同就不派单（零 WP 调用算过期数）。顺序不稳定 = 每次都判过期。"""
    from backend.app.modules.geo_series.content.backlink_targets import _fingerprint

    a = _fingerprint([("kp-guides", "<g/>"), ("kp-factory", "<f/>")])
    b = _fingerprint([("kp-factory", "<f/>"), ("kp-guides", "<g/>")])
    assert a == b, "块的先后不该改变指纹"
    assert a != _fingerprint([("kp-guides", "<g2/>"), ("kp-factory", "<f/>")])

    src = inspect.getsource(
        __import__(
            "backend.app.modules.geo_series.content.backlink_targets",
            fromlist=["collect_backlink_targets"],
        ).collect_backlink_targets
    )
    assert "previous == fingerprint" in src
    assert "已是最新" in src
    # 产出顺序稳定,否则包的字节每次都变
    assert "targets.sort(" in src


def test_backlink_targets_can_be_narrowed_to_one_product() -> None:
    """上架钩子只关心刚上的那个产品，全站扫是浪费。"""
    import inspect as _i

    from backend.app.modules.geo_series.content import backlink_targets

    sig = _i.signature(backlink_targets.collect_backlink_targets)
    assert "product_ids" in sig.parameters
    assert "if wanted and raw_id not in wanted" in _i.getsource(
        backlink_targets.collect_backlink_targets
    )


def test_n8n_merge_walks_every_block_and_shares_the_regex_with_python() -> None:
    """替换规则原本 Python 和 JS 各写一遍要手工同步。让 JS 那份由 Python 生成之后，
    改一处两边一起变。"""
    from backend.app.modules.content_core.html_blocks import js_block_regex_source
    from backend.app.modules.geo_series.n8n.build_backlink_workflow import build

    wf = build()
    merge = next(
        n["parameters"]["jsCode"] for n in wf["nodes"] if n["name"] == "拼描述"
    )
    assert "row.blocks" in merge and "forEach" in merge
    # 正则来自 Python 那一个真相源——把 JS 里的 PATTERNS 解析出来逐条比对,
    # 不是"看着像"。改 html_blocks 而忘了重新生成 workflow,这条会红。
    import json as _json

    start = merge.index("PATTERNS = ") + len("PATTERNS = ")
    end = merge.index(";", start)
    patterns = _json.loads(merge[start:end])
    for cls in ("kp-guides", "kp-factory"):
        expected = js_block_regex_source(cls).strip("/").rsplit("/", 1)[0]
        assert patterns[cls] == expected
    # 替换值用函数形式——块里含 $& / $1 会被当替换模式解释
    assert "() => block" in merge
    # 不认识的 class 一律不动
    assert "if (!source) { return; }" in merge
    # 仍然只写 description
    assert "wp_body: { description: next }" in merge
    for forbidden in ("regular_price", "stock", "images", "categories"):
        assert forbidden not in merge
