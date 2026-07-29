"""Mirror K's Google taxonomy into WordPress **post** categories.

Owner's ruling (2026-07-29): guide articles are filed strictly under the category
tree K already defines — the Google Product Taxonomy — not under the ad-hoc
categories that exist on the site. That is the same tree P mirrors into Woo
product categories, so products and guides end up sharing one structure.

**Why this reuses ``p_series/upload/wc_categories`` internals instead of copying
them:** the only real differences between filing a product category and filing a
post category are the REST endpoint (``wp/v2/categories`` vs
``wc/v3/products/categories``) and the learned-id cache table. Everything that is
hard — slug normalisation, path validation, candidate matching, retry/backoff,
and the reconcile-before-replay rule that makes a lost POST safe — must behave
*identically*, or the two trees silently diverge and the same taxonomy node ends
up with two different slugs. So the hardened helpers are imported, and only the
endpoint, the cache, and the orchestration live here.

Credentials are the same WordPress application password (it authenticates both
wp/v2 and wc/v3), read from Settings exactly as the P path does.

Failure never blocks publishing: the caller omits the category and the article
still goes live, mirroring P.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from sqlalchemy import bindparam, select, text
from sqlalchemy.orm import Session

from ....core.config import Settings, get_settings
from .models import GeoWpCategoryMap
from ...p_series.upload.wc_categories import (  # hardened, deliberately shared
    WCCategoryConfigurationError,
    WCCategoryError,
    _create_category,
    _find_existing_category,
    _owned_client,
    _path_nodes,
    _positive_int,
    _PathNode,
    _secret_value,
)

logger = logging.getLogger(__name__)

# WordPress core taxonomy for posts — NOT product_cat.
_CATEGORY_ENDPOINT = "/wp-json/wp/v2/categories"

_READ_CACHE = text(
    "SELECT google_id, wp_term_id FROM geo_wp_category_map "
    "WHERE google_id IN :google_ids"
).bindparams(bindparam("google_ids", expanding=True))
_UPSERT_CACHE = text(
    "INSERT INTO geo_wp_category_map (google_id, wp_term_id, synced_at) "
    "VALUES (:google_id, :wp_term_id, :synced_at) "
    "ON CONFLICT (google_id) DO UPDATE SET "
    "wp_term_id = EXCLUDED.wp_term_id, synced_at = EXCLUDED.synced_at"
)


@dataclass(frozen=True, slots=True)
class _WpPostCategoryConfig:
    """Duck-types ``_WCConfig`` — the shared helpers only read these four."""

    base_url: str
    username: str
    password: str = field(repr=False)
    timeout_seconds: float = 10.0
    max_attempts: int = 3

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}{_CATEGORY_ENDPOINT}"

    @property
    def timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            self.timeout_seconds, connect=min(5.0, self.timeout_seconds)
        )

    @property
    def auth(self) -> httpx.BasicAuth:
        return httpx.BasicAuth(self.username, self.password)


def _config_from_settings(settings: Settings | None) -> _WpPostCategoryConfig:
    configured = settings or get_settings()
    base_url = str(getattr(configured, "wp_base_url", None) or "").strip().rstrip("/")
    username = str(getattr(configured, "wp_app_user", None) or "").strip()
    password = _secret_value(getattr(configured, "wp_app_password", None))
    if not base_url or not username or not password:
        raise WCCategoryConfigurationError(
            "WordPress post-category REST credentials are not configured."
        )
    timeout = float(getattr(configured, "wp_request_timeout_seconds", 10.0) or 10.0)
    attempts = int(getattr(configured, "wp_request_max_attempts", 3) or 3)
    return _WpPostCategoryConfig(
        base_url=base_url,
        username=username,
        password=password,
        timeout_seconds=max(1.0, timeout),
        max_attempts=max(1, attempts),
    )


def _rollback_cache(db: Session) -> None:
    try:
        db.rollback()
    except Exception:  # noqa: BLE001 - cache trouble must never break publishing
        logger.exception("GEO category cache rollback failed")


def _read_cached_terms(
    db: Session, nodes: Sequence[_PathNode]
) -> dict[str, int]:
    try:
        rows = db.execute(
            _READ_CACHE, {"google_ids": [node.google_id for node in nodes]}
        ).all()
        expected = {node.google_id for node in nodes}
        cached: dict[str, int] = {}
        for row in rows:
            google_id = str(row[0])
            term_id = _positive_int(row[1])
            if google_id in expected and term_id is not None:
                cached[google_id] = term_id
        # 死规矩: release the read transaction before any outbound call.
        db.commit()
        return cached
    except Exception:  # noqa: BLE001 - remote ensure still works without cache
        _rollback_cache(db)
        logger.warning(
            "GEO category cache read failed; continuing without cache.",
            exc_info=True,
        )
        return {}


def _write_cached_terms(db: Session, mappings: Mapping[str, int]) -> None:
    if not mappings:
        return
    synced_at = datetime.now(UTC)
    try:
        for google_id, wp_term_id in mappings.items():
            db.execute(
                _UPSERT_CACHE,
                {
                    "google_id": google_id,
                    "wp_term_id": wp_term_id,
                    "synced_at": synced_at,
                },
            )
        db.commit()
    except Exception:  # noqa: BLE001 - a valid term id is still safe to return
        _rollback_cache(db)
        logger.warning(
            "GEO category cache write failed; returning remote term id.",
            exc_info=True,
        )


def ensure_post_category_path(
    db: Session,
    path: Sequence[Mapping[str, str]],
    *,
    client: httpx.Client | None = None,
    settings: Settings | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Ensure the whole Google path exists as post categories; return the leaf id.

    Same shape as ``ensure_wc_category_path``: cache first (a known leaf skips the
    walk entirely), then find-or-create level by level, and only write what was
    learned once the complete remote path succeeded.
    """
    nodes = _path_nodes(path)
    cached = _read_cached_terms(db, nodes)
    cached_leaf = cached.get(nodes[-1].google_id)
    if cached_leaf is not None:
        return cached_leaf

    config = _config_from_settings(settings)
    active_client = client or _owned_client(config)
    owns_client = client is None
    learned: dict[str, int] = {}
    parent_id = 0  # 0 = taxonomy root
    try:
        for node in nodes:
            known = cached.get(node.google_id)
            if known is not None:
                parent_id = known
                continue
            found = _find_existing_category(
                active_client, config, node=node, parent_id=parent_id, sleep=sleep
            )
            term_id = found if found is not None else _create_category(
                active_client, config, node=node, parent_id=parent_id, sleep=sleep
            )
            learned[node.google_id] = term_id
            parent_id = term_id
    finally:
        if owns_client:
            active_client.close()

    _write_cached_terms(db, learned)
    return parent_id


