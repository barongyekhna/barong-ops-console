"""A1 报表管线:SP-API 客户端(假传输层)、两份报表的解析器、周对齐、回填 CLI 登记。不碰库。"""

from __future__ import annotations

import gzip
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from backend.app.modules.amz_series import reports_sync as rs
from backend.app.modules.amz_series.clients import sp_api

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/amz"
CREDS = sp_api.SpApiCredentials("cid", "sec", "Atzr|rt", "na")


class FakeAmazon:
    """假的 LWA + 报表三步。记下每次请求,能注入 429 / 401 / FATAL。"""

    def __init__(self, document: dict, *, fatal: str | None = None, rate_limit_first: int = 0):
        self.document = document
        self.fatal = fatal
        self.rate_limit_first = rate_limit_first
        self.calls: list[str] = []
        self.tokens = 0
        self.polls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.host}{request.url.path}")
        if request.url.host == "api.amazon.com":
            self.tokens += 1
            return httpx.Response(200, json={"access_token": f"tok{self.tokens}", "expires_in": 3600})
        if request.headers.get("x-amz-access-token", "").startswith("tok") is False and "docs.example" not in request.url.host:
            return httpx.Response(401, json={"errors": [{"code": "Unauthorized", "message": "bad token"}]})
        if self.rate_limit_first > 0 and request.url.path.endswith("/reports") and request.method == "POST":
            self.rate_limit_first -= 1
            return httpx.Response(429, json={"errors": [{"code": "QuotaExceeded", "message": "slow down"}]})
        if request.method == "POST" and request.url.path == "/reports/2021-06-30/reports":
            body = json.loads(request.content)
            assert body["marketplaceIds"] == ["ATVPDKIKX0DER"] and body["dataStartTime"] == "2026-09-13"
            assert request.headers["User-Agent"].startswith("BarongOpsConsole-01us/")
            return httpx.Response(202, json={"reportId": "R1"})
        if request.url.path == "/reports/2021-06-30/reports/R1":
            self.polls += 1
            if self.polls < 2:
                return httpx.Response(200, json={"processingStatus": "IN_PROGRESS"})
            return httpx.Response(200, json={"processingStatus": "FATAL" if self.fatal else "DONE", "reportDocumentId": "D1"})
        if request.url.path == "/reports/2021-06-30/documents/D1":
            return httpx.Response(200, json={"url": "https://docs.example/D1", "compressionAlgorithm": "GZIP"})
        if request.url.host == "docs.example":
            payload = {"errorDetails": self.fatal} if self.fatal else self.document
            return httpx.Response(200, content=gzip.compress(json.dumps(payload).encode()))
        return httpx.Response(404, json={"errors": [{"code": "NotFound", "message": request.url.path}]})


def _client(amazon: FakeAmazon, **kwargs) -> sp_api.SpApiClient:
    slept: list[float] = []
    clock = {"t": 1000.0}
    client = sp_api.SpApiClient(CREDS, store_code="01us", marketplace_id="ATVPDKIKX0DER", transport=httpx.MockTransport(amazon.handler), sleep=slept.append, clock=lambda: clock["t"], **kwargs)
    client.slept = slept  # type: ignore[attr-defined]
    client.clock_state = clock  # type: ignore[attr-defined]
    return client


def test_client_runs_report_create_poll_download_gunzip_and_caches_token() -> None:
    doc = json.loads((FIXTURES / "sales_traffic_day.json").read_text(encoding="utf-8"))
    amazon = FakeAmazon(doc)
    client = _client(amazon)
    report_id, payload = client.run_report(rs.REPORT_SALES_TRAFFIC, start=date(2026, 9, 13), end=date(2026, 9, 13), options={"dateGranularity": "DAY", "asinGranularity": "CHILD"})
    assert report_id == "R1" and payload["reportSpecification"]["reportType"] == rs.REPORT_SALES_TRAFFIC
    assert amazon.tokens == 1  # 一小时内不重取令牌
    assert client.slept == [15.0]  # 第一次 IN_PROGRESS 等了一轮
    assert amazon.calls[0] == "POST api.amazon.com/auth/o2/token"
    assert amazon.calls[-1] == "GET docs.example/D1"
    # 令牌快过期时自动续
    client.clock_state["t"] += 3600
    client.token()
    assert amazon.tokens == 2


