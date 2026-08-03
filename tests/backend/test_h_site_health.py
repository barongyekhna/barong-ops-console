"""H site-health integration tests: ingest, review, dispatch, and permission gates."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.models.user import User
from backend.app.modules.h_series.sitehealth import service
from backend.app.modules.h_series.sitehealth.models import HHealthFinding, HHealthRun
from backend.app.modules.notifications.models import PNotification

pytestmark = pytest.mark.integration

_TOKEN = "h-site-health-integration-token"


def _payload(*, finding_type: str = "broken_link") -> dict[str, object]:
    broken = 1 if finding_type == "broken_link" else 0
    return {
        "run_id": None,
        "status": "completed",
        "error": None,
        "summary": {
            "urls_total": 12,
            "urls_ok": 10,
            "urls_broken": broken,
            "urls_slow": 1,
            "avg_response_ms": 640,
            "p95_response_ms": 2100,
            "sitemap_ok": True,
            "homepage_ok": True,
        },
        "findings": [
            {
                "finding_type": finding_type,
                "url": "https://barongyekhna.com/example",
                "status_code": 404 if broken else 200,
                "response_ms": 320 if broken else 4200,
                "detail": "integration fixture",
            }
        ],
    }


@pytest.fixture
def h_env(owner_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("H_INGEST_TOKEN", _TOKEN)
    monkeypatch.delenv("N8N_H_HEALTH_WEBHOOK", raising=False)
    monkeypatch.delenv("H_CALLBACK_BASE", raising=False)
    with SessionLocal() as db:
        db.execute(delete(HHealthFinding))
        db.execute(delete(HHealthRun))
        db.execute(
            delete(PNotification).where(PNotification.source == "h_site_health")
        )
        db.commit()

    yield owner_client

    with SessionLocal() as db:
        db.execute(delete(HHealthFinding))
        db.execute(delete(HHealthRun))
        db.execute(
            delete(PNotification).where(PNotification.source == "h_site_health")
        )
        db.commit()


def test_ingest_records_run_findings_alert_and_deduplicates(
    h_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _payload()
    payload_findings = payload["findings"]
    assert isinstance(payload_findings, list)
    payload_findings.append(dict(payload_findings[0]))
    response = h_env.post(
        "/api/app/h/ingest",
        headers={"X-H-Ingest-Token": _TOKEN},
        json=payload,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["deduped"] is False
    run_id = result["run_id"]

    detail = h_env.get(f"/api/app/h/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    run = detail.json()
    assert run["trigger"] == "scheduled"
    assert run["status"] == "completed"
    assert run["urls_total"] == 12
    assert run["urls_ok"] == 10
    assert run["urls_broken"] == 1
    assert run["urls_slow"] == 1
    assert run["avg_response_ms"] == 640
    assert run["p95_response_ms"] == 2100
    assert run["sitemap_ok"] is True
    assert run["homepage_ok"] is True
    assert len(run["findings"]) == 1
    assert run["findings"][0]["finding_type"] == "broken_link"

    duplicate = dict(payload)
    duplicate["run_id"] = run_id
    response = h_env.post(
        "/api/app/h/ingest",
        headers={"X-H-Ingest-Token": _TOKEN},
        json=duplicate,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"run_id": run_id, "deduped": True}

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(HHealthRun)) == 1
        assert db.scalar(select(func.count()).select_from(HHealthFinding)) == 1
        alerts = [
            {
                "level": row.level,
                "title": row.title,
                "payload": row.payload,
            }
            for row in db.scalars(
                select(PNotification).where(
                    PNotification.event_type == "h.health_alert",
                    PNotification.source == "h_site_health",
                )
            ).all()
        ]
    assert len(alerts) == 1
    assert alerts[0]["level"] == "warning"
    assert alerts[0]["title"] == "站点巡检发现异常：死链 1 个"
    assert alerts[0]["payload"] == {
        "run_id": run_id,
        "urls_broken": 1,
        "sitemap_ok": True,
        "homepage_ok": True,
    }

    # A distinct scheduled run refreshes the existing open identity rather
    # than creating another finding row.
    original_finding_id = run["findings"][0]["id"]
    refresh_payload = _payload()
    refresh_finding = refresh_payload["findings"]
    assert isinstance(refresh_finding, list)
    refresh_finding[0].update(
        {
            "status_code": 410,
            "response_ms": 777,
            "detail": "refreshed by a later scheduled run",
        }
    )
    response = h_env.post(
        "/api/app/h/ingest",
        headers={"X-H-Ingest-Token": _TOKEN},
        json=refresh_payload,
    )
    assert response.status_code == 200
    assert response.json()["run_id"] != run_id
    refreshed = h_env.get(
        "/api/app/h/findings", params={"finding_type": "broken_link"}
    ).json()
    assert refreshed["total"] == 1
    assert refreshed["items"][0]["id"] == original_finding_id
    assert refreshed["items"][0]["status_code"] == 410
    assert refreshed["items"][0]["response_ms"] == 777
    assert refreshed["items"][0]["detail"] == "refreshed by a later scheduled run"

    # Different runs can finish concurrently with the same new finding.  Both
    # transactions synchronize before advisory-lock acquisition; only one open
    # row may survive the insert-or-update path.
    concurrent_run_ids = (uuid4(), uuid4())
    with SessionLocal() as db:
        db.add_all(
            [
                HHealthRun(
                    id=concurrent_run_ids[0],
                    trigger="scheduled",
                    status="running",
                    started_at=datetime.now(UTC),
                ),
                HHealthRun(
                    id=concurrent_run_ids[1],
                    trigger="scheduled",
                    status="running",
                    started_at=datetime.now(UTC),
                ),
            ]
        )
        db.commit()

    barrier = Barrier(2)
    original_lock = service._lock_finding_keys

    def synchronized_lock(db: Session, keys: set[tuple[str, str]]) -> None:
        barrier.wait(timeout=10)
        original_lock(db, keys)

    monkeypatch.setattr(service, "_lock_finding_keys", synchronized_lock)

    def finish_run(concurrent_run_id: UUID) -> None:
        with SessionLocal() as db:
            service.ingest_run(
                db,
                run_id=concurrent_run_id,
                result_status="completed",
                error=None,
                summary={
                    "urls_total": 1,
                    "urls_ok": 0,
                    "urls_broken": 0,
                    "urls_slow": 1,
                    "avg_response_ms": 4200,
                    "p95_response_ms": 4200,
                    "sitemap_ok": True,
                    "homepage_ok": True,
                },
                findings=[
                    {
                        "finding_type": "slow_page",
                        "url": "https://barongyekhna.com/concurrent",
                        "status_code": 200,
                        "response_ms": 4200,
                        "detail": "concurrent fixture",
                    }
                ],
            )
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(finish_run, run_id) for run_id in concurrent_run_ids]
        for future in futures:
            future.result(timeout=15)
    with SessionLocal() as db:
        concurrent_findings = int(
            db.scalar(
                select(func.count())
                .select_from(HHealthFinding)
                .where(
                    HHealthFinding.finding_type == "slow_page",
                    HHealthFinding.url
                    == "https://barongyekhna.com/concurrent",
                    HHealthFinding.status == "open",
                )
            )
            or 0
        )
    assert concurrent_findings == 1


def test_finding_status_transitions(h_env: TestClient) -> None:
    response = h_env.post(
        "/api/app/h/ingest",
        headers={"X-H-Ingest-Token": _TOKEN},
        json=_payload(finding_type="slow_page"),
    )
    assert response.status_code == 200
    listed = h_env.get("/api/app/h/findings")
    assert listed.status_code == 200
    finding = listed.json()["items"][0]
    assert finding["status"] == "open"

    response = h_env.patch(
        f"/api/app/h/findings/{finding['id']}",
        json={"action": "acknowledge"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "acknowledged"
    assert h_env.get("/api/app/h/findings").json()["total"] == 0
    assert (
        h_env.get(
            "/api/app/h/findings", params={"status": "acknowledged"}
        ).json()["total"]
        == 1
    )

    # A later run is allowed to create a new open row once the old row is
    # acknowledged. Reopening the old row must then fail instead of producing
    # two open findings for the same type+URL identity.
    response = h_env.post(
        "/api/app/h/ingest",
        headers={"X-H-Ingest-Token": _TOKEN},
        json=_payload(finding_type="slow_page"),
    )
    assert response.status_code == 200
    new_open = h_env.get("/api/app/h/findings").json()["items"][0]
    assert new_open["id"] != finding["id"]
    response = h_env.patch(
        f"/api/app/h/findings/{finding['id']}",
        json={"action": "reopen"},
    )
    assert response.status_code == 409
    assert h_env.get("/api/app/h/findings").json()["total"] == 1

    response = h_env.patch(
        f"/api/app/h/findings/{new_open['id']}",
        json={"action": "resolve"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    response = h_env.patch(
        f"/api/app/h/findings/{finding['id']}",
        json={"action": "reopen"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "open"
    response = h_env.patch(
        f"/api/app/h/findings/{finding['id']}",
        json={"action": "acknowledge"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "acknowledged"
    response = h_env.patch(
        f"/api/app/h/findings/{finding['id']}",
        json={"action": "resolve"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


def test_manual_trigger_dispatches_required_envelope(
    h_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, payload: dict[str, object]) -> None:
        captured["url"] = url
        captured["payload"] = payload

    monkeypatch.setenv("N8N_H_HEALTH_WEBHOOK", "https://n8n.example/h-health")
    monkeypatch.setenv("H_CALLBACK_BASE", "https://console.example/")
    monkeypatch.setattr(service, "_post_webhook", fake_post)
    response = h_env.post("/api/app/h/runs/trigger")
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["trigger"] == "manual"
    assert run["status"] == "running"
    assert captured == {
        "url": "https://n8n.example/h-health",
        "payload": {
            "trigger": "manual",
            "ingest_url": "https://console.example/api/app/h/ingest",
            "run_id": run["id"],
        },
    }


def test_manual_trigger_failure_persists_without_overwriting_ingest(
    h_env: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = h_env.post("/api/app/h/runs/trigger")
    assert response.status_code == 502
    assert response.json()["detail"] == service.N8N_UNREACHABLE_DETAIL
    with SessionLocal() as db:
        run = db.scalar(
            select(HHealthRun).order_by(HHealthRun.created_at.desc()).limit(1)
        )
        persisted = (
            None
            if run is None
            else (run.trigger, run.status, run.finished_at, run.error)
        )
    assert persisted is not None
    assert persisted[0] == "manual"
    assert persisted[1] == "failed"
    assert persisted[2] is not None
    assert persisted[3] == service.N8N_UNREACHABLE_DETAIL

    # A webhook client can time out after n8n has accepted the request.  If the
    # callback completes first, failure accounting must not overwrite completed.
    callback_run_id: list[str] = []

    def complete_then_fail(url: str, payload: dict[str, object]) -> None:
        del url
        run_id = str(payload["run_id"])
        callback_run_id.append(run_id)
        with SessionLocal() as callback_db:
            service.ingest_run(
                callback_db,
                run_id=UUID(run_id),
                result_status="completed",
                error=None,
                summary={
                    "urls_total": 1,
                    "urls_ok": 1,
                    "urls_broken": 0,
                    "urls_slow": 0,
                    "avg_response_ms": 100,
                    "p95_response_ms": 100,
                    "sitemap_ok": True,
                    "homepage_ok": True,
                },
                findings=[],
            )
            callback_db.commit()
        raise OSError("client timed out after n8n accepted the run")

    monkeypatch.setenv("N8N_H_HEALTH_WEBHOOK", "https://n8n.example/h-health")
    monkeypatch.setattr(service, "_post_webhook", complete_then_fail)
    response = h_env.post("/api/app/h/runs/trigger")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    with SessionLocal() as db:
        completed_status = db.scalar(
            select(HHealthRun.status).where(
                HHealthRun.id == UUID(callback_run_id[0])
            )
        )
    assert completed_status == "completed"


def test_runs_list_reaps_stale_running_rows(h_env: TestClient) -> None:
    stale_id = uuid4()
    completed_id = uuid4()
    with SessionLocal() as db:
        db.add_all(
            [
                HHealthRun(
                    id=stale_id,
                    trigger="scheduled",
                    status="running",
                    started_at=datetime.now(UTC) - timedelta(minutes=35),
                    updated_at=datetime.now(UTC) - timedelta(minutes=35),
                ),
                HHealthRun(
                    id=completed_id,
                    trigger="scheduled",
                    status="completed",
                    started_at=datetime.now(UTC) - timedelta(minutes=35),
                    finished_at=datetime.now(UTC) - timedelta(minutes=34),
                    updated_at=datetime.now(UTC) - timedelta(minutes=35),
                ),
            ]
        )
        db.commit()
    response = h_env.get("/api/app/h/runs")
    assert response.status_code == 200
    run = next(row for row in response.json()["runs"] if row["id"] == str(stale_id))
    assert run["status"] == "failed"
    assert run["finished_at"] is not None
    completed = next(
        row for row in response.json()["runs"] if row["id"] == str(completed_id)
    )
    assert completed["status"] == "completed"


def test_ingest_rejects_wrong_token(h_env: TestClient) -> None:
    assert h_env.post("/api/public/auth/logout").status_code == 200
    response = h_env.post(
        "/api/app/h/ingest",
        headers={"X-H-Ingest-Token": _TOKEN},
        json=_payload(finding_type="slow_page"),
    )
    assert response.status_code == 200
    response = h_env.post(
        "/api/app/h/ingest",
        headers={"X-H-Ingest-Token": "wrong"},
        json=_payload(),
    )
    assert response.status_code == 403


def test_h_human_endpoints_require_permission(
    h_env: TestClient, auth_client: TestClient
) -> None:
    username = "h_site_health_plain_viewer"
    password = "h-site-health-example-viewer-pass"
    with SessionLocal() as db:
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role="viewer",
                is_active=True,
            )
        )
        db.commit()

    response = auth_client.post(
        "/api/public/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    unknown = uuid4()
    assert auth_client.get("/api/app/h/runs").status_code == 403
    assert auth_client.get(f"/api/app/h/runs/{unknown}").status_code == 403
    assert auth_client.post("/api/app/h/runs/trigger").status_code == 403
    assert auth_client.get("/api/app/h/findings").status_code == 403
    assert (
        auth_client.patch(
            f"/api/app/h/findings/{unknown}",
            json={"action": "acknowledge"},
        ).status_code
        == 403
    )


def _run_payload(
    *,
    findings: list[dict[str, object]],
    checked_urls: list[str],
    status: str = "completed",
) -> dict[str, object]:
    """一轮巡检回报。checked_urls = 本轮**确实访问过**的地址。"""
    return {
        "run_id": None,
        "status": status,
        "error": None,
        "summary": {
            "urls_total": len(checked_urls),
            "urls_ok": max(0, len(checked_urls) - len(findings)),
            "urls_broken": sum(
                1 for f in findings if f["finding_type"] == "broken_link"
            ),
            "urls_slow": sum(1 for f in findings if f["finding_type"] == "slow_page"),
            "avg_response_ms": 400,
            "p95_response_ms": 1200,
            "sitemap_ok": True,
            "homepage_ok": True,
        },
        "findings": findings,
        "checked_urls": checked_urls,
    }


def _finding(url: str, *, kind: str = "broken_link") -> dict[str, object]:
    return {
        "finding_type": kind,
        "url": url,
        "status_code": 404,
        "response_ms": 120,
        "detail": "fixture",
    }


_A = "https://barongyekhna.com/gone-a"
_B = "https://barongyekhna.com/gone-b"
_C = "https://barongyekhna.com/not-visited-this-round"


def test_fixed_problems_close_themselves_next_round(h_env: TestClient) -> None:
    """修好的问题下一轮自己关掉——否则清单只进不出，人越清越烦，最后就不看了。

    但**只关本轮确实访问过的**。一轮巡检可能因限速或时间预算截断而漏掉一部分
    地址，那些地址上的老问题这次自然不会出现在 findings 里；靠"没报"去推断
    就会把它们一并判成已修复——那比不关更糟，因为人会以为没事了。
    """
    first = h_env.post(
        "/api/app/h/ingest",
        headers={"X-H-Ingest-Token": _TOKEN},
        json=_run_payload(
            findings=[_finding(_A), _finding(_B), _finding(_C)],
            checked_urls=[_A, _B, _C],
        ),
    )
    assert first.status_code == 200, first.text

    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(HHealthFinding)
                .where(HHealthFinding.status == "open")
            )
            == 3
        )

    # 第二轮：A 还坏着；B 修好了；C 这轮**压根没访问**（不在 checked_urls 里）
    second = h_env.post(
        "/api/app/h/ingest",
        headers={"X-H-Ingest-Token": _TOKEN},
        json=_run_payload(findings=[_finding(_A)], checked_urls=[_A, _B]),
    )
    assert second.status_code == 200, second.text

    with SessionLocal() as db:
        rows = {
            row.url: row
            for row in db.scalars(select(HHealthFinding)).all()
        }
        assert rows[_A].status == "open", "还在报的问题不能被关掉"
        assert rows[_B].status == "resolved", "访问过且不再报 = 修好了，该自动关"
        assert "自动关闭" in (rows[_B].detail or ""), "要留下自动关闭的痕迹"
        assert rows[_C].status == "open", (
            "本轮没访问到的地址绝不能judged为已修复——"
            "限速/截断导致的漏检会把真问题静默关掉"
        )


def test_auto_close_never_touches_ignored_or_failed_runs(h_env: TestClient) -> None:
    """两条边界：人手动「忽略」的不许系统改；失败的轮次不作数。"""
    h_env.post(
        "/api/app/h/ingest",
        headers={"X-H-Ingest-Token": _TOKEN},
        json=_run_payload(findings=[_finding(_A), _finding(_B)], checked_urls=[_A, _B]),
    )
    with SessionLocal() as db:
        target = db.scalars(
            select(HHealthFinding).where(HHealthFinding.url == _A)
        ).one()
        finding_id = str(target.id)

    # 人把 A 标成「忽略」——那是他主动做的分类，系统不该替他改
    acted = h_env.post(
        f"/api/app/h/findings/{finding_id}", json={"action": "acknowledge"}
    )
    assert acted.status_code == 200, acted.text

    # 失败的轮次即使带 checked_urls 也不作数：它没检查完，不代表"查过且没问题"
    h_env.post(
        "/api/app/h/ingest",
        headers={"X-H-Ingest-Token": _TOKEN},
        json=_run_payload(findings=[], checked_urls=[_A, _B], status="failed"),
    )
    with SessionLocal() as db:
        rows = {row.url: row.status for row in db.scalars(select(HHealthFinding)).all()}
        assert rows[_A] == "acknowledged", "已忽略的不许被系统改成已解决"
        assert rows[_B] == "open", "失败轮次不能关掉任何问题"

    # 成功的轮次才关
    h_env.post(
        "/api/app/h/ingest",
        headers={"X-H-Ingest-Token": _TOKEN},
        json=_run_payload(findings=[], checked_urls=[_A, _B]),
    )
    with SessionLocal() as db:
        rows = {row.url: row.status for row in db.scalars(select(HHealthFinding)).all()}
        assert rows[_A] == "acknowledged", "已忽略的依然不动"
        assert rows[_B] == "resolved"
