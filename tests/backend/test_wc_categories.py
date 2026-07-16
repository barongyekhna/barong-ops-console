from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

from backend.app.core.config import Settings
from backend.app.modules.p_series.upload import wc_categories
from backend.app.modules.p_series.upload.wc_categories import (
    WCCategoryConfigurationError,
    ensure_wc_category_path,
)


pytestmark = pytest.mark.unit


class _Rows:
    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, object]]:
        return self._rows


class _FakeDB:
    def __init__(
        self,
        cache: dict[str, int] | None = None,
        *,
        fail_read: bool = False,
        fail_write: bool = False,
    ) -> None:
        self.cache = dict(cache or {})
        self.fail_read = fail_read
        self.fail_write = fail_write
        self.pending: dict[str, int] = {}
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement: object, params: dict[str, object]) -> _Rows:
        sql = str(statement)
        if sql.startswith("SELECT google_id, wc_term_id"):
            if self.fail_read:
                raise RuntimeError("cache read unavailable")
            google_ids = cast(list[str], params["google_ids"])
            return _Rows(
                [
                    (google_id, self.cache[google_id])
                    for google_id in google_ids
                    if google_id in self.cache
                ]
            )
        if sql.startswith("INSERT INTO k_category_wc_map"):
            if self.fail_write:
                raise RuntimeError("cache write unavailable")
            self.pending[str(params["google_id"])] = int(
                cast(int, params["wc_term_id"])
            )
            return _Rows([])
        raise AssertionError(f"unexpected SQL: {sql}")

    def commit(self) -> None:
        self.commits += 1
        self.cache.update(self.pending)
        self.pending.clear()

    def rollback(self) -> None:
        self.rollbacks += 1
        self.pending.clear()


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "development",
        "wp_base_url": "https://shop.example.test",
        "wp_app_user": "category-bot",
        "wp_app_password": SecretStr("example-app-password"),
        "wp_request_timeout_seconds": 7.0,
        "wp_request_max_attempts": 3,
    }
    values.update(overrides)
    return cast(Settings, SimpleNamespace(**values))


def _client(
    handler: httpx.MockTransport,
) -> httpx.Client:
    return httpx.Client(
        transport=handler,
        follow_redirects=True,
        trust_env=False,
    )


def _category(
    term_id: int,
    name: str,
    slug: str,
    parent: int,
) -> dict[str, object]:
    return {"id": term_id, "name": name, "slug": slug, "parent": parent}


def _no_sleep(_: float) -> None:
    return None


def test_leaf_cache_hit_returns_without_configuration_or_http() -> None:
    db = _FakeDB({"leaf": 902})
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("leaf cache hit must not call WooCommerce")

    with _client(httpx.MockTransport(handler)) as client:
        result = ensure_wc_category_path(
            cast(object, db),
            [
                {"google_id": "root", "name": "Home"},
                {"google_id": "leaf", "name": "Decor"},
            ],
            client=client,
            sleep=_no_sleep,
        )

    assert result == 902
    assert requests == []
    assert db.commits == 1


def test_partial_cache_reuses_parent_and_creates_only_missing_leaf() -> None:
    db = _FakeDB({"root": 41})
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            assert request.url.params["parent"] == "41"
            return httpx.Response(200, json=[])
        body = json.loads(request.content)
        assert body == {"name": "Wall Decor", "slug": "wall-decor", "parent": 41}
        return httpx.Response(
            201,
            json=_category(73, "Wall Decor", "wall-decor", 41),
        )

    with _client(httpx.MockTransport(handler)) as client:
        result = ensure_wc_category_path(
            cast(object, db),
            [
                {"google_id": "root", "name": "Home"},
                {"google_id": "leaf", "name": "Wall Decor"},
            ],
            client=client,
            settings=_settings(),
            sleep=_no_sleep,
        )

    assert result == 73
    assert [request.method for request in requests] == ["GET", "GET", "POST"]
    assert db.cache == {"root": 41, "leaf": 73}
    assert db.commits == 2


