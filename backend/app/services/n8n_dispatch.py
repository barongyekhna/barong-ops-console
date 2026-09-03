"""n8n 串行派单的公共实现。

收口前，这套东西在**五个模块里各有一份**：P 上架、GEO 发布、GEO 反链、
SEO 发布、B2B 小窗。五份的结构完全一致（收僵尸 → 串行闸 → 取最老的 queued →
先提交再发送 → 失败递归），差别只在模型类、webhook 环境变量名、载荷字段
和错误文案的措辞。

**副本必然分叉，实测已经分叉了**（2026-09-03 逐份比对）：
  · 四份的 `urlopen` 不读响应体也不显式关闭，只有 P 那份规范
    （CPython 靠引用计数会立刻回收，所以不是泄漏，但行为不一致）；
  · 收僵尸的文案三种写法（可重新发布 / 可重试 / 可重新上传）；
  · `db.add(job)`、`db.scalars` vs `db.execute(...).scalars()` 各写各的。
分叉本身不致命，致命的是**下次修 bug 只会修到其中一份**。

**刻意不并进来的两份**（不是漏了，是不能合）：
  · `w_series/logistics.py` —— 按 target 串行、有 definitive/uncertain 错误
    分类、有全站锁序约定。并进来会重开运费重复写入的口子。
  · `h_series/sitehealth` —— 根本没有队列，10 秒超时被规格文档锁死。

`record_result` 也**刻意不合**：P 有一条必须保留的例外（迟到的 success 可以
翻案已被看门狗误判为 failed 的单，见 2026-08-11 的实测），合进来就得用参数
表达一个只有一家用的分支，得不偿失。
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

#: 派出去多久没回传就按失联处理。五个模块此前各写各的，值都是 15。
DEFAULT_IN_FLIGHT_TIMEOUT_MINUTES = 15
#: 发 webhook 的超时。五个模块此前都硬编码 15。
DEFAULT_WEBHOOK_TIMEOUT_SECONDS = 15


def _now() -> datetime:
    return datetime.now(UTC)


def callback_base(public_base: str) -> str:
    """回调地址的根。

    `P_CALLBACK_BASE` 是这五个模块共用的覆盖开关（名字带 P 是历史原因，
    GEO/SEO/B2B 也读它）—— 改名会让线上环境变量失配，所以保持原样。

    **两个都空就当场报错，不许发一个没有主机名的地址出去。**
    2026-09-03 实测：内容台的 `_public_base()` 读的是 `PUBLIC_API_BASE_URL`，
    而那个变量在生产容器里根本没设置（compose 引用了两次，env 里没定义），
    返回空串 —— 现在靠 `P_CALLBACK_BASE` 挡着才没出事。哪天那个也没了，
    package_url 会变成 `/geo/clusters/…` 这种相对地址，n8n 取不到包，
    而且**整条链静默失败**：任务照常派出去、照常等回传、15 分钟后被看门狗
    判失联，没有一处会说「地址是错的」。宁可在这里当场炸。
    """
    base = (os.getenv("P_CALLBACK_BASE") or public_base).strip().rstrip("/")
    if not base:
        raise RuntimeError(
            "回调地址的根是空的（P_CALLBACK_BASE 与调用方传入的 public_base 都为空）"
            "—— 发出去的 package_url 会没有主机名，n8n 取不到包。"
        )
    return base


def post_to_n8n(
    webhook_env: str,
    payload: dict[str, Any],
    *,
    timeout: int = DEFAULT_WEBHOOK_TIMEOUT_SECONDS,
) -> None:
    """把一单 POST 给 n8n webhook。调用方负责状态流转。

    读完响应体再关闭 —— 五份副本里只有 P 这么写，统一到规范的那份。
    """
    webhook = (os.getenv(webhook_env) or "").strip()
    if not webhook:
        raise RuntimeError(f"{webhook_env} 未配置")
    request = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        response.read()


@dataclass(frozen=True)
class QueueSpec:
    """一条串行队列的全部差异点。"""

    #: 任务表的 ORM 模型。需要 status / created_at / dispatched_at / finished_at / error。
    model: type[Any]
    #: webhook 地址的环境变量名。
    webhook_env: str
    #: (job, base) -> 发给 n8n 的载荷。base 已经去掉尾斜杠。
    build_payload: Callable[[Any, str], dict[str, Any]]
    #: 看门狗收尸时写进 error 的话。必须含「未回传」——
    #: P 的 record_result 靠这三个字区分「推测的失败」和「事实的失败」。
    stale_error: str
    in_flight_timeout_minutes: int = DEFAULT_IN_FLIGHT_TIMEOUT_MINUTES


def send(spec: QueueSpec, job: Any, *, public_base: str) -> None:
    post_to_n8n(spec.webhook_env, spec.build_payload(job, callback_base(public_base)))


def kick_queue(db: Session, spec: QueueSpec, *, public_base: str) -> Any | None:
    """收僵尸，然后在「无 in-flight」时派下一单。

    返回本次真正派出去的 job（没有则 None）。幂等，可被任何触发点安全调用
    （入队后 / n8n 回传后 / 台账页轮询时）。

    四条不变量，改这里之前先看 `tests/backend/test_n8n_queue_contract.py`：
      1. 收僵尸：dispatched 超时的标 failed，把跑道腾出来
      2. 严格串行：有 in-flight 就一单都不派
      3. **先提交再发送** —— 2026-07-23 实锤的竞态：n8n 收到 webhook 后
         毫秒级回来取包，任务行若还没提交，取数按「token 无效」401 打回
      4. 发送失败不阻塞队列：本单标 failed，递归踢下一单
    """
    model = spec.model

    # 1) 失联收尸
    deadline = _now() - timedelta(minutes=spec.in_flight_timeout_minutes)
    stale = db.scalars(
        select(model)
        .where(model.status == "dispatched")
        .where(model.dispatched_at < deadline)
        .with_for_update(skip_locked=True)
    ).all()
    for job in stale:
        job.status = "failed"
        job.error = spec.stale_error
        job.finished_at = _now()
        db.add(job)
    if stale:
        db.flush()

    # 2) 跑道占用检查（严格串行）
    in_flight = db.scalar(
        select(model.id).where(model.status == "dispatched").limit(1)
    )
    if in_flight is not None:
        return None

    # 3) 取最老的 queued，行锁防并发触发点重复派单
    job = db.scalars(
        select(model)
        .where(model.status == "queued")
        .order_by(model.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None

    # 4) 先落库再发货（见上面第 3 条不变量）
    job.status = "dispatched"
    job.dispatched_at = _now()
    db.add(job)
    db.commit()
    try:
        send(spec, job, public_base=public_base)
    except Exception as exc:  # noqa: BLE001 - 一个坏 webhook 不能卡死整条队列
        job.status = "failed"
        job.error = f"dispatch failed: {exc}"[:500]
        job.finished_at = _now()
        db.add(job)
        db.commit()
        # 继续踢下一单（递归深度 = 连续失败单数，有限）
        return kick_queue(db, spec, public_base=public_base)
    return job
