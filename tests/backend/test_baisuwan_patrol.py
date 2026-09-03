"""锁住白苏婉主动开口的四条规矩。

用户拍板的是:出事就说 · 只报「卡住」和「等审」· 一天最多一条 · 同一件事永不重提。

这几条一旦被改坏,后果不是报错,是**她开始刷老板的屏** —— 而老板当初否掉
通知系统的原话就是「按通知来发消息会非常乱」。静默失效比崩溃更糟,所以每条
规矩都要有一个测试盯着。
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.app.modules.agent_series.baisuwan import patrol


pytestmark = pytest.mark.unit


class _FakeClient:
    """只实现巡检用到的那几个只读方法。"""

    def __init__(self, *, clusters: list[dict[str, Any]], detail: dict[str, Any] | None = None,
                 jobs: list[dict[str, Any]] | None = None,
                 publishes: list[dict[str, Any]] | None = None,
                 seo: dict[str, Any] | None = None,
                 runs: list[dict[str, Any]] | None = None) -> None:
        self._clusters = clusters
        self._detail = detail or {"items": []}
        self._jobs = jobs or []
        self._publishes = publishes or []
        self._seo = seo or {"items": [], "jobs": []}
        self._runs = runs or []

    def clusters(self) -> dict[str, Any]:
        return {"clusters": self._clusters}

    def cluster_items(self, cluster_id: str) -> dict[str, Any]:
        return self._detail

    def cluster_jobs(self, cluster_id: str) -> dict[str, Any]:
        return {"jobs": self._jobs}

    def cluster_publishes(self, cluster_id: str) -> dict[str, Any]:
        return {"jobs": self._publishes}

    def seo_items(self) -> dict[str, Any]:
        return self._seo

    def monitor(self) -> dict[str, Any]:
        return {"runs": self._runs}


def _cluster(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "cluster-1",
        "topic": "portable camping shower",
        "status": "approved",
        "updated_at": "2026-08-21T00:00:00+00:00",
        "pending_product_ids": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- 只报两类


def test_progress_events_never_become_findings() -> None:
    """「监测跑完了」「任务成功了」这类进展,一条发现都不该产生。

    这是门槛本身:不需要他动手或改主意的事,连生成的机会都没有。
    """
    client = _FakeClient(
        clusters=[_cluster()],
        jobs=[{"job_id": "j1", "job_type": "geo_content", "status": "completed",
               "started_at": "2026-08-20T00:00:00+00:00"}],
        publishes=[{"job_id": "p1", "status": "success",
                    "created_at": "2026-08-20T00:00:00+00:00"}],
        runs=[{"id": "r1", "status": "success", "created_at": "2026-08-20T00:00:00+00:00"}],
        seo={"items": [{"id": "s1", "review_status": "approved"}], "jobs": []},
    )

    assert patrol.collect_findings(client) == []


def test_finished_work_waiting_on_human_is_a_finding() -> None:
    client = _FakeClient(
        clusters=[_cluster()],
        detail={
            "items": [
                {"id": "i1", "generation_status": "generated", "review_status": "pending"},
                {"id": "i2", "generation_status": "generated", "review_status": "approved"},
            ]
        },
    )

    findings = patrol.collect_findings(client)

    assert [f.kind for f in findings] == [patrol.KIND_AWAITING]
    assert "1 篇" in findings[0].headline


# ---------------------------------------------------------------- 旧失败不算卡住


def test_old_failure_followed_by_success_is_history_not_stuck() -> None:
    """7-29 失败、当天重跑成功 —— 报它等于拿三周前解决的事去打扰他。

    实测踩过:首次空跑 7 件发现里有 4 件是这种历史记录。
    """
    client = _FakeClient(
        clusters=[_cluster()],
        jobs=[
            {"job_id": "old", "job_type": "geo_content", "status": "failed",
             "started_at": "2026-07-29T10:15:00+00:00"},
            {"job_id": "new", "job_type": "geo_content", "status": "completed",
             "started_at": "2026-07-29T13:48:00+00:00"},
        ],
    )

    assert patrol.collect_findings(client) == []


def test_latest_attempt_failed_is_stuck() -> None:
    client = _FakeClient(
        clusters=[_cluster()],
        jobs=[
            {"job_id": "old", "job_type": "geo_content", "status": "completed",
             "started_at": "2026-07-29T10:15:00+00:00"},
            {"job_id": "new", "job_type": "geo_content", "status": "failed",
             "started_at": "2026-08-20T13:48:00+00:00", "error": "boom"},
        ],
    )

    findings = patrol.collect_findings(client)

    assert [f.kind for f in findings] == [patrol.KIND_STUCK]
    assert findings[0].key.endswith("new")


def test_superseded_seo_failure_is_ignored() -> None:
    client = _FakeClient(
        clusters=[],
        seo={
            "items": [],
            "jobs": [{"job_id": "j", "job_kind": "generate", "status": "failed",
                      "superseded": True, "started_at": "2026-08-20T00:00:00+00:00"}],
        },
    )

    assert patrol.collect_findings(client) == []


# ---------------------------------------------------------------- 一天一条 / 永不重提


def test_only_one_finding_is_picked_even_when_several_qualify() -> None:
    """三件事不打包成一条 —— 打包等于逼他当场做三个决定。"""
    findings = [
        patrol.Finding(key="a", kind=patrol.KIND_AWAITING, headline="等审"),
        patrol.Finding(key="b", kind=patrol.KIND_STUCK, headline="卡了 9 天", rank=-9),
        patrol.Finding(key="c", kind=patrol.KIND_STUCK, headline="卡了 22 天", rank=-22),
    ]

    picked = patrol.pick_one(findings, {"reported_keys": {}})

    # 卡住优先于等审;同为卡住时放得越久越先说。
    assert picked is not None and picked.key == "c"


def test_already_reported_finding_is_never_raised_again() -> None:
    findings = [patrol.Finding(key="a", kind=patrol.KIND_STUCK, headline="卡住")]

    assert patrol.pick_one(findings, {"reported_keys": {"a": "2026-08-01"}}) is None


def test_new_item_in_the_batch_counts_as_a_new_event() -> None:
    """同一批 = 同一件事;多了一条 = 新的一件事,该重新报。"""
    first = patrol._digest(["i1", "i2"])
    same = patrol._digest(["i2", "i1"])
    grown = patrol._digest(["i1", "i2", "i3"])

    assert first == same
    assert first != grown


def test_daily_cap_and_mute_both_close_her_mouth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(patrol, "local_today", lambda: "2026-08-21")

    assert patrol.may_speak({"last_spoke_date": None, "mute_until": None}) is True
    # 今天已经说过一条
    assert patrol.may_speak({"last_spoke_date": "2026-08-21", "mute_until": None}) is False
    # 静默期未过
    assert patrol.may_speak({"last_spoke_date": None, "mute_until": "2026-08-22"}) is False
    # 静默期昨天到期
    assert patrol.may_speak({"last_spoke_date": None, "mute_until": "2026-08-20"}) is True


def test_stale_cluster_is_reported_once_per_cluster_not_once_per_day() -> None:
    """键里不带天数 —— 否则「停了 9 天」明天变「停了 10 天」,天天报一遍。"""
    client = _FakeClient(
        clusters=[_cluster(status="needs_review", updated_at="2026-01-01T00:00:00+00:00")]
    )

    findings = [f for f in patrol.collect_findings(client) if f.kind == patrol.KIND_STUCK]

    assert len(findings) == 1
    assert findings[0].key == "stuck:stale_cluster:cluster-1"


def test_unreachable_endpoint_does_not_become_a_finding() -> None:
    """接口抽风是我们自己的故障,不该拿去打扰他。"""

    class _Broken(_FakeClient):
        def clusters(self) -> dict[str, Any]:
            raise RuntimeError("503")

    assert patrol.collect_findings(_Broken(clusters=[])) == []