def test_missing_path_is_created_top_down_with_normalized_slugs() -> None:
    db = _FakeDB()
    created: list[dict[str, object]] = []
    next_id = iter((101, 102))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        body = cast(dict[str, object], json.loads(request.content))
        created.append(body)
        term_id = next(next_id)
        return httpx.Response(
            201,
            json=_category(
                term_id,
                cast(str, body["name"]),
                cast(str, body["slug"]),
                cast(int, body["parent"]),
            ),
        )

    with _client(httpx.MockTransport(handler)) as client:
        result = ensure_wc_category_path(
            cast(object, db),
            [
                {"google_id": "10", "name": "Café & Dining"},
                {"google_id": "11", "name": "Women's Décor"},
            ],
            client=client,
            settings=_settings(),
            sleep=_no_sleep,
        )

    assert result == 102
    assert created == [
        {"name": "Café & Dining", "slug": "cafe-and-dining", "parent": 0},
        {"name": "Women's Décor", "slug": "women-s-decor", "parent": 101},
    ]
    assert db.cache == {"10": 101, "11": 102}


def test_search_match_unescapes_html_and_never_crosses_parent() -> None:
    db = _FakeDB({"root": 20})
    post_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        if request.method == "POST":
            post_count += 1
            raise AssertionError("an existing child must be reused")
        if "slug" in request.url.params:
            return httpx.Response(
                200,
                json=[_category(50, "Arts &amp; Crafts", "arts-and-crafts", 999)],
            )
        return httpx.Response(
            200,
            json=[
                _category(50, "Arts &amp; Crafts", "arts-and-crafts", 999),
                _category(51, "Arts &amp; Crafts", "arts-crafts-2", 20),
            ],
        )

    with _client(httpx.MockTransport(handler)) as client:
        result = ensure_wc_category_path(
            cast(object, db),
            [
                {"google_id": "root", "name": "Hobbies"},
                {"google_id": "leaf", "name": "Arts & Crafts"},
            ],
            client=client,
            settings=_settings(),
            sleep=_no_sleep,
        )

    assert result == 51
    assert post_count == 0
    assert db.cache["leaf"] == 51


def test_lost_post_response_is_reconciled_before_any_replay() -> None:
    db = _FakeDB()
    created = False
    post_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal created, post_count
        if request.method == "POST":
            post_count += 1
            created = True
            raise httpx.ReadTimeout("response lost", request=request)
        if created and "slug" in request.url.params:
            return httpx.Response(
                200,
                json=[_category(301, "Lighting", "lighting", 0)],
            )
        return httpx.Response(200, json=[])

    with _client(httpx.MockTransport(handler)) as client:
        result = ensure_wc_category_path(
            cast(object, db),
            [{"google_id": "300", "name": "Lighting"}],
            client=client,
            settings=_settings(),
            sleep=_no_sleep,
        )

    assert result == 301
    assert post_count == 1
    assert db.cache["300"] == 301


def test_server_error_reconciles_then_retries_post_when_still_missing() -> None:
    db = _FakeDB()
    post_count = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_count
        if request.method == "GET":
            return httpx.Response(200, json=[])
        post_count += 1
        if post_count == 1:
            return httpx.Response(503, json={"code": "temporarily_unavailable"})
        return httpx.Response(
            201,
            json=_category(401, "Storage", "storage", 0),
        )

    with _client(httpx.MockTransport(handler)) as client:
        result = ensure_wc_category_path(
            cast(object, db),
            [{"google_id": "400", "name": "Storage"}],
            client=client,
            settings=_settings(),
            sleep=delays.append,
        )

    assert result == 401
    assert post_count == 2
    assert delays == [0.25]


