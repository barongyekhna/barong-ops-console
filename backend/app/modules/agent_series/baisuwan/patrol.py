"""主动巡检:她自己发现事情,而不是等人来问。

用户拍板的四条规矩(2026-08-21),全部落在代码里:

    出事就说 · 只报「卡住」和「等审」· 一天最多一条 · 同一件事永不重提

**为什么门槛必须写死在这里而不是提示词里**:用户当初否掉通知系统的原话是
「按通知来发消息会非常乱」。主动消息只要放开一点点,三天就会退化成刷屏的
通知系统 —— 而且比通知更糟,因为聊天窗没法忽略。提示词是软的(模型可以
忽略),白名单是硬的(不在表里的事根本走不到发消息那一步)。

判据只有一条:**这条消息他看完之后,需要动手或者改主意吗?**
不需要就不是发现,连生成的机会都没有。

所以「监测跑完了」「新挖到 12 个选题」「某个分数变高了」在这里一律没有对应
的规则 —— 不是被过滤掉,是压根没写。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ....services.media_store import storage_path
from .constants import (
    AGENT_USERNAME,
    REPORT_TIMEZONE,
    memory_root,
    stale_days,
)

_LOGGER = logging.getLogger("baisuwan.patrol")

STATE_DIR = "state"
STATE_FILE = "patrol.json"

# 记住报过什么,免得同一件事反复提。只留最近这些条 —— 再老的事早就不可能
# 重现了(键里带 id),留着只会把文件撑大。
MAX_REMEMBERED_KEYS = 500

KIND_STUCK = "stuck"
KIND_AWAITING = "awaiting"

# 卡住比等审急:等审是「你还没看」,卡住是「它自己走不下去了」。
_URGENCY = {KIND_STUCK: 0, KIND_AWAITING: 1}


@dataclass
class Finding:
    """一件够格打断老板的事。"""

    key: str
    kind: str
    headline: str
    facts: dict[str, Any] = field(default_factory=dict)
    # 越小越急。同类之间用它排,比如放了三周的比放了六天的先说。
    rank: int = 0

    @property
    def urgency(self) -> tuple[int, int]:
        return (_URGENCY.get(self.kind, 9), self.rank)


# ---------------------------------------------------------------- 状态


def _state_path() -> Path:
    return storage_path(Path(memory_root()) / AGENT_USERNAME, f"{STATE_DIR}/{STATE_FILE}")


def load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {"reported_keys": {}, "last_spoke_date": None, "mute_until": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _LOGGER.warning("巡检状态文件读不了,当作全新开始")
        return {"reported_keys": {}, "last_spoke_date": None, "mute_until": None}
    if not isinstance(data, dict):
        return {"reported_keys": {}, "last_spoke_date": None, "mute_until": None}
    data.setdefault("reported_keys", {})
    data.setdefault("last_spoke_date", None)
    data.setdefault("mute_until", None)
    return data


def save_state(state: dict[str, Any]) -> None:
    keys = state.get("reported_keys")
    if isinstance(keys, dict) and len(keys) > MAX_REMEMBERED_KEYS:
        newest = sorted(keys.items(), key=lambda kv: str(kv[1]), reverse=True)
        state["reported_keys"] = dict(newest[:MAX_REMEMBERED_KEYS])
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def local_today() -> str:
    """老板在洛杉矶。「一天一条」按他的日历算,不按 UTC —— 否则他的下午
    会被算成第二天,一天挨两条。"""
    return datetime.now(ZoneInfo(REPORT_TIMEZONE)).date().isoformat()


def may_speak(state: dict[str, Any]) -> bool:
    """今天还能不能开口。两道闸:静默期 + 一天一条。"""
    today = local_today()
    mute_until = state.get("mute_until")
    if isinstance(mute_until, str) and mute_until >= today:
        return False
    return state.get("last_spoke_date") != today


def mark_spoke(state: dict[str, Any], finding: Finding) -> None:
    state["last_spoke_date"] = local_today()
    keys = state.setdefault("reported_keys", {})
    keys[finding.key] = datetime.now(UTC).isoformat()


def set_mute(state: dict[str, Any], days: int) -> str:
    """「这两天别找我」——把静默期记下来。"""
    days = max(1, min(int(days), 30))
    until = datetime.now(ZoneInfo(REPORT_TIMEZONE)).date() + timedelta(days=days - 1)
    state["mute_until"] = until.isoformat()
    return state["mute_until"]


# ---------------------------------------------------------------- 发现


def _digest(values: list[str]) -> str:
    """一批东西的指纹。新来一条 = 新的指纹 = 新的一件事,该重新报;
    一模一样 = 同一件事,永不重提。"""
    joined = "|".join(sorted(values))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def _parse_dt(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _days_since(raw: Any) -> int | None:
    parsed = _parse_dt(raw)
    if parsed is None:
        return None
    return max(0, (datetime.now(UTC) - parsed).days)


def _latest_per(
    jobs: Any, *, group_field: str | None, time_field: str
) -> list[dict[str, Any]]:
    """每一类任务只留最近那一次。

    旧的失败后来被重跑成功了,它就不是「卡住」,是历史。2026-08-21 空跑实测:
    7 件发现里有 4 件是 7-29 失败、当天就已经重跑成功的记录 —— 全报出去等于
    拿三周前早就解决的事去打扰他,这正是主动消息最容易烂掉的地方。

    「最近这一次是什么状态」才是他真正要知道的事。
    """
    latest: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for job in jobs or []:
        if not isinstance(job, dict):
            continue
        group = str(job.get(group_field) or "") if group_field else "*"
        stamp = _parse_dt(job.get(time_field)) or datetime.min.replace(tzinfo=UTC)
        current = latest.get(group)
        if current is None or stamp > current[0]:
            latest[group] = (stamp, job)
    return [job for _, job in latest.values()]


def collect_findings(client: Any) -> list[Finding]:
    """跑一圈只读接口,把够格打断老板的事挑出来。

    任何一块取不到就跳过那一块 —— 接口抽风不该变成一条「出事了」的消息,
    那是拿我们自己的故障去打扰他。
    """
    findings: list[Finding] = []
    findings.extend(_geo_findings(client))
    findings.extend(_seo_findings(client))
    findings.extend(_monitor_findings(client))
    return findings


def _safe(loader, label: str) -> Any:
    try:
        return loader()
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("巡检 %s 取不到(跳过): %s", label, exc)
        return None


def _geo_findings(client: Any) -> list[Finding]:
    payload = _safe(lambda: client.clusters(), "geo/clusters")
    if not isinstance(payload, dict):
        return []
    out: list[Finding] = []
    for cluster in payload.get("clusters") or []:
        if not isinstance(cluster, dict):
            continue
        out.extend(_one_cluster(client, cluster))
    return out


def _one_cluster(client: Any, cluster: dict[str, Any]) -> list[Finding]:
    cluster_id = str(cluster.get("id") or "")
    topic = str(cluster.get("topic") or cluster.get("title") or "(无题)")
    status = str(cluster.get("status") or "")
    out: list[Finding] = []

    # ① 等审:内容写完了,躺在那儿等人看。
    detail = _safe(lambda: client.cluster_items(cluster_id), f"clusters/{cluster_id}")
    if isinstance(detail, dict):
        pending = [
            str(item.get("id"))
            for item in (detail.get("items") or [])
            if isinstance(item, dict)
            and item.get("generation_status") == "generated"
            and item.get("review_status") == "pending"
        ]
        if pending:
            out.append(
                Finding(
                    key=f"awaiting:geo_items:{cluster_id}:{_digest(pending)}",
                    kind=KIND_AWAITING,
                    headline=f"GEO 簇「{topic}」有 {len(pending)} 篇写完了在等审",
                    facts={
                        "cluster": topic,
                        "待审篇数": len(pending),
                        "簇状态": status,
                    },
                )
            )

    # ② 等审:产品悬在 pending 没归位,簇因此走不下去。
    pending_ids = [str(x) for x in (cluster.get("pending_product_ids") or [])]
    if pending_ids:
        out.append(
            Finding(
                key=f"awaiting:geo_pending_products:{cluster_id}:{_digest(pending_ids)}",
                kind=KIND_AWAITING,
                headline=f"GEO 簇「{topic}」有 {len(pending_ids)} 个产品悬在 pending 没归位",
                facts={
                    "cluster": topic,
                    "悬着的产品数": len(pending_ids),
                    "簇状态": status,
                },
            )
        )

    # ③ 卡住:任务失败了。
    jobs = _safe(lambda: client.cluster_jobs(cluster_id), f"clusters/{cluster_id}/jobs")
    if isinstance(jobs, dict):
        for job in _latest_per(
            jobs.get("jobs"), group_field="job_type", time_field="started_at"
        ):
            if job.get("status") == "failed":
                out.append(
                    Finding(
                        key=f"stuck:geo_job:{job.get('job_id')}",
                        kind=KIND_STUCK,
                        headline=f"GEO 簇「{topic}」的{job.get('job_type') or '生成'}任务失败了",
                        facts={
                            "cluster": topic,
                            "任务类型": job.get("job_type"),
                            "报错": str(job.get("error") or "")[:300],
                        },
                    )
                )

    pubs = _safe(
        lambda: client.cluster_publishes(cluster_id), f"clusters/{cluster_id}/publishes"
    )
    if isinstance(pubs, dict):
        for job in _latest_per(
            pubs.get("jobs"), group_field=None, time_field="created_at"
        ):
            if job.get("status") == "failed":
                out.append(
                    Finding(
                        key=f"stuck:geo_publish:{job.get('job_id')}",
                        kind=KIND_STUCK,
                        headline=f"GEO 簇「{topic}」的发布任务失败了",
                        facts={
                            "cluster": topic,
                            "报错": str(job.get("error") or "")[:300],
                        },
                    )
                )

    # ④ 卡住:停在半路很久没动。
    #
    # 只报一次(键里不带天数)。这条正是老板那句「我根本记不住这么多流程」
    # 的解药 —— 一个簇停了三周,不会有任何系统告诉他,只有她会。
    if status in {"needs_review", "generating", "draft"}:
        idle = _days_since(cluster.get("updated_at"))
        if idle is not None and idle >= stale_days():
            out.append(
                Finding(
                    key=f"stuck:stale_cluster:{cluster_id}",
                    kind=KIND_STUCK,
                    headline=f"GEO 簇「{topic}」停在 {status} 已经 {idle} 天没动了",
                    facts={"cluster": topic, "簇状态": status, "停了几天": idle},
                    rank=-idle,  # 放得越久越先说
                )
            )
    return out


def _seo_findings(client: Any) -> list[Finding]:
    payload = _safe(lambda: client.seo_items(), "seo/items")
    if not isinstance(payload, dict):
        return []
    out: list[Finding] = []

    pending = [
        str(item.get("id"))
        for item in (payload.get("items") or [])
        if isinstance(item, dict) and item.get("review_status") == "pending"
    ]
    if pending:
        out.append(
            Finding(
                key=f"awaiting:seo_items:{_digest(pending)}",
                kind=KIND_AWAITING,
                headline=f"SEO 有 {len(pending)} 篇文章写完了在等审",
                facts={"待审篇数": len(pending)},
            )
        )

    for job in _latest_per(
        payload.get("jobs"), group_field="job_kind", time_field="started_at"
    ):
        # superseded 的失败是被后来那次重跑顶掉的旧记录,不是还卡着的事。
        # 报它等于拿一件已经过去的事去打扰他。
        if job.get("status") != "failed" or job.get("superseded"):
            continue
        out.append(
            Finding(
                key=f"stuck:seo_job:{job.get('job_id')}",
                kind=KIND_STUCK,
                headline=f"SEO 的{job.get('job_kind') or '生成'}任务失败了",
                facts={
                    "任务类型": job.get("job_kind"),
                    "报错": str(job.get("error") or "")[:300],
                },
            )
        )
    return out


def _monitor_findings(client: Any) -> list[Finding]:
    payload = _safe(lambda: client.monitor(), "geo/monitor")
    if not isinstance(payload, dict):
        return []
    out: list[Finding] = []
    for run in _latest_per(
        payload.get("runs"), group_field=None, time_field="created_at"
    ):
        if run.get("status") == "failed":
            out.append(
                Finding(
                    key=f"stuck:monitor_run:{run.get('id')}",
                    kind=KIND_STUCK,
                    headline="GEO 阵地监测跑失败了",
                    facts={"报错": str(run.get("error") or "")[:300]},
                )
            )
    return out


def pick_one(findings: list[Finding], state: dict[str, Any]) -> Finding | None:
    """一天最多一条 —— 所以只挑最要紧的那一件,其余留着等他问。

    刻意不做「三件事打包成一条」:三件事写在一条消息里,他得当场做三个决定,
    那正是让他喘不过气的东西。一次一件。
    """
    reported = state.get("reported_keys") or {}
    fresh = [f for f in findings if f.key not in reported]
    if not fresh:
        return None
    fresh.sort(key=lambda f: f.urgency)
    return fresh[0]
