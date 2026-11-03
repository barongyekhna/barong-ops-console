"""Search Console 接入(10-30,看板第二期;11-03 改按「页」存)的纯逻辑:服务账号钥匙解析 + RS256 JWT、换 token、
每天两次请求(全站合计 + 按页)+ 28 天搜索词窗口、该拉哪几天/补历史隔 10 分钟一批、拉数落库与台账、按页按词合计、缺口门槛、看板分节;
钥匙类型注册/别名/校验;key_health 探针(假 transport)。unit,不连库(落库用假 db)、不出网。"""

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


def test_query_day_asks_for_site_totals_and_pages_and_the_window_asks_for_queries(keypair, monkeypatch: pytest.MonkeyPatch) -> None:
    """11-03:按天的搜索词被谷歌全部匿名,一天改问两样——全站合计(维度空)和按页;搜索词按 28 天一窗去要。"""
    pem, _ = keypair
    account = gsa.parse_service_account(_secret(pem))
    gsc._token_cache.clear()
    calls: list[httpx.Request] = []
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.url.path in ("/webmasters/v3/sites/sc-domain%3Abarongyekhna.com/searchAnalytics/query", "/webmasters/v3/sites/sc-domain:barongyekhna.com/searchAnalytics/query")  # httpx 会把 %3A 还原成冒号
        assert request.headers["authorization"] == "Bearer tok"
        body = json.loads(request.content)
        bodies.append(body)
        assert {k: v for k, v in body.items() if k not in ("startDate", "endDate", "dimensions")} == {"rowLimit": 5000, "type": "web", "dataState": "final"}
        if body["dimensions"] == []:
            return httpx.Response(200, json={"rows": [{"clicks": 2, "impressions": 15, "ctr": 0.1333, "position": 2.27}]})
        if body["dimensions"] == ["page"]:
            return httpx.Response(200, json={"rows": [{"keys": ["https://barongyekhna.com/"], "clicks": 2, "impressions": 9, "ctr": 0.222, "position": 3.0}, {"keys": ["https://barongyekhna.com/how-to-use-arctic-i/"], "clicks": 0, "impressions": 6, "ctr": 0.0, "position": 6.8}]})
        assert body["dimensions"] == ["query"]
        return httpx.Response(200, json={})  # 站小:谷歌一个词都不给,连 rows 都没有

    day = date(2026, 10, 27)
    got = gsc.query_day(account, day, site="sc-domain:barongyekhna.com", transport=httpx.MockTransport(handler))
    assert got["site"] == {"clicks": 2, "impressions": 15, "ctr": 0.1333, "position": 2.27}
    assert got["pages"] == [
        {"page": "https://barongyekhna.com/", "clicks": 2, "impressions": 9, "ctr": 0.222, "position": 3.0},
        {"page": "https://barongyekhna.com/how-to-use-arctic-i/", "clicks": 0, "impressions": 6, "ctr": 0.0, "position": 6.8},
    ]
    assert [(b["startDate"], b["endDate"], b["dimensions"]) for b in bodies] == [("2026-10-27", "2026-10-27", []), ("2026-10-27", "2026-10-27", ["page"])]
    assert gsc.query_window(account, day, site="sc-domain:barongyekhna.com", transport=httpx.MockTransport(handler)) == []
    assert (bodies[-1]["startDate"], bodies[-1]["endDate"]) == ("2026-09-30", "2026-10-27")  # 截止那天往回共 28 天
    assert sum(1 for c in calls if c.url.host == "oauth2.googleapis.com") == 1  # token 缓存住了
    with pytest.raises(gsc.GscError, match="searchAnalytics 403"):
        gsc.query(account, start=day, end=day, dimensions=["page"], site="sc-domain:barongyekhna.com", transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"error": "denied"})))
    gsc._token_cache.clear()


