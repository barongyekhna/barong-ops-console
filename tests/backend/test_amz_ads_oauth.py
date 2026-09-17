"""广告 API 授权通道:授权链接、state、钥匙对形状、profile 挑选、换令牌与拉 profile(假传输层)。不碰库。"""

from __future__ import annotations

from types import SimpleNamespace as N

import httpx
import pytest

from backend.app.modules.amz_series.clients import ads_oauth
from backend.app.modules.amz_series.service import AmzServiceError

pytestmark = pytest.mark.unit


def test_authorize_url_and_state() -> None:
    url = ads_oauth.authorize_url(client_id="amzn1.application-oa2-client.abc", region="na", state="01us.n0nce")
    assert url.startswith("https://www.amazon.com/ap/oa?")
    assert "scope=advertising%3A%3Acampaign_management" in url and "state=01us.n0nce" in url
    assert "redirect_uri=https%3A%2F%2Fops.barongyekhna.com%2Famz%2Fads-callback" in url
    assert ads_oauth.authorize_url(client_id="x", region="eu", state="01de.n").startswith("https://eu.account.amazon.com/")
    assert ads_oauth.parse_state("01US.abc") == "01us"
    with pytest.raises(AmzServiceError):
        ads_oauth.parse_state("nodots")
    assert ads_oauth.ads_alias("01US") == "ads:01us"


def test_pick_profiles_keeps_only_this_stores_country() -> None:
    profiles = [
        {"profileId": 111, "countryCode": "US", "currencyCode": "USD", "accountInfo": {"type": "seller"}},
        {"profileId": 222, "countryCode": "CA", "currencyCode": "CAD", "accountInfo": {"type": "seller"}},
        {"profileId": 333, "countryCode": "US", "currencyCode": "USD", "accountInfo": {"type": "agency"}},
        {"profileId": 444, "countryCode": "DE", "currencyCode": "EUR", "accountInfo": {"type": "seller"}},
    ]
    us = ads_oauth.pick_profiles(profiles, country="US")
    assert [p["profileId"] for p in us] == ["111"]
    assert [p["profileId"] for p in ads_oauth.pick_profiles(profiles, country="de")] == ["444"]


def test_exchange_and_profiles_over_fake_transport() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.host}{request.url.path}")
        if request.url.host == "api.amazon.com":
            body = request.content.decode()
            assert "grant_type=authorization_code" in body and "code=THECODE" in body and "redirect_uri=https%3A%2F%2Fops.barongyekhna.com%2Famz%2Fads-callback" in body
            return httpx.Response(200, json={"access_token": "at", "refresh_token": "Atzr|rt", "expires_in": 3600})
        if request.url.path == "/v2/profiles":
            assert request.headers["Authorization"] == "Bearer at" and request.headers["Amazon-Advertising-API-ClientId"] == "cid"
            return httpx.Response(200, json=[{"profileId": 5, "countryCode": "US", "currencyCode": "USD", "accountInfo": {"type": "seller"}}])
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        tokens = ads_oauth.exchange_code(http, code="THECODE", client_id="cid", client_secret="sec")
        assert tokens["refresh_token"] == "Atzr|rt"
        profiles = ads_oauth.fetch_profiles(http, region="na", access_token=tokens["access_token"], client_id="cid")
        assert profiles[0]["profileId"] == 5
    assert seen == ["POST api.amazon.com/auth/o2/token", "GET advertising-api.amazon.com/v2/profiles"]

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with httpx.Client(transport=httpx.MockTransport(refuse)) as http, pytest.raises(AmzServiceError) as exc:
        ads_oauth.exchange_code(http, code="x", client_id="cid", client_secret="sec")
    assert exc.value.code == "amz_ads_token_exchange_failed"


def test_start_rejects_bad_client_pair_shape() -> None:
    store = N(store_code="01us", region="na", metadata_json={})

    class Db:
        def add(self, *_): ...

        def flush(self): ...

    with pytest.raises(AmzServiceError) as exc:
        ads_oauth.start(Db(), store=store, client_id="wrong", client_secret="amzn1.oa2-cs.v1.x", actor_user_id=1)
    assert exc.value.code == "amz_ads_client_pair_invalid"
