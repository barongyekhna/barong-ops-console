"""2026-09-07 R-A 图搜通道 / 分销包动态额度 / 重试风暴 / key-health 判定 / R-W 去翻译。

背景：跨境图搜远端套餐耗尽（gw.NoUsageLeftError）三天没人发现——本地台账看不见
远端余量、失败产品不落状态被巡航反复重选、key-health 零消耗探针假绿。这里把每
个断点都钉一条测试。
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.app.modules.key_health import service as key_health_service
from backend.app.modules.key_health.probes import ProbeTarget, probe_target
from r_system_v2.ra import key_health_bridge, quota_ledger
from r_system_v2.ra.auto_profit import _ra_profit_not_processed_sql
from r_system_v2.ra.job_queue import _mark_rw_profit_status, classify_product_error
from r_system_v2.ra.quota_ledger import (
    PROVIDER_1688_CPS_IMAGE_SEARCH,
    PROVIDER_1688_IMAGE_SEARCH,
    PROVIDER_F_1688_IMAGE_SEARCH,
    RAQuotaExhaustedError,
    cps_package_summary,
    daily_budget,
    ensure_quota_schema,
    image_search_channels,
    mark_exhausted_today,
    try_consume,
    usage_today,
)
from r_system_v2.ra.supplier_api import RASupplierApiError, is_no_usage_left
from r_system_v2.ra.supplier_discovery import _run_image_search_waterfall
from r_system_v2.ra.supplier_keyword_skill import (
    is_deepseek_credits_exhausted,
    sanitize_keyword_profile,
)
from r_system_v2.rw.core.keepa_buffer_queue import KeepaBufferQueue
from r_system_v2.rw.core.models import IngestionRecord
from r_system_v2.rw.providers.keepa_provider import KeepaProvider
from r_system_v2.rw.storage.batch_writer import (
    InMemoryBatchWriter,
    SQLAlchemyBatchWriter,
    products_rw,
)
from r_system_v2.rw.workers.keepa_worker import KeepaWorker

pytestmark = pytest.mark.unit

NO_USAGE_LEFT = (
    '1688 图搜请求失败：HTTP 400 {"error_message":"SLA bill has no usage left",'
    '"exception":"SLA bill has no usage left","error_code":"gw.NoUsageLeftError"}'
)


@pytest.fixture
def ledger_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as session:
        ensure_quota_schema(session)
        session.commit()
        yield session


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quota_ledger, "_cps_budget_cache", {})
    key_health_bridge.reset_throttle()
    for name in (
        "RA_1688_IMAGE_CHANNELS",
        "RA_1688_IMAGE_SEARCH_DAILY_BUDGET",
        "RA_1688_CPS_IMAGE_SEARCH_DAILY_BUDGET",
        "RA_1688_CPS_PACKAGE_TOTAL",
        "RA_1688_CPS_PACKAGE_EXPIRES_ON",
        "RA_1688_CPS_PACKAGE_USED_OFFSET",
        "RA_1688_CPS_BUDGET_MARGIN",
        "RA_FAILED_RETRY_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def bridge_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, object]]]:
    calls: dict[str, list[dict[str, object]]] = {"incident": [], "recovered": []}

    def _incident(**kwargs: object) -> bool:
        calls["incident"].append(dict(kwargs))
        return True

    def _recovered(**kwargs: object) -> bool:
        calls["recovered"].append(dict(kwargs))
        return True

    monkeypatch.setattr(key_health_bridge, "report_incident", _incident)
    monkeypatch.setattr(key_health_bridge, "report_recovered", _recovered)
    return calls


# ------------------------------------------------------------ A. 通道与识别
def test_image_search_channels_default_is_cps_only(monkeypatch: pytest.MonkeyPatch) -> None:
    assert image_search_channels() == ("cps",)
    monkeypatch.setenv("RA_1688_IMAGE_CHANNELS", " cross , cps, bogus, cross")
    assert image_search_channels() == ("cross", "cps")
    monkeypatch.setenv("RA_1688_IMAGE_CHANNELS", "bogus")
    assert image_search_channels() == ("cps",)


def test_no_usage_left_and_credits_exhausted_classifiers() -> None:
    assert is_no_usage_left(RASupplierApiError(NO_USAGE_LEFT))
    assert is_no_usage_left("SLA bill has No Usage Left")
    assert not is_no_usage_left("1688 图搜网络失败：timed out")
    assert is_deepseek_credits_exhausted(
        'DeepSeek 关键词抽取失败：HTTP 402 {"error":{"message":"Insufficient Balance"}}'
    )
    assert not is_deepseek_credits_exhausted("DeepSeek 关键词抽取失败：HTTP 500 boom")


def test_usage_today_hides_channels_not_in_use(ledger_db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = usage_today(ledger_db)
    assert PROVIDER_1688_IMAGE_SEARCH not in payload
    assert PROVIDER_1688_CPS_IMAGE_SEARCH in payload
    assert "package" in payload[PROVIDER_1688_CPS_IMAGE_SEARCH]
    monkeypatch.setenv("RA_1688_IMAGE_CHANNELS", "cps,cross")
    assert PROVIDER_1688_IMAGE_SEARCH in usage_today(ledger_db)


# ------------------------------------------------------ B. 分销包动态日额度
def test_cps_daily_budget_derives_from_package_remaining(
    ledger_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    today = datetime.now(UTC).date()
    monkeypatch.setenv("RA_1688_CPS_PACKAGE_TOTAL", "1000")
    monkeypatch.setenv("RA_1688_CPS_PACKAGE_EXPIRES_ON", (today + timedelta(days=9)).isoformat())
    monkeypatch.setenv("RA_1688_CPS_BUDGET_MARGIN", "0.5")
    yesterday = (today - timedelta(days=1)).isoformat()
    ledger_db.execute(
        text("INSERT INTO ra_provider_quota_usage (provider, day, used) VALUES (:p, :d, :u)"),
        [
            {"p": PROVIDER_1688_CPS_IMAGE_SEARCH, "d": yesterday, "u": 100},
            {"p": PROVIDER_F_1688_IMAGE_SEARCH, "d": yesterday, "u": 50},
            # 今天的用量不影响今天的额度（否则额度会随用随缩）。
            {"p": PROVIDER_1688_CPS_IMAGE_SEARCH, "d": today.isoformat(), "u": 999},
        ],
    )
    ledger_db.commit()

    summary = cps_package_summary(ledger_db)
    assert summary["ledger_used"] == 150
    assert summary["remaining"] == 850
    assert summary["days_left"] == 10
    # 850 / 10 * 0.5 = 42.5 → 42
    assert summary["daily_budget"] == 42
    assert daily_budget(PROVIDER_1688_CPS_IMAGE_SEARCH, ledger_db) == 42

    # 显式 env 压住动态值。
    monkeypatch.setenv("RA_1688_CPS_IMAGE_SEARCH_DAILY_BUDGET", "7")
    assert daily_budget(PROVIDER_1688_CPS_IMAGE_SEARCH, ledger_db) == 7


def test_cps_daily_budget_after_expiry_is_one_not_unlimited(
    ledger_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RA_1688_CPS_PACKAGE_EXPIRES_ON", "2020-01-01")
    assert cps_package_summary(ledger_db)["daily_budget"] == 1
    monkeypatch.setenv("RA_1688_CPS_PACKAGE_EXPIRES_ON", "2999-01-01")
    monkeypatch.setenv("RA_1688_CPS_PACKAGE_TOTAL", "10")
    monkeypatch.setenv("RA_1688_CPS_PACKAGE_USED_OFFSET", "10")
    assert cps_package_summary(ledger_db)["daily_budget"] == 1


def test_production_like_numbers_land_near_three_thousand_three_hundred(
    ledger_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 2026-09-07 实盘：台账已用 16777，剩 132 天（含当天）。
    monkeypatch.setenv("RA_1688_CPS_PACKAGE_EXPIRES_ON", "2027-01-17")
    fixed_today = datetime(2026, 9, 7, tzinfo=UTC).date()
    ledger_db.execute(
        text("INSERT INTO ra_provider_quota_usage (provider, day, used) VALUES (:p, :d, :u)"),
        [
            {"p": PROVIDER_1688_CPS_IMAGE_SEARCH, "d": "2026-07-20", "u": 16148},
            {"p": PROVIDER_F_1688_IMAGE_SEARCH, "d": "2026-08-01", "u": 629},
        ],
    )
    ledger_db.commit()
    summary = cps_package_summary(ledger_db, today=fixed_today)
    assert summary["days_left"] == 133
    assert 3200 <= summary["daily_budget"] <= 3400


# ---------------------------------------------------- A. 台账记满 + 通道瀑布
def test_mark_exhausted_today_blocks_further_consumption(
    ledger_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RA_1688_IMAGE_SEARCH_DAILY_BUDGET", "5")
    try_consume(ledger_db, PROVIDER_1688_IMAGE_SEARCH)
    assert mark_exhausted_today(ledger_db, PROVIDER_1688_IMAGE_SEARCH) == 5
    with pytest.raises(RAQuotaExhaustedError) as excinfo:
        try_consume(ledger_db, PROVIDER_1688_IMAGE_SEARCH)
    assert excinfo.value.used == 5


class _WaterfallProvider:
    provider_name = "alibaba_1688_official"

    def __init__(self, *, failing: dict[str, Exception]) -> None:
        self.failing = failing
        self.calls: list[str] = []

    def search_offers(self, *, product, keyword_profile, limit, image_channel="cross"):
        self.calls.append(image_channel)
        if image_channel in self.failing:
            raise self.failing[image_channel]
        return [{"channel": image_channel}]


def test_waterfall_switches_to_cps_when_cross_has_no_usage_left(
    ledger_db: Session, monkeypatch: pytest.MonkeyPatch, bridge_calls
) -> None:
    monkeypatch.setenv("RA_1688_IMAGE_CHANNELS", "cross,cps")
    monkeypatch.setenv("RA_1688_IMAGE_SEARCH_DAILY_BUDGET", "330")
    monkeypatch.setenv("RA_1688_CPS_IMAGE_SEARCH_DAILY_BUDGET", "100")
    provider = _WaterfallProvider(failing={"cross": RASupplierApiError(NO_USAGE_LEFT)})

    offers, channel = _run_image_search_waterfall(
        ledger_db,
        provider=provider,
        product={"asin": "B0TEST0001"},
        keyword_profile={},
        limit=5,
        is_real_provider=True,
    )

    assert channel == "cps"
    assert offers == [{"channel": "cps"}]
    assert provider.calls == ["cross", "cps"]
    usage = usage_today(ledger_db)
    # 跨境当天被记满（远端没额度），分销记了 1 次。
    assert usage[PROVIDER_1688_IMAGE_SEARCH]["used"] == 330
    assert usage[PROVIDER_1688_CPS_IMAGE_SEARCH]["used"] == 1
    assert bridge_calls["incident"] and bridge_calls["incident"][0]["key_type"] == "alibaba1688"
    assert bridge_calls["incident"][0]["reason_code"] == key_health_bridge.REASON_QUOTA_EXHAUSTED
    assert bridge_calls["recovered"] and bridge_calls["recovered"][0]["key_type"] == "alibaba1688"

    # 同一天再来：跨境本地台账已满，直接走 cps，不再打远端。
    provider.calls.clear()
    _run_image_search_waterfall(
        ledger_db,
        provider=provider,
        product={"asin": "B0TEST0002"},
        keyword_profile={},
        limit=5,
        is_real_provider=True,
    )
    assert provider.calls == ["cps"]


def test_waterfall_raises_quota_error_when_every_channel_is_gone(
    ledger_db: Session, monkeypatch: pytest.MonkeyPatch, bridge_calls
) -> None:
    monkeypatch.setenv("RA_1688_IMAGE_CHANNELS", "cps")
    monkeypatch.setenv("RA_1688_CPS_IMAGE_SEARCH_DAILY_BUDGET", "100")
    provider = _WaterfallProvider(failing={"cps": RASupplierApiError(NO_USAGE_LEFT)})
    with pytest.raises(RAQuotaExhaustedError) as excinfo:
        _run_image_search_waterfall(
            ledger_db,
            provider=provider,
            product={"asin": "B0TEST0003"},
            keyword_profile={},
            limit=5,
            is_real_provider=True,
        )
    assert excinfo.value.provider == PROVIDER_1688_CPS_IMAGE_SEARCH
    assert usage_today(ledger_db)[PROVIDER_1688_CPS_IMAGE_SEARCH]["used"] == 100


def test_waterfall_reraises_product_level_errors(
    ledger_db: Session, monkeypatch: pytest.MonkeyPatch, bridge_calls
) -> None:
    monkeypatch.setenv("RA_1688_CPS_IMAGE_SEARCH_DAILY_BUDGET", "100")
    provider = _WaterfallProvider(
        failing={"cps": RASupplierApiError("该 R-W 产品缺少可用于 1688 图搜的图片。")}
    )
    with pytest.raises(RASupplierApiError):
        _run_image_search_waterfall(
            ledger_db,
            provider=provider,
            product={"asin": "B0TEST0004"},
            keyword_profile={},
            limit=5,
            is_real_provider=True,
        )
    # 失败退款：台账回到 0。
    assert usage_today(ledger_db)[PROVIDER_1688_CPS_IMAGE_SEARCH]["used"] == 0
    assert not bridge_calls["incident"]


# ------------------------------------------------------- C. 重试风暴止血
def test_classify_product_error_separates_provider_outage_from_product_issue() -> None:
    assert classify_product_error(NO_USAGE_LEFT) == "provider"
    assert (
        classify_product_error(
            'DeepSeek 关键词提取失败，已禁止降级启发式：DeepSeek 关键词抽取失败：HTTP 402 {"error":{"message":"Insufficient Balance"}}'
        )
        == "provider"
    )
    assert classify_product_error("1688 图搜网络失败：timed out") == "transient"
    assert (
        classify_product_error("DeepSeek 供应商匹配失败：The read operation timed out")
        == "transient"
    )
    assert classify_product_error("1688 分销图搜请求失败：HTTP 400 gw.QosAppFrequencyLimit") == "transient"
    assert classify_product_error("1688 扩品词搜返回失败：APIACLDecline") == "provider"
    assert classify_product_error("该 R-W 产品缺少可用于 1688 图搜的图片。") == "product"
    assert classify_product_error("详情页解析失败") == "product"


def _products_rw_sqlite() -> Session:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE products_rw (
                  asin TEXT PRIMARY KEY,
                  state TEXT,
                  rule_reject_reason TEXT,
                  features TEXT,
                  updated_at TEXT
                )
                """
            )
        )
    return Session(engine)


