"""K 路由清单的**逐条**基准。

为什么值得单开一份：K 的 router 有 6763 行、81 个路由、两套挂载前缀，而
在这之前它的 HTTP 级回归网只有 1 个文件 6 条断言。任何一次重构（比如把
它剥成 service 层）都可能悄悄少注册一条 —— 而**少一条不会有任何东西报错**：
前端调那个 URL 会拿到 404，看起来像「功能坏了」，没人会想到是路由掉了。

尤其是这五组**双路径别名**：`/risks` 与 `/risk`、`/research` 与
`/keyword-research/start`。它们零测试覆盖、零注释说明谁在用，断了是静默的。

这份清单是**基准快照**：改路由是正常的，但必须**有意**地改，
连带更新这里的期望值。测试失败时先问「这条是我故意加/删的吗」。
"""

from __future__ import annotations

import backend.app.models  # noqa: F401 - 先装载模型注册表
from backend.app.modules.k_series.product_knowledge.router import router

#: 五组同一处理函数挂两个 URL 的别名。断了是静默的 404。
DUAL_PATH_ALIASES = [
    ("GET", "/k/risks", "/k/risk"),
    ("POST", "/k/risks", "/k/risk"),
    ("PATCH", "/k/risks/{risk_id}", "/k/risk/{risk_id}"),
    ("DELETE", "/k/risks/{risk_id}", "/k/risk/{risk_id}"),
    ("POST", "/k/research", "/k/keyword-research/start"),
]


def _registered() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in router.routes
        for method in getattr(route, "methods", None) or []
        if method != "HEAD"
    }


def test_route_count_is_pinned() -> None:
    """路由总数的基准。改了要有意识地改这个数字。"""
    assert len(_registered()) == 81, sorted(_registered())


def test_every_dual_path_alias_is_still_registered() -> None:
    """**红线**：五组别名一条都不能少。

    它们没有任何调用方注释，也没有测试覆盖 —— 删掉不会有东西变红，
    只会在某个前端按钮上变成 404。
    """
    registered = _registered()
    missing = [
        (method, primary, alias)
        for method, primary, alias in DUAL_PATH_ALIASES
        if (method, primary) not in registered or (method, alias) not in registered
    ]
    assert missing == [], f"双路径别名掉了：{missing}"


def test_route_inventory_matches_the_snapshot() -> None:
    """逐条比对。**这是重构 K router 时唯一靠得住的验收**。

    数量对不代表清单对：删掉一条、又加一条新的，总数不变。
    """
    expected = set(EXPECTED_ROUTES)
    actual = _registered()
    added = sorted(actual - expected)
    removed = sorted(expected - actual)
    assert not removed, f"路由消失了（前端会拿到 404）：{removed}"
    assert not added, f"多出没登记的路由：{added}（有意新增就把它加进 EXPECTED_ROUTES）"


