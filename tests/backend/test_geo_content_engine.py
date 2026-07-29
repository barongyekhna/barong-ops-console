"""GEO content engine — milestone 1 (content engine).

Behavioral tests for the output guards (the fail-closed core) + source/wiring
assertions for the skill, orchestrator, queue, and router.
"""

from __future__ import annotations

import inspect

import pytest

# Load the app model registry first so importing geo modules directly does not
# trip the (K-style) circular import through backend.app.models.
import backend.app.models  # noqa: F401,E402

pytestmark = pytest.mark.unit


# --------------------------------------------------------------- guards


def test_evidence_number_corpus_extracts_spec_numbers() -> None:
    from backend.app.modules.geo_series.content.guards import evidence_number_corpus

    corpus = evidence_number_corpus(
        "2.11 GPM flow", "90 minutes runtime", "6.5 ft hose", "IPX8"
    )
    assert "2.11" in corpus
    assert "90" in corpus
    assert "6.5" in corpus


def test_audit_passes_clean_grounded_item() -> None:
    from backend.app.modules.geo_series.content.guards import (
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
    from backend.app.modules.geo_series.content.guards import audit_content_item

    item = {"title": "The Ivation shower beats it", "sections": []}
    audit = audit_content_item(
        item, forbidden_terms=["ivation"], evidence_numbers=set()
    )
    assert audit["clean"] is False
    assert audit["brand_violations"]


def test_audit_flags_ungrounded_number() -> None:
    from backend.app.modules.geo_series.content.guards import audit_content_item

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
    from backend.app.modules.geo_series.content.guards import audit_content_item

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
    assert "google_category_id == google_id" in src
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
    from backend.app.modules.geo_series.content.analysis import analysis_instruction

    prompt = analysis_instruction()
    assert "禁止套话" in prompt
    for field in ("translation", "geo_role", "why_written_this_way", "strengths", "risks"):
        assert field in prompt


def test_analysis_is_fail_open_and_never_blocks_content() -> None:
    from backend.app.modules.geo_series.content import analysis

    src = inspect.getsource(analysis.analyze_content)
    assert "except Exception" in src
    assert "return None" in src
    wrapper = inspect.getsource(analysis.attach_analysis_safely)
    assert "except Exception" in wrapper
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
    from backend.app.modules.geo_series.content import analysis

    src = inspect.getsource(analysis.attach_analysis_safely)
    snapshot_at = src.index("_item_payload(item)) for item in items")
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
    from backend.app.modules.geo_series.content import critique

    for fn in (critique.collect_critiques, critique.collect_data_gaps):
        src = inspect.getsource(fn)
        assert "AIExecutionRouter" not in src
        assert "SessionLocal" not in src


def test_data_gaps_group_by_missing_fact() -> None:
    from types import SimpleNamespace

    from backend.app.modules.geo_series.content.critique import collect_data_gaps

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
    from backend.app.modules.geo_series.content.critique import (
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

    from backend.app.modules.geo_series.content.publish_html import (
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
        sibling_links=[("Sibling", "item-2")],
    )
    # the product page exists → real link; the sibling post does not → placeholder
    assert "https://site/product/x/" in html
    assert unresolved_link_tokens(html) == ["{{GEO_LINK_item-2}}"]
    assert not unresolved_link_tokens(
        resolve_link_tokens(html, {"item-2": "https://site/guide-2/"})
    )


def test_publish_queue_mirrors_p_serial_semantics() -> None:
    from backend.app.modules.geo_series.content import publish_jobs

    src = inspect.getsource(publish_jobs)
    assert "IN_FLIGHT_TIMEOUT_MINUTES = 15" in src
    # strictly one dispatch in flight
    assert 'GeoPublishJob.status == "dispatched"' in src
    # commit before sending (the 2026-07-23 race fix inherited from P)
    kick = inspect.getsource(publish_jobs.kick_queue)
    assert kick.index("db.commit()") < kick.index("_send_to_n8n(job")
    # terminal-state idempotency
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
    # never blocks publishing
    ensure = inspect.getsource(wp_categories.ensure_cluster_category)
    assert "return None" in ensure


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