def test_failed_status_only_touches_features_and_cools_down() -> None:
    db = _products_rw_sqlite()
    db.execute(
        text("INSERT INTO products_rw (asin, state, features) VALUES ('B0FAIL0001', 'ai1_passed', '{}')")
    )
    db.commit()

    _mark_rw_profit_status(
        db,
        asin="B0FAIL0001",
        status="failed",
        run_id="run-1",
        candidate_id="",
        reason="1688 图搜网络失败",
        snapshot=None,
    )
    row = db.execute(
        text("SELECT state, rule_reject_reason, features FROM products_rw WHERE asin = 'B0FAIL0001'")
    ).mappings().first()
    assert row["state"] == "ai1_passed"
    assert row["rule_reject_reason"] is None
    features = json.loads(row["features"])
    assert features["ra_profit"]["status"] == "failed"
    assert features["ra_profit"]["calculated_at"]

    # 冷却期内不回池；把 calculated_at 拨回 8 天前就回池。
    predicate = _ra_profit_not_processed_sql(db)
    assert db.execute(
        text(f"SELECT COUNT(*) FROM products_rw WHERE {predicate}")
    ).scalar() == 0
    features["ra_profit"]["calculated_at"] = (
        datetime.now(UTC) - timedelta(days=8)
    ).isoformat()
    db.execute(
        text("UPDATE products_rw SET features = :features WHERE asin = 'B0FAIL0001'"),
        {"features": json.dumps(features)},
    )
    db.commit()
    assert db.execute(
        text(f"SELECT COUNT(*) FROM products_rw WHERE {predicate}")
    ).scalar() == 1