def test_term_exists_response_is_reconciled_without_duplicate_post() -> None:
    db = _FakeDB()
    visible = False
    post_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal visible, post_count
        if request.method == "POST":
            post_count += 1
            visible = True
            return httpx.Response(
                400,
                json={"code": "woocommerce_rest_term_exists"},
            )
        if visible and "slug" in request.url.params:
            return httpx.Response(
                200,
                json=[_category(501, "Garden", "garden", 0)],
            )
        return httpx.Response(200, json=[])

    with _client(httpx.MockTransport(handler)) as client:
        result = ensure_wc_category_path(
            cast(object, db),
            [{"google_id": "500", "name": "Garden"}],
            client=client,
            settings=_settings(),
            sleep=_no_sleep,
        )

    assert result == 501
    assert post_count == 1


def test_cache_read_and_write_failures_do_not_hide_remote_term() -> None:
    db = _FakeDB(fail_read=True, fail_write=True)

    def handler(request: httpx.Request) -> httpx.Response:
        if "slug" in request.url.params:
            return httpx.Response(
                200,
                json=[_category(601, "Office", "office", 0)],
            )
        raise AssertionError("slug lookup should find the term")

    with _client(httpx.MockTransport(handler)) as client:
        result = ensure_wc_category_path(
            cast(object, db),
            [{"google_id": "600", "name": "Office"}],
            client=client,
            settings=_settings(),
            sleep=_no_sleep,
        )

    assert result == 601
    assert db.rollbacks == 2
    assert db.cache == {}


def test_missing_configuration_fails_before_http() -> None:
    db = _FakeDB()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(WCCategoryConfigurationError):
            ensure_wc_category_path(
                cast(object, db),
                [{"google_id": "700", "name": "Toys"}],
                client=client,
                settings=_settings(wp_app_password=None),
                sleep=_no_sleep,
            )

    assert requests == []


def test_production_configuration_requires_https() -> None:
    db = _FakeDB()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    with _client(httpx.MockTransport(handler)) as client:
        with pytest.raises(WCCategoryConfigurationError):
            ensure_wc_category_path(
                cast(object, db),
                [{"google_id": "secure", "name": "Secure"}],
                client=client,
                settings=_settings(
                    app_env="production",
                    wp_base_url="http://shop.example.test",
                ),
                sleep=_no_sleep,
            )

    assert requests == []


def test_slug_fallback_normalizes_malformed_google_id() -> None:
    db = _FakeDB()
    posted: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        body = cast(dict[str, object], json.loads(request.content))
        posted.append(body)
        return httpx.Response(
            201,
            json=_category(
                750,
                cast(str, body["name"]),
                cast(str, body["slug"]),
                0,
            ),
        )

    with _client(httpx.MockTransport(handler)) as client:
        result = ensure_wc_category_path(
            cast(object, db),
            [{"google_id": " Bad / ID ", "name": "家居"}],
            client=client,
            settings=_settings(wp_base_url="http://shop.example.test"),
            sleep=_no_sleep,
        )

    assert result == 750
    assert posted == [{"name": "家居", "slug": "google-bad-id", "parent": 0}]


def test_owned_client_uses_basic_auth_timeout_and_safe_transport_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB()
    constructor: dict[str, object] = {}
    requests: list[httpx.Request] = []
    expected_auth = "Basic " + base64.b64encode(
        b"category-bot:example-app-password"
    ).decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[_category(801, "Pet Supplies", "pet-supplies", 0)],
        )

    real_client = httpx.Client(transport=httpx.MockTransport(handler))

    def client_factory(**kwargs: object) -> httpx.Client:
        constructor.update(kwargs)
        return real_client

    monkeypatch.setattr(wc_categories.httpx, "Client", client_factory)
    result = ensure_wc_category_path(
        cast(object, db),
        [{"google_id": "800", "name": "Pet Supplies"}],
        settings=_settings(),
        sleep=_no_sleep,
    )

    assert result == 801
    assert constructor["trust_env"] is False
    assert constructor["follow_redirects"] is False
    assert isinstance(constructor["auth"], httpx.BasicAuth)
    assert isinstance(constructor["timeout"], httpx.Timeout)
    assert requests[0].headers["authorization"] == expected_auth
    assert requests[0].extensions["timeout"]["read"] == 7.0
