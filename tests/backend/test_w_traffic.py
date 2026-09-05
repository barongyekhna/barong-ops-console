"""独立站流量：归一化、ingest 门、幂等 upsert、心跳、区间报表、n8n 流 JSON。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text

from backend.app.db.session import SessionLocal
from backend.app.modules.w_series.traffic import service
from backend.app.modules.w_series.traffic.models import WTrafficDaily, WTrafficHourly
from backend.app.modules.w_series.traffic.schemas import TrafficIngestRequest
from backend.app.services.data_isolation import without_org_data_isolation
from backend.app.services.permission_service import upsert_permission_registry

TOKEN = "test-w-traffic-ingest-token"
WORKFLOW_JSON = (
    Path(__file__).resolve().parents[2]
    / "backend/app/modules/w_series/n8n/w_traffic_workflow.json"
)


def _visits(unit: str, rows: list[list]) -> dict:
    return {
        "date": "2026-09-05",
        "unit": unit,
        # 故意打乱列顺序：归一化必须按 fields 找列
        "fields": ["visitors", "period", "views", "likes"],
        "data": rows,
        "utc_offset": "-05:00",
    }


def _sample_payload() -> dict:
    return {
        "site_id": 242834372,
        "collected_at": "2026-09-05T18:05:00Z",
        "visits_day": _visits("day", [[6, "2026-09-03", 7, 0], [3, "2026-09-04", 3, 0], [2, "2026-09-05", 3, 0]]),
        "visits_hour": _visits("hour", [[1, "2026-09-05 13:00:00", 2, 0], [0, "2026-09-05 14:00:00", 0, 0]]),
        "top_posts": {
            "days": {
                "2026-09-04": {
                    "postviews": [
                        {"id": 861, "href": "https://barongyekhna.com/arctic", "title": "Arctic I", "type": "page", "views": 2},
                        {"id": 4053, "href": "https://barongyekhna.com/butter", "title": "Butter Stick", "type": "product", "views": 1},
                    ]
                },
                "2026-09-05": {
                    "postviews": [
                        {"id": 861, "href": "https://barongyekhna.com/arctic", "title": "Arctic I", "type": "page", "views": 3}
                    ]
                },
            }
        },
        "referrers": {
            "utc_offset": "-05:00",
            "days": {"2026-09-05": {"groups": [{"group": "search", "name": "Search Engines", "url": None, "total": 2}], "total_views": 2}},
        },
        "country_views": {
            "utc_offset": "-05:00",
            "days": {"2026-09-05": {"views": [{"country_code": "US", "views": 3}, {"country_code": "AU", "views": 1}]}},
            "country-info": {"US": {"country_full": "United States"}, "AU": {"country_full": "Australia"}},
        },
        "search_terms": {
            "utc_offset": "-05:00",
            "days": {"2026-09-05": {"search_terms": [{"term": "camping shower", "views": 1}], "encrypted_search_terms": 4}},
        },
        "clicks": {"utc_offset": "-05:00", "days": {"2026-09-05": {"clicks": []}}},
    }


# ---------------------------------------------------------------- unit


@pytest.mark.unit
def test_normalize_maps_all_seven_shapes() -> None:
    normalized = service.normalize(TrafficIngestRequest.model_validate(_sample_payload()))

    assert normalized.utc_offset == "-05:00"
    assert normalized.warnings == []
    day = normalized.days[date(2026, 9, 5)]
    assert (day.views, day.visitors) == (3, 2)
    assert day.top_posts[0]["title"] == "Arctic I" and day.top_posts[0]["views"] == 3
    assert day.referrers == [{"group": "search", "name": "Search Engines", "url": "", "views": 2}]
    assert day.countries[0] == {"code": "US", "name": "United States", "views": 3}
    assert day.search_terms == {"terms": [{"term": "camping shower", "views": 1}], "encrypted": 4}
    assert day.clicks == []
    assert day.present == {"visits", "top_posts", "referrers", "countries", "search_terms", "clicks"}
    # 只带 top_posts 的那天，其它列不算 present
    assert normalized.days[date(2026, 9, 4)].present == {"visits", "top_posts"}


@pytest.mark.unit
def test_hour_bucket_uses_site_utc_offset() -> None:
    normalized = service.normalize(TrafficIngestRequest.model_validate(_sample_payload()))

    bucket = datetime(2026, 9, 5, 13, 0, tzinfo=service.parse_utc_offset("-05:00"))
    assert normalized.hours[bucket] == (2, 1)
    assert bucket.astimezone(UTC) == datetime(2026, 9, 5, 18, 0, tzinfo=UTC)


@pytest.mark.unit
def test_normalize_tolerates_missing_and_broken_branches() -> None:
    payload = {"visits_day": _visits("day", [[1, "2026-09-05", 2, 0]]), "top_posts": {"days": "not-a-dict"}}

    normalized = service.normalize(TrafficIngestRequest.model_validate(payload))

    assert normalized.days[date(2026, 9, 5)].present == {"visits"}
    assert normalized.utc_offset == "-05:00"


@pytest.mark.unit
def test_unexpected_utc_offset_is_kept_but_warned() -> None:
    payload = {"utc_offset": "-04:00", "visits_day": _visits("day", [[1, "2026-09-05", 2, 0]])}

    normalized = service.normalize(TrafficIngestRequest.model_validate(payload))

    assert normalized.utc_offset == "-04:00"
    assert normalized.warnings and "differs" in normalized.warnings[0]


@pytest.mark.unit
def test_site_today_follows_site_timezone() -> None:
    # UTC 03:00 时站点（UTC-5）还是前一天
    assert service.site_today(datetime(2026, 9, 5, 3, 0, tzinfo=UTC)) == date(2026, 9, 4)
    assert service.site_today(datetime(2026, 9, 5, 12, 0, tzinfo=UTC)) == date(2026, 9, 5)


@pytest.mark.unit
def test_workflow_is_its_own_flow_and_active_version_matches() -> None:
    workflow = json.loads(WORKFLOW_JSON.read_text(encoding="utf-8"))

    assert workflow["id"] == "barongWtraffic001"
    assert workflow["versionId"] == workflow["activeVersionId"]
    assert workflow["active"] is True
    assert workflow["settings"]["timezone"] == "America/Los_Angeles"
    assert workflow["nodes"][0]["type"] == "n8n-nodes-base.stickyNote"

    trigger = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger")
    assert trigger["parameters"]["rule"]["interval"][0]["expression"] == "5-55/10 * * * *"

    http_nodes = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    jetpack = [n for n in http_nodes if "jetpack/v4/stats-app" in n["parameters"]["url"]]
    assert len(jetpack) == 7
    for node in jetpack:
        assert node["parameters"]["authentication"] == "predefinedCredentialType"
        assert node["parameters"]["nodeCredentialType"] == "wordpressApi"
        assert node["credentials"]["wordpressApi"]["id"] == "kaIcXMDT4cNA0GXm"

    ingest = next(n for n in http_nodes if n["parameters"]["url"].endswith("/w/traffic/ingest"))
    header = ingest["parameters"]["headerParameters"]["parameters"][0]
    assert header["name"] == "X-Ingest-Token"
    assert header["value"] == "__W_TRAFFIC_INGEST_TOKEN__"  # 仓库副本绝不含真令牌

    for node in workflow["nodes"]:
        if node["type"] == "n8n-nodes-base.code":
            code = node["parameters"]["jsCode"]
            assert "fetch(" not in code and "require(" not in code and "new URL(" not in code


# ---------------------------------------------------------------- integration


def _purge() -> None:
    with without_org_data_isolation(), SessionLocal() as db:
        db.execute(delete(WTrafficDaily))
        db.execute(delete(WTrafficHourly))
        db.execute(text("DELETE FROM worker_heartbeats WHERE worker_name = 'w-traffic'"))
        db.commit()


@pytest.fixture
def traffic_client(owner_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("W_TRAFFIC_INGEST_TOKEN", TOKEN)
    with SessionLocal() as db:
        upsert_permission_registry(db)
    _purge()
    yield owner_client
    _purge()


def _heartbeat() -> dict | None:
    with SessionLocal() as db:
        row = db.execute(
            text(
                "SELECT last_success_at, consecutive_failures, expected_interval_seconds, module_key "
                "FROM worker_heartbeats WHERE worker_name = 'w-traffic'"
            )
        ).mappings().first()
        return dict(row) if row else None


def _daily_count() -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(WTrafficDaily)) or 0)


@pytest.mark.integration
@pytest.mark.parametrize("headers", [{}, {"X-Ingest-Token": "wrong"}], ids=["missing", "wrong"])
def test_ingest_rejects_missing_or_wrong_token(traffic_client: TestClient, headers: dict) -> None:
    response = traffic_client.post("/w/traffic/ingest", json=_sample_payload(), headers=headers)
    assert response.status_code == 401
    assert _daily_count() == 0
    assert _heartbeat() is None


@pytest.mark.integration
def test_ingest_rejects_when_token_unset(traffic_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("W_TRAFFIC_INGEST_TOKEN")
    response = traffic_client.post(
        "/w/traffic/ingest", json=_sample_payload(), headers={"X-Ingest-Token": TOKEN}
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_ingest_upserts_idempotently_and_writes_heartbeat(traffic_client: TestClient) -> None:
    first = traffic_client.post("/w/traffic/ingest", json=_sample_payload(), headers={"X-Ingest-Token": TOKEN})
    assert first.status_code == 200, first.text
    assert first.json()["days_upserted"] == 3
    assert first.json()["hours_upserted"] == 2
    assert first.json()["day_from"] == "2026-09-03"
    assert first.json()["day_to"] == "2026-09-05"
    beat = _heartbeat()
    assert beat is not None
    assert beat["consecutive_failures"] == 0
    assert beat["expected_interval_seconds"] == 600
    assert beat["module_key"] == "w"

    # 第二轮：不带 top_posts，数值变了；行数不变，历史 JSON 列保留
    payload = _sample_payload()
    payload.pop("top_posts")
    payload["visits_day"]["data"][2] = [5, "2026-09-05", 9, 0]
    second = traffic_client.post("/w/traffic/ingest", json=payload, headers={"X-Ingest-Token": TOKEN})
    assert second.status_code == 200
    assert _daily_count() == 3
    with SessionLocal() as db:
        row = db.scalar(select(WTrafficDaily).where(WTrafficDaily.day == date(2026, 9, 5)))
        assert row is not None
        assert (row.views, row.visitors) == (9, 5)
        assert row.top_posts_json and row.top_posts_json[0]["title"] == "Arctic I"


@pytest.mark.integration
def test_empty_payload_does_not_refresh_heartbeat(traffic_client: TestClient) -> None:
    response = traffic_client.post("/w/traffic/ingest", json={}, headers={"X-Ingest-Token": TOKEN})
    assert response.status_code == 200
    assert response.json()["days_upserted"] == 0
    assert _heartbeat() is None


@pytest.mark.integration
def test_ingest_failure_records_failure_heartbeat(
    traffic_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_a, **_k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(service, "upsert_traffic", _boom)
    response = traffic_client.post("/w/traffic/ingest", json=_sample_payload(), headers={"X-Ingest-Token": TOKEN})
    assert response.status_code == 500
    beat = _heartbeat()
    assert beat is not None
    assert beat["consecutive_failures"] == 1
    assert beat["last_success_at"] is None


@pytest.mark.integration
def test_traffic_endpoints_zero_fill_and_validate_range(
    traffic_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    traffic_client.post("/w/traffic/ingest", json=_sample_payload(), headers={"X-Ingest-Token": TOKEN})
    # 冻结「站点今天」= 09-05，让窗口断言稳定
    monkeypatch.setattr(service, "site_today", lambda now=None: date(2026, 9, 5))

    summary = traffic_client.get("/api/app/dashboard/home/traffic?days=7")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["day_to"] == "2026-09-05"
    assert body["day_from"] == "2026-08-30"
    assert [d["views"] for d in body["days"]] == [0, 0, 0, 0, 7, 3, 3]
    assert body["views"] == 13 and body["visitors"] == 11
    assert body["today"] == {"day": "2026-09-05", "views": 3, "visitors": 2}
    assert body["top_post"]["title"] == "Arctic I"
    assert body["top_country"]["code"] == "US"
    assert body["collector_stale"] is False

    ranged = traffic_client.get("/api/app/dashboard/home/traffic/range?from=2026-09-04&to=2026-09-05")
    assert ranged.status_code == 200, ranged.text
    assert ranged.json()["top_posts"][0] == {"id": 861, "title": "Arctic I", "href": "https://barongyekhna.com/arctic", "type": "page", "views": 5}
    assert ranged.json()["encrypted_search_terms"] == 4
    assert ranged.json()["countries"][0]["views"] == 3

    too_long = traffic_client.get(
        f"/api/app/dashboard/home/traffic/range?from={date(2026, 6, 1)}&to={date(2026, 6, 1) + timedelta(days=92)}"
    )
    assert too_long.status_code == 422
    backwards = traffic_client.get("/api/app/dashboard/home/traffic/range?from=2026-09-05&to=2026-09-01")
    assert backwards.status_code == 422