# ------------------------------------------------------- D. key-health 判定
def _deepseek_target() -> ProbeTarget:
    return ProbeTarget(
        key_id="key_00000000000000000000000000000001",
        org_id="org_00000000000000000000000000000000",
        name="DeepSeek",
        url="https://api.deepseek.com",
        key_hash_prefix="abcdef123456",
        key_type="deepseek",
        aliases=(),
        secret_value="test-secret-value",
    )


def _deepseek_transport(*, balance: str, available: bool = True, models_status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.deepseek.com"
        if request.url.path == "/models":
            if models_status != 200:
                return httpx.Response(
                    models_status, json={"error": {"message": "Insufficient Balance"}}
                )
            return httpx.Response(200, json={"data": [{"id": "deepseek-v4-flash"}]})
        if request.url.path == "/user/balance":
            return httpx.Response(
                200,
                json={
                    "is_available": available,
                    "balance_infos": [
                        {"currency": "CNY", "total_balance": balance, "granted_balance": "0.00"}
                    ],
                },
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    return httpx.MockTransport(handler)


def test_deepseek_probe_flags_zero_balance_as_credits_exhausted() -> None:
    result = probe_target(
        _deepseek_target(),
        enforce_public_network=False,
        transport=_deepseek_transport(balance="0.00"),
    )
    assert result.status == "provider_error"
    assert result.reason_code == "provider_credits_exhausted"
    assert result.details["balance"] == {"currency": "CNY", "total_balance": 0.0}


def test_deepseek_probe_healthy_with_balance_and_402_models() -> None:
    healthy = probe_target(
        _deepseek_target(),
        enforce_public_network=False,
        transport=_deepseek_transport(balance="128.40"),
    )
    assert healthy.status == "healthy"
    assert healthy.reason_code == "models_list_ok"
    assert healthy.details["balance"]["total_balance"] == 128.4

    unavailable = probe_target(
        _deepseek_target(),
        enforce_public_network=False,
        transport=_deepseek_transport(balance="5.00", available=False),
    )
    assert unavailable.reason_code == "provider_credits_exhausted"

    paid_wall = probe_target(
        _deepseek_target(),
        enforce_public_network=False,
        transport=_deepseek_transport(balance="0.00", models_status=402),
    )
    assert paid_wall.status == "provider_error"
    assert paid_wall.reason_code == "provider_credits_exhausted"


def test_runtime_incident_expiry_helper() -> None:
    now = datetime.now(UTC)
    active = {
        key_health_service.RUNTIME_INCIDENT_KEY: {
            "reason_code": "provider_quota_exhausted",
            "expires_at": (now + timedelta(hours=1)).isoformat(),
        }
    }
    expired = {
        key_health_service.RUNTIME_INCIDENT_KEY: {
            "reason_code": "provider_quota_exhausted",
            "expires_at": (now - timedelta(minutes=1)).isoformat(),
        }
    }
    assert key_health_service._active_runtime_incident(active, now=now) is not None
    assert key_health_service._active_runtime_incident(expired, now=now) is None
    assert key_health_service._active_runtime_incident({}, now=now) is None
    assert key_health_service._active_runtime_incident(None, now=now) is None


def test_bridge_throttles_repeat_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, object]] = []

    def fake_loader(name: str):
        def _fn(**kwargs: object) -> int:
            seen.append({"name": name, **kwargs})
            return 1

        return _fn

    monkeypatch.setattr(key_health_bridge, "_load_service_function", fake_loader)
    assert key_health_bridge.report_incident(
        key_type="alibaba1688", reason_code="provider_quota_exhausted", message="x"
    )
    assert not key_health_bridge.report_incident(
        key_type="alibaba1688", reason_code="provider_quota_exhausted", message="x"
    )
    assert key_health_bridge.report_recovered(key_type="alibaba1688")
    assert not key_health_bridge.report_recovered(key_type="alibaba1688")
    assert [item["name"] for item in seen] == [
        "report_runtime_incident",
        "report_runtime_recovered",
    ]