EXPECTED_ROUTES: tuple[tuple[str, str], ...] = (
    ('DELETE', '/k/keywords/{keyword_id}'),
    ('DELETE', '/k/media/{asset_id}'),
    ('DELETE', '/k/products/{product_id}'),
    ('DELETE', '/k/risk/{risk_id}'),
    ('DELETE', '/k/risks/{risk_id}'),
    ('GET', '/k/categories/search'),
    ('GET', '/k/keywords/{product_id}'),
    ('GET', '/k/media'),
    ('GET', '/k/media/{asset_id}/download'),
    ('GET', '/k/media/{asset_id}/file'),
    ('GET', '/k/media/{asset_id}/preview'),
    ('GET', '/k/media/{asset_id}/thumbnail'),
    ('GET', '/k/products'),
    ('GET', '/k/products/{product_id}'),
    ('GET', '/k/products/{product_id}/attributes'),
    ('GET', '/k/products/{product_id}/generation-jobs'),
    ('GET', '/k/products/{product_id}/image-plates'),
    ('GET', '/k/products/{product_id}/keywords'),
    ('GET', '/k/products/{product_id}/overlay-fields'),
    ('GET', '/k/products/{product_id}/readiness'),
    ('GET', '/k/products/{product_id}/reference-image'),
    ('GET', '/k/products/{product_id}/render-assets'),
    ('GET', '/k/products/{product_id}/render-jobs'),
    ('GET', '/k/products/{product_id}/risk-terms'),
    ('GET', '/k/products/{product_id}/selling-points'),
    ('GET', '/k/products/{product_id}/workflow/latest'),
    ('GET', '/k/risk'),
    ('GET', '/k/risks'),
    ('PATCH', '/k/keywords/{keyword_id}'),
    ('PATCH', '/k/products/{product_id}'),
    ('PATCH', '/k/products/{product_id}/attributes'),
    ('PATCH', '/k/products/{product_id}/keywords'),
    ('PATCH', '/k/products/{product_id}/risk-terms'),
    ('PATCH', '/k/products/{product_id}/variant-prices'),
    ('PATCH', '/k/risk/{risk_id}'),
    ('PATCH', '/k/risks/{risk_id}'),
    ('POST', '/k/keyword-research/start'),
    ('POST', '/k/keywords'),
    ('POST', '/k/media'),
    ('POST', '/k/products'),
    ('POST', '/k/products/generate-copy/batch'),
    ('POST', '/k/products/generate-image-brief/batch'),
    ('POST', '/k/products/import-from-r'),
    ('POST', '/k/products/{product_id}/archive'),
    ('POST', '/k/products/{product_id}/brand-audit'),
    ('POST', '/k/products/{product_id}/brand-audit/ignore'),
    ('POST', '/k/products/{product_id}/brand-audit/override'),
    ('POST', '/k/products/{product_id}/brief-images'),
    ('POST', '/k/products/{product_id}/brief-images/{position}/overlay'),
    ('POST', '/k/products/{product_id}/enrich/deepseek'),
    ('POST', '/k/products/{product_id}/generate-copy'),
    ('POST', '/k/products/{product_id}/generate-image-brief'),
    ('POST', '/k/products/{product_id}/images/bind'),
    ('POST', '/k/products/{product_id}/images/import-i-output'),
    ('POST', '/k/products/{product_id}/images/submit'),
    ('POST', '/k/products/{product_id}/images/{asset_id}/upload-bound'),
    ('POST', '/k/products/{product_id}/keywords/submit'),
    ('POST', '/k/products/{product_id}/media/upload'),
    ('POST', '/k/products/{product_id}/render-assets/save'),
    ('POST', '/k/products/{product_id}/render-images'),
    ('POST', '/k/products/{product_id}/render-images/retry'),
    ('POST', '/k/products/{product_id}/render-rework'),
    ('POST', '/k/products/{product_id}/risk-filter'),
    ('POST', '/k/products/{product_id}/selling-points/approve'),
    ('POST', '/k/products/{product_id}/selling-points/generate'),
    ('POST', '/k/products/{product_id}/translate'),
    ('POST', '/k/products/{product_id}/workflow/export'),
    ('POST', '/k/products/{product_id}/workflow/pause'),
    ('POST', '/k/products/{product_id}/workflow/resume'),
    ('POST', '/k/products/{product_id}/workflow/retry'),
    ('POST', '/k/products/{product_id}/workflow/risk-review'),
    ('POST', '/k/products/{product_id}/workflow/rollback'),
    ('POST', '/k/products/{product_id}/workflow/start'),
    ('POST', '/k/research'),
    ('POST', '/k/risk'),
    ('POST', '/k/risks'),
    ('POST', '/k/selling-points/generate'),
    ('POST', '/k/serp/search'),
    ('PUT', '/k/products/{product_id}/faq'),
    ('PUT', '/k/products/{product_id}/image-plates/{asset_id}/mask'),
    ('PUT', '/k/products/{product_id}/operating-model'),
)