def test_page_label_is_the_last_path_segment_or_home() -> None:
    assert gsc.page_label("https://barongyekhna.com/") == "首页"
    assert gsc.page_label("https://barongyekhna.com/2026/01/16/10-common-mistakes-how-to-fix-them/") == "10-common-mistakes-how-to-fix-them"
    assert gsc.page_label("https://barongyekhna.com/product/lantern") == "lantern"


# ---------------------------------------------------------------- 节律 / 拉数 / 台账


def test_days_due_and_should_pull_follow_the_lag_backfill_and_backlog() -> None:
    now = datetime(2026, 10, 30, 16, 0, tzinfo=UTC)  # LA 10-30 09:00
    due = gsc.days_due(now, have=set(), lag=3, backfill=5)
    assert due == [date(2026, 10, 27) - timedelta(days=n) for n in range(5)]  # 最新在前
    assert gsc.days_due(now, have={date(2026, 10, 27), date(2026, 10, 25)}, lag=3, backfill=5) == [date(2026, 10, 26), date(2026, 10, 24), date(2026, 10, 23)]
    assert not gsc.should_pull(datetime(2026, 10, 30, 14, 30, tzinfo=UTC), last_attempt_at=None)  # LA 07:30,还没到 8 点
    assert gsc.should_pull(now, last_attempt_at=None)
    assert gsc.should_pull(now, last_attempt_at=now - timedelta(days=1))  # 昨天拉过,今天照拉
    earlier = now - timedelta(minutes=5)
    assert not gsc.should_pull(now, last_attempt_at=earlier) and not gsc.should_pull(now, last_attempt_at=earlier, more=True)  # 补历史也要隔 10 分钟
    assert gsc.should_pull(now, last_attempt_at=now - timedelta(minutes=10), more=True)
    assert not gsc.should_pull(now, last_attempt_at=now - timedelta(minutes=10), more=False)  # 补完了:一天一次
    full = {"configured": True, "pulled": 10, "failed": 0, "stopped": None, "remaining": 80}
    assert gsc.has_more(full)
    for change in ({"remaining": 0}, {"failed": 1}, {"stopped": "预算已用完"}, {"pulled": 0}, {"configured": False}):
        assert not gsc.has_more({**full, **change})  # 出错/台账停/没拉到:等明天,不 10 分钟一轮地撞


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
        return [d for d, m in self.marks.items() if m.status == "ok" and (m.fmt or 1) >= gsc.FMT]

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1