# ------------------------------------------- F. 翻译并进抽词 / R-W 不再翻译
def test_keyword_profile_carries_title_zh_only_when_chinese() -> None:
    product = {"asin": "B0X", "title": "Folding Camping Table", "brand": "Acme"}
    profile = sanitize_keyword_profile(
        {"title_zh": " 折叠露营桌 ", "product_type_zh": "露营桌"}, product=product
    )
    assert profile["title_zh"] == "折叠露营桌"
    assert sanitize_keyword_profile({"title_zh": "Folding Table"}, product=product)["title_zh"] is None
    assert sanitize_keyword_profile({}, product=product)["title_zh"] is None


def test_rw_upsert_keeps_existing_title_zh_when_refetch_has_none() -> None:
    engine = create_engine("sqlite:///:memory:")
    products_rw.create(engine)
    base = {
        "asin": "B0KEEP0001",
        "title": "Folding Camping Table",
        "title_zh": "折叠露营桌",
        "title_zh_source": "ra_keyword_profile",
        "title_zh_updated_at": datetime(2026, 9, 7, tzinfo=UTC),
        "features": {},
    }
    with Session(engine) as db:
        SQLAlchemyBatchWriter._bulk_upsert_products(None, db, [base])  # type: ignore[arg-type]
        db.commit()
        refetch = {**base, "title": "Folding Camping Table v2", "title_zh": None,
                   "title_zh_source": None, "title_zh_updated_at": None}
        SQLAlchemyBatchWriter._bulk_upsert_products(None, db, [refetch])  # type: ignore[arg-type]
        db.commit()
        row = db.execute(
            text("SELECT title, title_zh, title_zh_source FROM products_rw WHERE asin = 'B0KEEP0001'")
        ).mappings().first()
    assert row["title"] == "Folding Camping Table v2"
    assert row["title_zh"] == "折叠露营桌"
    assert row["title_zh_source"] == "ra_keyword_profile"