class GeoCategoryError(RuntimeError):
    """The cluster cannot be filed under its Google-taxonomy category."""


def ensure_cluster_category(
    db: Session, *, cluster: object, settings: Settings | None = None
) -> int:
    """Leaf post-category id for a cluster's Google path. Raises rather than skipping.

    **Owner's ruling 2026-07-29: a guide must never be published uncategorised.**
    This used to return ``None`` on any failure and the publisher simply omitted the
    ``categories`` field — the post went live outside the site's structure, invisible
    to the taxonomy the whole hub is built on. Now every failure raises, the package
    endpoint turns it into a 409, and nothing is published at all.

    Creating the terms is the same find-or-create walk P uses for Woo product
    categories, so guides and products mirror one Google tree.
    """
    google_id = str(getattr(cluster, "google_category_id", "") or "").strip()
    if not google_id:
        raise GeoCategoryError(
            "这个话题簇没有绑定谷歌类目——指南必须落在类目里，不能无类目上线。"
        )
    from ...k_series.product_knowledge.category_resolver import google_category_path

    try:
        path = google_category_path(db, google_id)
    except Exception as exc:  # noqa: BLE001
        _rollback_cache(db)
        raise GeoCategoryError(f"谷歌类目 {google_id} 解析失败：{exc}") from exc
    if not path:
        raise GeoCategoryError(
            f"谷歌类目 {google_id} 在类目树里找不到路径——不能无类目上线。"
        )
    try:
        term_id = ensure_post_category_path(db, path, settings=settings)
    except WCCategoryError as exc:
        _rollback_cache(db)
        raise GeoCategoryError(
            f"WordPress 分类创建失败（{' > '.join(path)}）：{exc}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        _rollback_cache(db)
        raise GeoCategoryError(
            f"WordPress 分类创建异常（{' > '.join(path)}）：{exc}"
        ) from exc
    if not isinstance(term_id, int) or term_id <= 0:
        raise GeoCategoryError(
            f"WordPress 没有返回有效的分类 id（{' > '.join(path)}）。"
        )
    return term_id


__all__ = [
    "GEO_CATEGORY_IDS_OPTION",
    "GeoCategoryError",
    "ensure_cluster_category",
    "ensure_post_category_path",
    "sync_geo_category_exclusions",
    "sync_geo_category_exclusions_safely",
]


# ---------------------------------------------------------------- rail 3
# Keep guides out of the blog archive. The exclusion list is data, not code: the
# console owns it and pushes it to a WordPress option that the thin plugin
# ``barong-geo-archive`` reads. New Google categories therefore start being
# excluded the moment they are created — the plugin is never re-uploaded.

GEO_CATEGORY_IDS_OPTION = "barong_geo_category_ids"


def sync_geo_category_exclusions(db: Session, settings: Settings | None = None) -> str:
    """Push every category GEO owns to the site. Returns the value written."""
    from ....services import wp_bridge

    rows = db.execute(select(GeoWpCategoryMap.wp_term_id)).all()
    ids = sorted({int(r[0]) for r in rows if r and int(r[0] or 0) > 0})
    value = ",".join(str(i) for i in ids)
    # 死规矩: release the transaction before talking to WordPress.
    db.commit()

    credentials = wp_bridge._resolve_credentials(db=db)
    if credentials is None:
        raise WCCategoryError("WordPress credentials unavailable")
    result = wp_bridge._request_json(
        wp_bridge._api_url(credentials, "settings"),
        credentials=credentials,
        authenticated=True,
        method="POST",
        payload={GEO_CATEGORY_IDS_OPTION: value},
    )
    if not result.get("reachable"):
        raise WCCategoryError(str(result.get("error") or "settings write failed"))
    return value


def sync_geo_category_exclusions_safely(
    db: Session, settings: Settings | None = None
) -> str | None:
    """Same, fail-open: guides are already live, the blog filter is a nicety.

    Never raise into a publish run — if the plugin is not installed yet the option
    write simply has no reader, which is exactly the pre-install state.
    """
    try:
        return sync_geo_category_exclusions(db, settings)
    except Exception:  # noqa: BLE001 - the blog filter never blocks publishing
        logger.exception("GEO category exclusion sync failed")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("GEO category exclusion rollback failed")
        return None