def test_pull_due_consumes_the_ledger_per_request_refunds_failures_and_stops_when_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    import r_system_v2.ra.quota_ledger as ql

    ledger: list[int] = []
    budget = {"left": 7}

    def consume(db, provider, *, amount=1):
        if budget["left"] < amount:
            raise ql.RAQuotaExhaustedError(provider, used=300, budget=300)
        budget["left"] -= amount
        ledger.append(amount)

    monkeypatch.setattr(ql, "try_consume", consume)
    monkeypatch.setattr(ql, "refund", lambda db, provider, *, amount=1: ledger.append(-amount))
    monkeypatch.setenv("SQH_GSC_LAG_DAYS", "3")
    monkeypatch.setenv("SQH_GSC_BACKFILL_DAYS", "10")
    db = FakeDb()
    old = gsc.SqhGscDay(day=date(2026, 10, 24), rows=0, status="ok", fmt=1)  # 旧口径拉过的天:不算,重拉
    db.marks[old.day] = old
    now = datetime(2026, 10, 30, 16, 0, tzinfo=UTC)
    windows: list[date] = []

    def fetch(day: date) -> dict[str, Any]:
        if day == date(2026, 10, 26):
            raise RuntimeError("boom")
        if day == date(2026, 10, 27):
            return {"site": {"clicks": 2, "impressions": 15, "ctr": 0.1333, "position": 2.3}, "pages": [{"page": "https://x/", "clicks": 2, "impressions": 9, "ctr": 0.22, "position": 3.0}]}
        return {"site": None, "pages": []}

    def fetch_window(end: date) -> list[dict[str, Any]]:
        windows.append(end)
        return []

    out = gsc.pull_due(db, now=now, fetch=fetch, fetch_window=fetch_window)
    assert out["configured"] and out["pulled"] == 2 and out["failed"] == 1 and out["rows"] == 1 and out["days"] == ["2026-10-27", "2026-10-25"]
    assert out["stopped"] and "预算已用完" in out["stopped"]
    assert ledger == [2, 2, -2, 2]  # 一天两次请求扣 2;失败那天退 2;第四天只剩 1 次额度,停
    assert windows == []  # 台账停了,词窗口不拉
    latest = db.marks[date(2026, 10, 27)]
    assert (latest.fmt, latest.clicks, latest.impressions, latest.rows, latest.window_rows) == (2, 2, 15, 1, None)  # 全站合计记在天的那一行
    assert db.marks[date(2026, 10, 26)].status == "failed" and "boom" in db.marks[date(2026, 10, 26)].error
    assert db.marks[date(2026, 10, 25)].rows == 0 and db.marks[date(2026, 10, 25)].status == "ok" and db.marks[date(2026, 10, 25)].impressions == 0  # 没展现的天也记,不重拉
    assert out["remaining"] == 8 and not gsc.has_more(out)
    pages = [r for r in db.rows if isinstance(r, gsc.SqhGscPage)]
    assert [(p.day, p.page, p.impressions) for p in pages] == [(date(2026, 10, 27), "https://x/", 9)]

    budget["left"] = 100
    ledger.clear()
    out = gsc.pull_due(db, now=now, fetch=fetch, fetch_window=fetch_window)
    assert out["pulled"] == 7 and out["failed"] == 1 and windows == [date(2026, 10, 27)]  # 最新那天的 28 天词窗口拉一次
    assert out["window"] == {"end": "2026-10-27", "rows": 0} and latest.window_rows == 0  # 0 = 拉了,谷歌一个词都没给
    assert ledger[-1] == 1 and old.fmt == 2  # 词窗口扣 1;旧口径那天重拉成新口径
    gsc.pull_due(db, now=now, fetch=fetch, fetch_window=fetch_window)
    assert windows == [date(2026, 10, 27)]  # 同一窗不重拉


def test_pull_due_without_a_key_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gsc, "credentials", lambda db: (_ for _ in ()).throw(gsc.GscNotConfigured("没有 Search Console 钥匙")))
    out = gsc.pull_due(FakeDb(), now=datetime(2026, 10, 30, 16, 0, tzinfo=UTC))
    assert out == {"configured": False, "reason": "没有 Search Console 钥匙"}


# ---------------------------------------------------------------- 聚合 / 缺口 / 分节


def _r(page: str, clicks: int, impressions: int, position: float, query: str = "") -> Any:
    return SimpleNamespace(query=query, page=page, clicks=clicks, impressions=impressions, ctr=clicks / impressions if impressions else 0, position=position)