def test_keepa_worker_no_longer_translates_titles() -> None:
    class FakeDeepSeekSkill:
        def translate_title(self, title: str):  # 有这个方法也不该被调
            raise AssertionError("R-W must not call translate_title any more")

    writer = InMemoryBatchWriter()
    buffer = KeepaBufferQueue(writer=writer.write, batch_size=100, flush_interval_seconds=5)
    worker = KeepaWorker(
        provider=KeepaProvider(force_mock=True),
        buffer_queue=buffer,
        deepseek_skill=FakeDeepSeekSkill(),  # type: ignore[arg-type]
        enforce_wall_clock_rate=False,
    )
    worker.enqueue(
        [
            IngestionRecord(
                asin="B0HOLIDAY2",
                source_query="keepa_category:holiday-halloween",
                category_id="holiday-halloween",
            )
        ]
    )

    async def run() -> None:
        report = await worker.run_once()
        assert report.failed == 0, report.errors
        await buffer.flush()

    asyncio.run(run())
    product = writer.products["B0HOLIDAY2"]
    assert product["title_zh"] is None
    assert "title_translation" not in product["features"]


# ------------------------------------------- DeepSeek V4 默认思考模式必须关
def test_deepseek_thinking_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from r_system_v2.rw.ai.model_config import deepseek_thinking_extras

    monkeypatch.delenv("DEEPSEEK_THINKING", raising=False)
    assert deepseek_thinking_extras("deepseek-v4-flash") == {"thinking": {"type": "disabled"}}
    monkeypatch.setenv("DEEPSEEK_THINKING", "enabled")
    assert deepseek_thinking_extras("deepseek-v4-flash") == {}


