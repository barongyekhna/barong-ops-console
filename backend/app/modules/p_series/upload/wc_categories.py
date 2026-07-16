"""On-demand WooCommerce product-category path synchronization.

The console owns the category-tree control state.  It resolves one Google
taxonomy path at a time, reuses cached WooCommerce term ids, and creates only
the missing ``product_cat`` ancestors.  Network and cache failures are kept
separate so a successful remote lookup/create can still be returned when the
local cache is temporarily unavailable.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from ....core.config import Settings, get_settings


logger = logging.getLogger(__name__)

_CATEGORY_ENDPOINT = "/wp-json/wc/v3/products/categories"
_MAX_TERM_SLUG_LENGTH = 200
_MAX_PATH_DEPTH = 64
_RETRYABLE_STATUSES = frozenset({408, 425, 429})

_READ_CACHE = text(
    "SELECT google_id, wc_term_id FROM k_category_wc_map "
    "WHERE google_id IN :google_ids"
).bindparams(bindparam("google_ids", expanding=True))
_UPSERT_CACHE = text(
    "INSERT INTO k_category_wc_map (google_id, wc_term_id, synced_at) "
    "VALUES (:google_id, :wc_term_id, :synced_at) "
    "ON CONFLICT (google_id) DO UPDATE SET "
    "wc_term_id = EXCLUDED.wc_term_id, synced_at = EXCLUDED.synced_at"
)


class WCCategoryError(RuntimeError):
    """Base error for the WooCommerce category synchronization boundary."""


class WCCategoryConfigurationError(WCCategoryError):
    """The WooCommerce REST configuration is missing or unsafe."""


class WCCategoryAuthenticationError(WCCategoryError):
    """WooCommerce rejected the configured application-password credentials."""


class WCCategoryUnavailableError(WCCategoryError):
    """WooCommerce could not be reached after bounded retries."""


class WCCategoryRequestError(WCCategoryError):
    """WooCommerce rejected a category request."""


class WCCategoryProtocolError(WCCategoryError):
    """WooCommerce returned an invalid category response."""


@dataclass(frozen=True, slots=True)
class _PathNode:
    google_id: str
    name: str
    slug: str


@dataclass(frozen=True, slots=True)
class _WCConfig:
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
            self.timeout_seconds,
            connect=min(5.0, self.timeout_seconds),
        )

    @property
    def auth(self) -> httpx.BasicAuth:
        return httpx.BasicAuth(self.username, self.password)


def _secret_value(value: object) -> str:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        raw = getter()
        return raw if isinstance(raw, str) else ""
    return value if isinstance(value, str) else ""


def _config_from_settings(settings: Settings | None) -> _WCConfig:
    configured = settings or get_settings()
    app_env = str(getattr(configured, "app_env", "development") or "development")
    app_env = app_env.strip().casefold()
    base_url = str(getattr(configured, "wp_base_url", None) or "").strip()
    username = str(getattr(configured, "wp_app_user", None) or "").strip()
    password = _secret_value(getattr(configured, "wp_app_password", None))
    if not base_url or not username or not password:
        raise WCCategoryConfigurationError(
            "WooCommerce category REST credentials are not configured."
        )

    base_url = base_url.rstrip("/")
    parsed = urlsplit(base_url)
    try:
        port = parsed.port
    except ValueError:
        raise WCCategoryConfigurationError(
            "WooCommerce base URL is invalid."
        ) from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65_535)
        or (app_env in {"staging", "production"} and parsed.scheme != "https")
    ):
        raise WCCategoryConfigurationError("WooCommerce base URL is invalid.")

    try:
        timeout_seconds = float(
            getattr(configured, "wp_request_timeout_seconds", 10.0)
        )
        max_attempts = int(getattr(configured, "wp_request_max_attempts", 3))
    except (TypeError, ValueError):
        raise WCCategoryConfigurationError(
            "WooCommerce retry configuration is invalid."
        ) from None
    if not 0 < timeout_seconds <= 60 or not 1 <= max_attempts <= 5:
        raise WCCategoryConfigurationError(
            "WooCommerce retry configuration is invalid."
        )
    return _WCConfig(
        base_url=base_url,
        username=username,
        password=password,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
    )


def _display_name(value: str) -> str:
    decoded = html.unescape(value)
    normalized = unicodedata.normalize("NFKC", decoded)
    return re.sub(r"\s+", " ", normalized).strip()


def _normalized_name(value: str) -> str:
    return _display_name(value).casefold()


def _slug_for(name: str, google_id: str) -> str:
    decoded = html.unescape(name).replace("&", " and ")
    decomposed = unicodedata.normalize("NFKD", decoded).casefold()
    ascii_name = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    slug = slug[:_MAX_TERM_SLUG_LENGTH].rstrip("-")
    if slug:
        return slug
    decomposed_id = unicodedata.normalize("NFKD", google_id).casefold()
    ascii_id = decomposed_id.encode("ascii", "ignore").decode("ascii")
    normalized_id = re.sub(r"[^a-z0-9]+", "-", ascii_id).strip("-")
    if not normalized_id:
        normalized_id = hashlib.sha256(google_id.encode("utf-8")).hexdigest()[:16]
    return f"google-{normalized_id}"[:_MAX_TERM_SLUG_LENGTH].rstrip("-")


def _path_nodes(path: Sequence[Mapping[str, str]]) -> tuple[_PathNode, ...]:
    if not path:
        raise WCCategoryProtocolError("WooCommerce category path is empty.")
    if len(path) > _MAX_PATH_DEPTH:
        raise WCCategoryProtocolError("WooCommerce category path is too deep.")

    nodes: list[_PathNode] = []
    seen_ids: set[str] = set()
    for raw in path:
        google_id = str(raw.get("google_id") or "").strip()
        name = _display_name(str(raw.get("name") or ""))
        if not google_id or not name or google_id in seen_ids:
            raise WCCategoryProtocolError(
                "WooCommerce category path contains an invalid node."
            )
        seen_ids.add(google_id)
        nodes.append(
            _PathNode(
                google_id=google_id,
                name=name,
                slug=_slug_for(name, google_id),
            )
        )
    return tuple(nodes)


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _rollback_cache(db: Session) -> None:
    try:
        db.rollback()
    except Exception:  # noqa: BLE001 - cache failure must not sink the upload
        logger.warning(
            "WooCommerce category cache rollback failed.",
            exc_info=True,
        )


def _read_cached_terms(
    db: Session,
    nodes: Sequence[_PathNode],
) -> dict[str, int]:
    try:
        rows = db.execute(
            _READ_CACHE,
            {"google_ids": [node.google_id for node in nodes]},
        ).all()
        cached: dict[str, int] = {}
        expected = {node.google_id for node in nodes}
        for row in rows:
            google_id = str(row[0])
            term_id = _positive_int(row[1])
            if google_id in expected and term_id is not None:
                cached[google_id] = term_id
        # Do not hold the cache read transaction open across remote retries.
        db.commit()
        return cached
    except Exception:  # noqa: BLE001 - remote ensure remains useful without cache
        _rollback_cache(db)
        logger.warning(
            "WooCommerce category cache read failed; continuing without cache.",
            exc_info=True,
        )
        return {}


def _write_cached_terms(db: Session, mappings: Mapping[str, int]) -> None:
    if not mappings:
        return
    synced_at = datetime.now(UTC)
    try:
        for google_id, wc_term_id in mappings.items():
            db.execute(
                _UPSERT_CACHE,
                {
                    "google_id": google_id,
                    "wc_term_id": wc_term_id,
                    "synced_at": synced_at,
                },
            )
        db.commit()
    except Exception:  # noqa: BLE001 - a valid WC id is still safe to return
        _rollback_cache(db)
        logger.warning(
            "WooCommerce category cache write failed; returning remote term id.",
            exc_info=True,
        )


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    backoff = min(2.0, 0.25 * (2**attempt))
    if response is None:
        return backoff
    retry_after = response.headers.get("retry-after", "").strip()
    try:
        requested = float(retry_after)
    except ValueError:
        return backoff
    return min(5.0, max(backoff, requested, 0.0))


def _pause(
    sleep: Callable[[float], None],
    *,
    response: httpx.Response | None,
    attempt: int,
) -> None:
    sleep(_retry_delay(response, attempt))


def _is_retryable_status(status_code: int) -> bool:
    return status_code in _RETRYABLE_STATUSES or status_code >= 500


def _request_once(
    client: httpx.Client,
    config: _WCConfig,
    method: str,
    *,
    params: Mapping[str, object] | None = None,
    payload: Mapping[str, object] | None = None,
) -> httpx.Response:
    return client.request(
        method,
        config.endpoint,
        params=params,
        json=payload,
        auth=config.auth,
        timeout=config.timeout,
        follow_redirects=False,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )


def _response_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        raise WCCategoryProtocolError(
            "WooCommerce returned invalid category JSON."
        ) from None


def _get_categories(
    client: httpx.Client,
    config: _WCConfig,
    *,
    params: Mapping[str, object],
    sleep: Callable[[float], None],
) -> list[Mapping[str, Any]]:
    for attempt in range(config.max_attempts):
        try:
            response = _request_once(client, config, "GET", params=params)
        except httpx.RequestError:
            if attempt + 1 >= config.max_attempts:
                raise WCCategoryUnavailableError(
                    "WooCommerce category lookup is unavailable."
                ) from None
            _pause(sleep, response=None, attempt=attempt)
            continue

        if response.status_code == 200:
            payload = _response_json(response)
            if not isinstance(payload, list):
                raise WCCategoryProtocolError(
                    "WooCommerce category lookup returned an invalid payload."
                )
            return [item for item in payload if isinstance(item, Mapping)]
        if response.status_code in {401, 403}:
            raise WCCategoryAuthenticationError(
                "WooCommerce rejected category REST credentials."
            )
        if _is_retryable_status(response.status_code):
            if attempt + 1 >= config.max_attempts:
                raise WCCategoryUnavailableError(
                    "WooCommerce category lookup is unavailable."
                )
            _pause(sleep, response=response, attempt=attempt)
            continue
        raise WCCategoryRequestError(
            f"WooCommerce category lookup failed with HTTP {response.status_code}."
        )
    raise WCCategoryUnavailableError(
        "WooCommerce category lookup is unavailable."
    )


def _candidate_term_id(
    candidate: Mapping[str, Any],
    *,
    node: _PathNode,
    parent_id: int,
) -> int | None:
    term_id = _positive_int(candidate.get("id"))
    candidate_parent = candidate.get("parent")
    if (
        term_id is None
        or isinstance(candidate_parent, bool)
        or not isinstance(candidate_parent, int)
        or candidate_parent != parent_id
    ):
        return None
    candidate_slug = str(candidate.get("slug") or "").strip().casefold()
    candidate_name = str(candidate.get("name") or "")
    if (
        candidate_slug == node.slug.casefold()
        or _normalized_name(candidate_name) == _normalized_name(node.name)
    ):
        return term_id
    return None


def _find_existing_category(
    client: httpx.Client,
    config: _WCConfig,
    *,
    node: _PathNode,
    parent_id: int,
    sleep: Callable[[float], None],
) -> int | None:
    lookups = (
        {"slug": node.slug, "parent": parent_id, "per_page": 100},
        {"search": node.name, "parent": parent_id, "per_page": 100},
    )
    for params in lookups:
        candidates = _get_categories(
            client,
            config,
            params=params,
            sleep=sleep,
        )
        for candidate in candidates:
            term_id = _candidate_term_id(
                candidate,
                node=node,
                parent_id=parent_id,
            )
            if term_id is not None:
                return term_id
    return None


def _is_term_exists(response: httpx.Response) -> bool:
    if response.status_code not in {400, 409}:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    if not isinstance(payload, Mapping):
        return False
    return "term_exists" in str(payload.get("code") or "").casefold()


def _created_term_id(
    response: httpx.Response,
    *,
    node: _PathNode,
    parent_id: int,
) -> int:
    payload = _response_json(response)
    if not isinstance(payload, Mapping):
        raise WCCategoryProtocolError(
            "WooCommerce category creation returned an invalid payload."
        )
    term_id = _candidate_term_id(payload, node=node, parent_id=parent_id)
    if term_id is None:
        raise WCCategoryProtocolError(
            "WooCommerce category creation returned a mismatched term."
        )
    return term_id


def _create_category(
    client: httpx.Client,
    config: _WCConfig,
    *,
    node: _PathNode,
    parent_id: int,
    sleep: Callable[[float], None],
) -> int:
    body = {"name": node.name, "slug": node.slug, "parent": parent_id}
    for attempt in range(config.max_attempts):
        response: httpx.Response | None = None
        request_failed = False
        try:
            response = _request_once(
                client,
                config,
                "POST",
                payload=body,
            )
        except httpx.RequestError:
            request_failed = True

        if response is not None and response.status_code in {200, 201}:
            return _created_term_id(
                response,
                node=node,
                parent_id=parent_id,
            )
        if response is not None and response.status_code in {401, 403}:
            raise WCCategoryAuthenticationError(
                "WooCommerce rejected category REST credentials."
            )

        should_reconcile = request_failed or (
            response is not None
            and (
                _is_retryable_status(response.status_code)
                or _is_term_exists(response)
            )
        )
        if should_reconcile:
            # A POST can succeed remotely even when its response is lost.  Always
            # look up the deterministic (parent, slug/name) term before replay.
            existing = _find_existing_category(
                client,
                config,
                node=node,
                parent_id=parent_id,
                sleep=sleep,
            )
            if existing is not None:
                return existing
            if attempt + 1 >= config.max_attempts:
                raise WCCategoryUnavailableError(
                    "WooCommerce category creation could not be reconciled."
                )
            _pause(sleep, response=response, attempt=attempt)
            continue

        status_code = response.status_code if response is not None else None
        if status_code is None:
            raise WCCategoryUnavailableError(
                "WooCommerce category creation is unavailable."
            )
        raise WCCategoryRequestError(
            f"WooCommerce category creation failed with HTTP {status_code}."
        )
    raise WCCategoryUnavailableError(
        "WooCommerce category creation is unavailable."
    )


def _owned_client(config: _WCConfig) -> httpx.Client:
    return httpx.Client(
        auth=config.auth,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=config.timeout,
        follow_redirects=False,
        trust_env=False,
    )


def ensure_wc_category_path(
    db: Session,
    path: Sequence[Mapping[str, str]],
    *,
    client: httpx.Client | None = None,
    settings: Settings | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Ensure one Google taxonomy path exists and return its leaf WC term id.

    Cache reads and writes are best-effort.  All remote operations happen after
    the cache read transaction is committed, and all newly learned mappings are
    persisted only after the complete remote path succeeds.
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
    parent_id = 0
    try:
        for node in nodes:
            cached_term = cached.get(node.google_id)
            if cached_term is not None:
                parent_id = cached_term
                continue
            term_id = _find_existing_category(
                active_client,
                config,
                node=node,
                parent_id=parent_id,
                sleep=sleep,
            )
            if term_id is None:
                term_id = _create_category(
                    active_client,
                    config,
                    node=node,
                    parent_id=parent_id,
                    sleep=sleep,
                )
            learned[node.google_id] = term_id
            parent_id = term_id
    finally:
        if owns_client:
            active_client.close()

    _write_cached_terms(db, learned)
    return parent_id


__all__ = [
    "WCCategoryAuthenticationError",
    "WCCategoryConfigurationError",
    "WCCategoryError",
    "WCCategoryProtocolError",
    "WCCategoryRequestError",
    "WCCategoryUnavailableError",
    "ensure_wc_category_path",
]
