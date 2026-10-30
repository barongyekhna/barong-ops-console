"""Search Console 接入(10-30,看板第二期)的纯逻辑:服务账号钥匙解析 + RS256 JWT、换 token、该拉哪几天、拉数落库与台账、
按词按页聚合、缺口门槛、看板分节;钥匙类型注册/别名/校验;key_health 探针(假 transport)。unit,不连库(落库用假 db)、不出网。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.app.modules.agent_series.suqinghe import digest, gsc
from backend.app.services import google_service_account as gsa

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def keypair() -> tuple[str, Any]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_key_bytes(encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8, encryption_algorithm=serialization.NoEncryption()).decode() if hasattr(key, "private_key_bytes") else key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return pem, key.public_key()


def _secret(pem: str, **over: Any) -> str:
    payload = {"type": "service_account", "project_id": "barong-ops", "private_key_id": "k1", "private_key": pem, "client_email": "suqinghe-gsc@barong-ops.iam.gserviceaccount.com", "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token"}
    payload.update(over)
    return json.dumps(payload)


# ---------------------------------------------------------------- 钥匙 + JWT + token


def test_service_account_parse_and_rs256_assertion(keypair) -> None:
    pem, public = keypair
    account = gsa.parse_service_account(_secret(pem))
    assert account.client_email.endswith("iam.gserviceaccount.com") and account.project_id == "barong-ops"
    assertion = gsa.build_assertion(account, scope=gsc.SCOPE, now=1_800_000_000)
    header, claims, signature = assertion.split(".")
    body = gsa.decode_claims(assertion)
    assert body == {"iss": account.client_email, "scope": gsc.SCOPE, "aud": "https://oauth2.googleapis.com/token", "iat": 1_800_000_000, "exp": 1_800_003_600}
    import base64

    sig = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    public.verify(sig, f"{header}.{claims}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())  # 真能验签
    # 私钥里 \\n 被转义过(控制台里粘的 JSON 常这样)也认
    assert gsa.parse_service_account(_secret(pem.replace("\n", "\\n"))).private_key_pem == pem
    for bad, reason in (("not json", "json_invalid"), (json.dumps({"type": "service_account"}), "json_missing_fields"), (_secret(pem, type="authorized_user"), "not_service_account"), (_secret(pem, private_key="nope"), "private_key_invalid")):
        with pytest.raises(gsa.ServiceAccountError, match=reason):
            gsa.parse_service_account(bad)


def test_fetch_access_token_posts_a_jwt_bearer_grant(keypair) -> None:
    pem, _ = keypair
    account = gsa.parse_service_account(_secret(pem))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = dict(x.split("=", 1) for x in request.content.decode().split("&"))
        assert body["grant_type"].startswith("urn%3Aietf") and body["assertion"].count(".") == 2
        return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3599, "token_type": "Bearer"})

    token, ttl = gsa.fetch_access_token(account, scope=gsc.SCOPE, transport=httpx.MockTransport(handler))
    assert token == "tok-1" and ttl == 3599 and seen[0].url.host == "oauth2.googleapis.com"
    with pytest.raises(gsa.ServiceAccountError, match="token_rejected:401"):
        gsa.fetch_access_token(account, scope=gsc.SCOPE, transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "invalid_grant", "error_description": "Invalid JWT"})))


def test_query_day_calls_search_analytics_with_the_site_encoded(keypair, monkeypatch: pytest.MonkeyPatch) -> None:
    pem, _ = keypair
    account = gsa.parse_service_account(_secret(pem))
    gsc._token_cache.clear()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.url.path in ("/webmasters/v3/sites/sc-domain%3Abarongyekhna.com/searchAnalytics/query", "/webmasters/v3/sites/sc-domain:barongyekhna.com/searchAnalytics/query")  # httpx 会把 %3A 还原成冒号
        assert request.headers["authorization"] == "Bearer tok"
        body = json.loads(request.content)
        assert body["startDate"] == body["endDate"] and body["startDate"] in ("2026-10-27", "2026-10-26")
        assert {k: v for k, v in body.items() if k not in ("startDate", "endDate")} == {"dimensions": ["query", "page"], "rowLimit": 5000, "type": "web", "dataState": "final"}
        return httpx.Response(200, json={"rows": [{"keys": ["camping lantern", "https://barongyekhna.com/product/lantern/"], "clicks": 3, "impressions": 120, "ctr": 0.025, "position": 9.4}]})

    rows = gsc.query_day(account, date(2026, 10, 27), site="sc-domain:barongyekhna.com", transport=httpx.MockTransport(handler))
    assert rows == [{"query": "camping lantern", "page": "https://barongyekhna.com/product/lantern/", "clicks": 3, "impressions": 120, "ctr": 0.025, "position": 9.4}]
    gsc.query_day(account, date(2026, 10, 26), site="sc-domain:barongyekhna.com", transport=httpx.MockTransport(handler))
    assert sum(1 for c in calls if c.url.host == "oauth2.googleapis.com") == 1  # token 缓存住了
    gsc._token_cache.clear()


# ---------------------------------------------------------------- 节律 / 拉数 / 台账


def test_days_due_and_should_pull_follow_the_lag_and_backfill() -> None:
    now = datetime(2026, 10, 30, 16, 0, tzinfo=UTC)  # LA 10-30 09:00
    due = gsc.days_due(now, have=set(), lag=3, backfill=5)
    assert due == [date(2026, 10, 27) - timedelta(days=n) for n in range(5)]  # 最新在前
    assert gsc.days_due(now, have={date(2026, 10, 27), date(2026, 10, 25)}, lag=3, backfill=5) == [date(2026, 10, 26), date(2026, 10, 24), date(2026, 10, 23)]
    assert not gsc.should_pull(datetime(2026, 10, 30, 14, 30, tzinfo=UTC), last_attempt_day=None)  # LA 07:30,还没到 8 点
    assert gsc.should_pull(now, last_attempt_day=None) and not gsc.should_pull(now, last_attempt_day=date(2026, 10, 30))


class FakeDb:
    def __init__(self) -> None:
        self.rows: list[Any] = []
        self.marks: dict[date, Any] = {}
        self.commits = 0

    def add(self, row: Any) -> None:
        if isinstance(row, gsc.SqhGscDay):
            self.marks[row.day] = row
        else:
            self.rows.append(row)

    def get(self, model: Any, key: Any) -> Any:
        return self.marks.get(key) if model is gsc.SqhGscDay else None

    def execute(self, *a: Any, **k: Any) -> None:
        pass

    def scalars(self, *a: Any, **k: Any) -> list[Any]:
        return [d for d, m in self.marks.items() if m.status == "ok"]

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1


def test_pull_due_consumes_the_ledger_per_day_refunds_failures_and_stops_when_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    import r_system_v2.ra.quota_ledger as ql

    ledger: list[str] = []
    budget = {"left": 3}

    def consume(db, provider, *, amount=1):
        if budget["left"] <= 0:
            raise ql.RAQuotaExhaustedError(provider, used=30, budget=30)
        budget["left"] -= 1
        ledger.append("+")

    monkeypatch.setattr(ql, "try_consume", consume)
    monkeypatch.setattr(ql, "refund", lambda db, provider, *, amount=1: ledger.append("-"))
    monkeypatch.setenv("SQH_GSC_LAG_DAYS", "3")
    monkeypatch.setenv("SQH_GSC_BACKFILL_DAYS", "10")
    db = FakeDb()
    now = datetime(2026, 10, 30, 16, 0, tzinfo=UTC)

    def fetch(day: date) -> list[dict[str, Any]]:
        if day == date(2026, 10, 26):
            raise RuntimeError("boom")
        return [{"query": "q", "page": "p", "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 5.0}] if day == date(2026, 10, 27) else []

    out = gsc.pull_due(db, now=now, fetch=fetch)
    assert out["configured"] and out["pulled"] == 2 and out["failed"] == 1 and out["rows"] == 1 and out["days"] == ["2026-10-27", "2026-10-25"]
    assert out["stopped"] and "预算已用完" in out["stopped"]
    assert ledger == ["+", "+", "-", "+"]  # 失败那天退了一次
    assert db.marks[date(2026, 10, 26)].status == "failed" and "boom" in db.marks[date(2026, 10, 26)].error
    assert db.marks[date(2026, 10, 25)].rows == 0 and db.marks[date(2026, 10, 25)].status == "ok"  # 没展现的天也记,不重拉


def test_pull_due_without_a_key_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gsc, "credentials", lambda db: (_ for _ in ()).throw(gsc.GscNotConfigured("没有 Search Console 钥匙")))
    out = gsc.pull_due(FakeDb(), now=datetime(2026, 10, 30, 16, 0, tzinfo=UTC))
    assert out == {"configured": False, "reason": "没有 Search Console 钥匙"}


# ---------------------------------------------------------------- 聚合 / 缺口 / 分节


def _r(query: str, page: str, clicks: int, impressions: int, position: float) -> Any:
    return SimpleNamespace(query=query, page=page, clicks=clicks, impressions=impressions, ctr=clicks / impressions if impressions else 0, position=position)


def test_aggregate_weights_position_by_impressions_and_gaps_apply_the_thresholds() -> None:
    rows = [
        _r("camping lantern", "https://x/lantern/", 4, 200, 9.0),
        _r("camping lantern", "https://x/blog/lanterns/", 0, 100, 15.0),
        _r("12v drill battery", "https://x/battery/", 0, 150, 7.5),
        _r("portable shower pump", "https://x/shower/", 0, 60, 24.0),
        _r("tent pole repair", "https://x/blog/poles/", 1, 40, 31.0),
        _r("rare phrase", "https://x/a/", 0, 5, 50.0),
    ]
    cur = gsc.aggregate(rows)
    assert cur["clicks"] == 5 and cur["impressions"] == 555
    assert cur["queries"]["camping lantern"] == {"clicks": 4, "impressions": 300, "ctr": 0.0133, "position": 11.0}  # (9*200+15*100)/300
    assert cur["pages"]["https://x/battery/"]["ctr"] == 0.0
    prev = gsc.aggregate([_r("camping lantern", "https://x/lantern/", 2, 100, 12.0)])
    g = gsc.gaps(cur, prev, product_terms=["12V Drill Battery Pack", "Camping Shower Pump"])
    assert [x["query"] for x in g["quick_wins"]] == ["camping lantern"]  # 排 11、展现 300
    assert [x["page"] for x in g["low_ctr_pages"]] == ["https://x/battery/", "https://x/blog/lanterns/"]  # 展现≥100 且 ctr<1%
    far = {x["query"]: x["has_product"] for x in g["far_queries"]}
    assert far == {"portable shower pump": True, "tent pole repair": False}  # 排 24/31,展现 60/40;rare phrase 展现不够
    assert [x["query"] for x in g["new_queries"]] == ["12v drill battery", "portable shower pump", "tent pole repair"]  # 上期没有且展现≥10
    search = {"configured": True, "day_from": "2026-10-19", "day_to": "2026-10-25", "covered_days": 7, "last_day": "2026-10-25", "clicks": 5, "impressions": 555, "ctr": 0.009, "position": 14.2, "prev_clicks": 2, "prev_impressions": 100, "top_queries": [{"query": "camping lantern", "clicks": 4}], "gaps": g}
    sections = digest.search_sections(search, kind="week", prev_label="比上周")
    assert [s["heading"] for s in sections] == ["搜索(Search Console)", "搜索缺口"]
    rows_by = {r[0]: r for r in sections[0]["rows"]}
    assert rows_by["点击 / 展现"][1] == "5 / 555" and rows_by["点击 / 展现"][2] == "+150% 比上周"
    labels = [r[0] for r in sections[1]["rows"]]
    assert labels == ["差一步的词(排 8–20,展现够)", "有展现没点击的页", "有需求、我们有品但排得远", "有需求、我们没对应品/内容", "本期新出现的词"]
    assert "喂内容台选题 / 选品池" in sections[1]["rows"][3][2]
    assert digest.search_sections({"configured": False, "reason": "x"}, kind="day", prev_label="")[0]["rows"][0][1].startswith("还没接")
    assert digest.search_sections({"error": "读不到"}, kind="day", prev_label="")[0]["rows"] == [["状态", "读不到", None]]


def test_gsc_rules_only_fire_when_configured() -> None:
    base = {"kind": "week", "period_key": "2026-W44", "traffic": {"error": "读不到"}, "orders": {"error": "读不到"}, "site": {"error": "读不到"}, "content": {"error": "读不到"}}
    assert digest.rules({**base, "search": {"configured": False}}) == []
    stale = digest.rules({**base, "search": {"configured": True, "last_day": None}})
    assert [f["code"] for f in stale] == ["gsc_pull_stale"]
    drop = digest.rules({**base, "search": {"configured": True, "last_day": "2026-11-01", "clicks": 20, "prev_clicks": 80}})
    assert [(f["code"], f["severity"]) for f in drop] == [("gsc_clicks_drop", "warn")]
    assert digest.rules({**base, "search": {"configured": True, "last_day": "2026-11-01", "clicks": 20, "prev_clicks": 30}}) == []  # 基数小,静默
    day = {"kind": "day", "period_key": "2026-10-30", "search": {"configured": True, "last_day": "2026-10-20", "clicks": 1, "prev_clicks": 1}}
    assert [f["code"] for f in digest.rules(day)] == ["gsc_pull_stale"]  # 数停在 10 天前(lag 3 + 3 容忍)
    assert digest.rules({**day, "search": {**day["search"], "last_day": "2026-10-26"}}) == []


# ---------------------------------------------------------------- 钥匙类型 + 探针


def test_key_type_is_registered_validated_and_probed(keypair, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.core.key_registry import key_type_definition, list_key_type_definitions, normalize_key_type
    from backend.app.modules.key_health.probes import ProbeTarget, adapter_for_target, probe_target
    from backend.app.services.api_key_orchestration import validate_api_key_value

    pem, _ = keypair
    assert "google_search_console" in {d["type"] for d in list_key_type_definitions()}
    definition = key_type_definition("google_search_console")
    assert definition["auth_type"] == "oauth_json" and definition["default_alias"] == "gsc" and definition["module_ids"] == ["k.product_knowledge"]
    assert normalize_key_type("gsc") == "google_search_console" and normalize_key_type("search-console") == "google_search_console"
    assert validate_api_key_value(key_type="gsc", key_value=_secret(pem))["valid"] is True
    assert validate_api_key_value(key_type="google_search_console", key_value="{}")["reason"] == "json_missing_fields"

    def target(secret: str) -> ProbeTarget:
        return ProbeTarget(key_id="key_" + "0" * 32, org_id="org_" + "0" * 32, name="gsc", url="https://searchconsole.googleapis.com", key_hash_prefix="abcdef123456", key_type="google_search_console", aliases=("gsc",), secret_value=secret)

    assert adapter_for_target(target(_secret(pem))) == "google_search_console"
    monkeypatch.setenv("SQH_GSC_SITE", "sc-domain:barongyekhna.com")
    sites = {"siteEntry": [{"siteUrl": "sc-domain:barongyekhna.com", "permissionLevel": "siteFullUser"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ephemeral", "expires_in": 3600})
        assert request.url.path == "/webmasters/v3/sites" and request.headers["authorization"] == "Bearer ephemeral"
        return httpx.Response(200, json=sites)

    result = probe_target(target(_secret(pem)), enforce_public_network=False, transport=httpx.MockTransport(handler))
    assert result.status == "healthy" and result.reason_code == "site_granted" and "ephemeral" not in repr(result)
    sites["siteEntry"] = [{"siteUrl": "https://other.example/", "permissionLevel": "siteOwner"}]
    result = probe_target(target(_secret(pem)), enforce_public_network=False, transport=httpx.MockTransport(handler))
    assert result.status == "invalid" and result.reason_code == "site_not_granted"  # 老板还没在 Search Console 加它
    result = probe_target(target("{}"), enforce_public_network=False, transport=httpx.MockTransport(handler))
    assert result.status == "malformed" and result.reason_code == "json_missing_fields"
    rejected = probe_target(target(_secret(pem)), enforce_public_network=False, transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "invalid_grant"})))
    assert rejected.status == "invalid" and rejected.reason_code == "service_account_token_rejected"