def test_backend_deepseek_adapter_sends_thinking_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.services.ai_provider_router import DeepSeekAdapter

    monkeypatch.delenv("DEEPSEEK_THINKING", raising=False)
    adapter = DeepSeekAdapter.__new__(DeepSeekAdapter)
    body = DeepSeekAdapter.request_builder(
        adapter,
        task_type="chat",
        payload={"messages": [{"role": "user", "content": "hi"}], "temperature": 0},
        model="deepseek-v4-flash",
    )
    assert body["thinking"] == {"type": "disabled"}
    explicit = DeepSeekAdapter.request_builder(
        adapter,
        task_type="chat",
        payload={"messages": [{"role": "user", "content": "hi"}], "thinking": {"type": "enabled"}},
        model="deepseek-v4-flash",
    )
    assert explicit["thinking"] == {"type": "enabled"}


def test_keyword_profile_request_body_disables_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    from r_system_v2.ra import supplier_keyword_skill as skill

    captured: dict[str, object] = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps({"product_type_zh": "露营桌", "title_zh": "折叠露营桌"})}}]}
            ).encode()

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode())
        return _Resp()

    monkeypatch.setattr(skill, "urlopen", fake_urlopen)
    monkeypatch.delenv("DEEPSEEK_THINKING", raising=False)
    result = skill._call_deepseek_keyword_profile(
        api_key="k", product={"asin": "B0X", "title": "Folding Camping Table"}
    )
    assert result["title_zh"] == "折叠露营桌"
    assert captured["body"]["thinking"] == {"type": "disabled"}