def test_both_mounts_expose_the_same_paths() -> None:
    """K 的 router 挂了**两套前缀**，两边必须一字不差。

      · `/api/app/k/…`  —— 浏览器走 Next 代理进来的
      · `/k/…`（裸挂）  —— n8n 取包/回报的机器路由

    只在一边注册同样是静默失败：某个前端按钮 404，或者 n8n 取不到包而
    整单卡到看门狗收尸。两边都不会有任何东西主动报错。
    """
    from backend.app.main import app

    paths = {route.path for route in app.routes if "/k/" in route.path}
    bare = {path for path in paths if path.startswith("/k/")}
    proxied = {path[len("/api/app") :] for path in paths if path.startswith("/api/app/k/")}

    assert bare, "裸挂的机器路由一条都没有了"
    assert bare == proxied, {
        "只在裸挂那边": sorted(bare - proxied),
        "只在代理那边": sorted(proxied - bare),
    }


# ---------------------------------------------------------------------------
# 兼容面：22 个测试文件直接从 router 里 import 这些符号
# ---------------------------------------------------------------------------

#: 存量测试从 `...product_knowledge.router` 直接引用的全部符号（2026-09-03 实测）。
#:
#: 把 6763 行的 router 剥成 service 层时，**这些名字必须继续能从 router 导入**
#: —— 尾部留 re-export 兼容层即可。少一个名字，对应的测试文件会以
#: ImportError 整份崩掉（不是某一条断言变红，是整份文件收集失败），
#: 在一堆输出里很容易被读成「环境问题」。
COMPAT_SURFACE: tuple[str, ...] = (
    "ApproveSellingPointsRequest",
    "BriefImageAddRequest",
    "ProductFaqUpdateRequest",
    "RenderReworkRequest",
    "SellingPointBullet",
    "_active_keyword_snapshot",
    "_claim_product_create_idempotency",
    "_complete_product_create_idempotency",
    "_discard_product_create_idempotency",
    "_ensure_product_ready_for_approval",
    "_execute_provider_json",
    "_execution_context",
    "_gate_error",
    "_humanize_selling_point_error",
    "_image_asset_for_product",
    "_image_dimensions",
    "_product_by_ref",
    "_product_create_fingerprint",
    "_product_full_ai_payload",
    "_product_read",
    "_product_readiness",
    "_require_k_permission",
    "_scope_context",
    "_selling_point_evidence_error",
    "_selling_point_evidence_snapshot",
    "_selling_point_review_error_message",
    "_selling_point_support_error",
    "_selling_points_response_from_payload",
    "_selling_points_snapshot",
    "_store_image_review_snapshot",
    "_store_keyword_review_snapshot",
    "_structured_spec_evidence_snapshot",
    "_structured_spec_path_exists",
    "_workflow_error",
    "approve_product_selling_points",
    "deepseek_enrich_product",
    "download_media_asset_file",
    "logger",
    "product_knowledge_brief_image_add",
    "product_knowledge_create",
    "product_knowledge_list_image_plates",
    "product_knowledge_render_rework",
    "product_knowledge_update_faq",
    "product_knowledge_workflow_start",
    "router",
    "set_image_upload_bound",
    "upload_product_media_asset",
)


def test_router_still_exports_everything_tests_import() -> None:
    """剥 service 层时的兼容面基准。

    这条测试的价值在重构**中途**：每剥一桶就跑一次，立刻知道有没有漏挂
    re-export。等到跑全量测试才发现，已经分不清是哪一步弄丢的。
    """
    from backend.app.modules.k_series.product_knowledge import router as module

    missing = [name for name in COMPAT_SURFACE if not hasattr(module, name)]
    assert missing == [], (
        f"这些符号从 router 消失了，存量测试会 ImportError：{missing}；"
        "剥走可以，但要在 router 尾部 re-export 回来"
    )