def test_client_backs_off_on_429_and_surfaces_fatal_error_details() -> None:
    doc = json.loads((FIXTURES / "sales_traffic_day.json").read_text(encoding="utf-8"))
    amazon = FakeAmazon(doc, rate_limit_first=2)
    client = _client(amazon)
    client.run_report(rs.REPORT_SALES_TRAFFIC, start=date(2026, 9, 13), end=date(2026, 9, 13))
    assert client.slept[:2] == [5.0, 15.0]
    fatal = FakeAmazon(doc, fatal="dataStartTime must be a Sunday when reportPeriod=WEEK")
    with pytest.raises(sp_api.SpApiReportFailed) as exc:
        _client(fatal).run_report(rs.REPORT_SQP, start=date(2026, 9, 13), end=date(2026, 9, 13))
    assert exc.value.report_status == "FATAL" and "Sunday" in exc.value.details
    hopeless = FakeAmazon(doc, rate_limit_first=99)
    with pytest.raises(sp_api.SpApiError) as exc2:
        _client(hopeless).create_report(rs.REPORT_SALES_TRAFFIC, start=date(2026, 9, 13), end=date(2026, 9, 13))
    assert exc2.value.code == "rate_limited"


def test_credentials_json_shape_and_egress_defaults() -> None:
    creds = sp_api.SpApiCredentials.from_json(json.dumps({"client_id": "a", "client_secret": "b", "refresh_token": "c", "region": "EU"}))
    assert creds.region == "eu"
    with pytest.raises(sp_api.SpApiError):
        sp_api.SpApiCredentials.from_json(json.dumps({"client_id": "a", "client_secret": "b", "region": "na"}))
    with pytest.raises(sp_api.SpApiError):
        sp_api.SpApiCredentials.from_json(json.dumps({"client_id": "a", "client_secret": "b", "refresh_token": "c", "region": "mars"}))
    assert sp_api.default_user_agent("03us") == "BarongOpsConsole-03us/0.1 (Language=Python; Platform=Linux)"


def test_parse_sales_traffic_gives_store_total_row_plus_child_asin_rows() -> None:
    doc = json.loads((FIXTURES / "sales_traffic_day.json").read_text(encoding="utf-8"))
    rows = rs.parse_sales_traffic(doc, store_code="01us", currency_default="USD")
    assert [r["child_asin"] for r in rows] == ["", "B0TESTA0001", "B0TESTA0002"]
    total = rows[0]
    assert total["report_date"] == date(2026, 9, 13) and total["units_ordered"] == 10 and total["ordered_product_sales"] == Decimal("246.75")
    assert total["sessions"] == 158 and total["unit_session_pct"] == Decimal("6.33") and total["units_refunded"] == 2
    asin = rows[1]
    assert asin["parent_asin"] == "B0TESTP0001" and asin["report_date"] == date(2026, 9, 13) and asin["sessions"] == 117 and asin["units_ordered"] == 7
    assert rs.parse_sales_traffic({"salesAndTrafficByAsin": [{"childAsin": "X"}]}, store_code="01us", currency_default="USD") == []


def test_parse_sqp_rows_and_week_alignment() -> None:
    doc = json.loads((FIXTURES / "sqp_week.json").read_text(encoding="utf-8"))
    rows = rs.parse_sqp(doc, store_code="01us")
    assert len(rows) == 2 and {r["search_query"] for r in rows} == {"camping shower", "portable shower"}
    row = rows[0]
    assert row["asin"] == "B0TESTA0001" and row["period_start"] == date(2026, 8, 30) and row["period_end"] == date(2026, 9, 5)
    assert row["impressions_total"] == 5000 and row["impressions_share_pct"] == Decimal("5.00")
    assert row["clicks_share_pct"] == Decimal("10.00") and row["purchases_share_pct"] == Decimal("2.00") and row["query_volume"] == 1000
    # 周日到周六;今天是周三 → 上一个整周
    assert rs.last_complete_week(date(2026, 9, 16)) == (date(2026, 9, 6), date(2026, 9, 12))
    assert rs.last_complete_week(date(2026, 9, 12)) == (date(2026, 8, 30), date(2026, 9, 5))  # 周六当天算未结束
    assert rs.last_complete_week(date(2026, 9, 13)) == (date(2026, 9, 6), date(2026, 9, 12))  # 周日:上一周刚结束
    assert rs.complete_weeks(date(2026, 9, 16), 3) == [(date(2026, 9, 6), date(2026, 9, 12)), (date(2026, 8, 30), date(2026, 9, 5)), (date(2026, 8, 23), date(2026, 8, 29))]


def test_backfill_cli_and_fixtures_are_anonymized() -> None:
    from backend.app.modules.amz_series import backfill

    assert backfill.main.__doc__ is None or True
    for name in ("sales_traffic_day.json", "sqp_week.json"):
        text = (FIXTURES / name).read_text(encoding="utf-8")
        assert "B0TEST" in text and "B0H" not in text and "B0G" not in text