def test_group_weights_position_by_impressions_and_gaps_apply_the_thresholds() -> None:
    pages = gsc.group([
        _r("https://x/lantern/", 4, 200, 9.0),
        _r("https://x/lantern/", 0, 100, 15.0),
        _r("https://x/battery/", 0, 150, 7.5),
        _r("https://x/blog/poles/", 1, 40, 31.0),
    ], "page")
    assert pages["https://x/lantern/"] == {"clicks": 4, "impressions": 300, "ctr": 0.0133, "position": 11.0}  # (9*200+15*100)/300
    assert gsc.total([_r("a", 4, 200, 9.0), _r("b", 0, 100, 15.0)]) == {"clicks": 4, "impressions": 300, "ctr": 0.0133, "position": 11.0}
    assert gsc.total([]) == {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}
    queries = gsc.group([
        _r("", 4, 300, 11.0, query="camping lantern"),
        _r("", 0, 150, 7.5, query="12v drill battery"),
        _r("", 0, 60, 24.0, query="portable shower pump"),
        _r("", 1, 40, 31.0, query="tent pole repair"),
        _r("", 0, 5, 50.0, query="rare phrase"),
    ], "query")
    prev = gsc.group([_r("", 2, 100, 12.0, query="camping lantern")], "query")
    g = gsc.gaps(pages, queries, prev, product_terms=["12V Drill Battery Pack", "Camping Shower Pump"])
    assert [x["page"] for x in g["quick_win_pages"]] == ["https://x/lantern/"]  # 排 11、展现 300;battery 排 7.5 已在前十
    assert [x["query"] for x in g["quick_wins"]] == ["camping lantern"]
    assert [x["page"] for x in g["low_ctr_pages"]] == ["https://x/battery/"]  # 展现≥100 且 ctr<1%;lantern 1.33% 不算
    assert {x["query"]: x["has_product"] for x in g["far_queries"]} == {"portable shower pump": True, "tent pole repair": False}  # 排 24/31;rare phrase 展现不够
    assert [x["query"] for x in g["new_queries"]] == ["12v drill battery", "portable shower pump", "tent pole repair"]  # 上一窗没有且展现≥10
    assert gsc.gaps(pages, queries, None)["new_queries"] == []  # 没有上一窗:不比,免得第一周全是「新词」
    assert gsc.gaps({}, {}, None) == {"quick_win_pages": [], "quick_wins": [], "low_ctr_pages": [], "far_queries": [], "new_queries": []}

    search = {
        "configured": True, "day_from": "2026-10-19", "day_to": "2026-10-25", "covered_days": 7, "last_day": "2026-10-25",
        "clicks": 5, "impressions": 555, "ctr": 0.009, "position": 14.2, "prev_clicks": 2, "prev_impressions": 100,
        "top_pages": [{"page": "https://x/lantern/", "label": "lantern", "clicks": 4, "impressions": 300}, {"page": "https://x/", "clicks": 1, "impressions": 20}],
        "top_queries": [{"query": "camping lantern", "clicks": 4, "impressions": 300}], "query_window": {"end": "2026-10-25", "days": 28, "rows": 5},
        "gap_window": {"from": "2026-09-28", "to": "2026-10-25", "impressions": 900}, "gaps": g,
    }
    sections = digest.search_sections(search, kind="week", prev_label="比上周")
    assert [s["heading"] for s in sections] == ["搜索(Search Console)", "搜索缺口"]
    rows_by = {r[0]: r for r in sections[0]["rows"]}
    assert rows_by["点击 / 展现"][1] == "5 / 555" and rows_by["点击 / 展现"][2] == "+150% 比上周"
    assert rows_by["页面(点击 / 展现)"][1] == "lantern 4/300、首页 1/20"
    assert rows_by["点击最多的词(近 28 天)"][1] == "camping lantern 4/300"
    labels = [r[0] for r in sections[1]["rows"]]
    assert labels == ["按哪段算", "差一步的页(排 8–20,展现够)", "差一步的词(排 8–20,展现够)", "有展现没点击的页", "有需求、我们有品但排得远", "有需求、我们没对应品/内容", "本期新出现的词"]
    assert sections[1]["rows"][0][1] == "近 28 天(2026-09-28~2026-10-25)全站展现 900 次"
    assert "喂内容台选题 / 选品池" in sections[1]["rows"][5][2]

    hidden = {**search, "top_queries": [], "queries_hidden": True, "gaps": gsc.gaps({}, {}, None), "gap_window": {"from": "2026-10-04", "to": "2026-10-31", "impressions": 40}}
    sections = digest.search_sections(hidden, kind="week", prev_label="比上周")
    assert {r[0]: r[1] for r in sections[0]["rows"]}["搜索词"].startswith("谷歌没给:近 28 天每个词搜的人都太少")  # 说清楚是谷歌藏了,不是没拉
    assert sections[1]["rows"] == [["这一期", "没有够门槛的缺口:近 28 天(2026-10-04~2026-10-31)全站展现 40 次;一页或一个词要 ≥50 次展现才看", None]]
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
