"""W-S logistics orchestration for Woo sync jobs and 17TRACK tracking.

WooCommerce writes are dispatched to n8n.  Tracking registration and reads are
sent directly to 17TRACK.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError

from ...models.organization import OrganizationRecord
from ...repositories.security import register_rate_limit_attempt
from ...services.data_isolation import without_org_data_isolation
from .shipping.models import WOrder, WShippingClass, WSyncJob

TARGET_ORGANIZATION_NAME = "涌龙麟（深圳）国际贸易有限公司"
N8N_WEBHOOK_ENV = "N8N_W_SYNC_WEBHOOK"
TRACK17_BASE_URL_ENV = "W_17TRACK_BASE_URL"
TRACK17_DEFAULT_BASE_URL = "https://api.17track.net"
TRACK17_SIGN_MODE_ENV = "W_17TRACK_WEBHOOK_SIGN_MODE"
TRACK17_TIMEOUT_SECONDS = 15
N8N_TIMEOUT_SECONDS = 15
TRACK_PUBLIC_MINUTE_LIMIT = 600
TRACK_PUBLIC_WINDOW_SECONDS = 60
TRACK_PUBLIC_RATE_LIMIT_SCOPE = "track_global_minute"
TRACK_PUBLIC_RATE_LIMIT_IDENTIFIER = "global"
TRACK_PUBLIC_RATE_LIMIT_ENDPOINT = "track.lookup"

SYNC_IN_FLIGHT_STATUSES = ("pending", "dispatched")
SHIPPING_STATUSES = (
    "registered",
    "info_received",
    "in_transit",
    "out_for_delivery",
)
EXCEPTION_STATUSES = ("exception", "expired", "not_found")

_TRACK17_STATUS_MAP = {
    "notfound": "not_found",
    "inforeceived": "info_received",
    "pickedup": "in_transit",
    "intransit": "in_transit",
    "availableforpickup": "in_transit",
    "outfordelivery": "out_for_delivery",
    "deliveryfailure": "exception",
    "delivered": "delivered",
    "exception": "exception",
    "expired": "expired",
    "returned": "exception",
    "returning": "exception",
}


def _now() -> datetime:
    return datetime.now(UTC)


def register_track_public_rate_limit(
    db: Session,
    *,
    now: datetime | None = None,
) -> bool:
    """Consume the process-shared global bucket for public tracking lookups."""

    result = register_rate_limit_attempt(
        db,
        scope=TRACK_PUBLIC_RATE_LIMIT_SCOPE,
        identifier=TRACK_PUBLIC_RATE_LIMIT_IDENTIFIER,
        endpoint_key=TRACK_PUBLIC_RATE_LIMIT_ENDPOINT,
        limit=TRACK_PUBLIC_MINUTE_LIMIT,
        window_seconds=TRACK_PUBLIC_WINDOW_SECONDS,
        now=now or _now(),
    )
    return result.allowed


def _public_base() -> str:
    return (
        os.getenv("PUBLIC_BASE_URL") or "https://ops.barongyekhna.com"
    ).strip().rstrip("/")


def _callback_base() -> str:
    """n8n 回调控制台用的 base（照 P 的口径：内网直连优先，公网回退）。"""
    return (os.getenv("W_CALLBACK_BASE") or _public_base()).strip().rstrip("/")


def _track17_base() -> str:
    return (
        os.getenv(TRACK17_BASE_URL_ENV, TRACK17_DEFAULT_BASE_URL).strip()
        or TRACK17_DEFAULT_BASE_URL
    ).rstrip("/")


def _target_org_id(db: Session) -> str | None:
    with without_org_data_isolation():
        return db.scalar(
            select(OrganizationRecord.org_id)
            .where(OrganizationRecord.org_name == TARGET_ORGANIZATION_NAME)
            .where(OrganizationRecord.status != "deleted")
            .limit(1)
        )


def list_woo_shipping_zones(db: Session) -> list[dict[str, Any]]:
    """只读拉取 Woo 配送区域(供运费模板下拉选择,消灭区域名手误)。

    凭据走 H 桥的解析链(密钥管理→env 回退);Woo 不可达或未配凭据时
    返回空表——前端据此优雅退回手填输入框,绝不因此报错。
    排除 id=0 的「其余未覆盖区域」兜底区。
    """

    from ...services import wp_bridge

    try:
        credentials = wp_bridge._resolve_credentials(  # noqa: SLF001 - 站内共享口径
            db=db, org_id=_target_org_id(db)
        )
        if credentials is None:
            return []
        url = f"{credentials.base_url.rstrip('/')}/wp-json/wc/v3/shipping/zones"
        result = wp_bridge._request_json(  # noqa: SLF001 - 站内共享口径
            url, credentials=credentials, authenticated=True
        )
        data = result.get("data")
        if not result.get("reachable") or not isinstance(data, list):
            return []
        zones: list[dict[str, Any]] = []
        for zone in data:
            zone_id = zone.get("id") if isinstance(zone, dict) else None
            name = str(zone.get("name") or "").strip() if isinstance(zone, dict) else ""
            if isinstance(zone_id, int) and zone_id > 0 and name:
                zones.append({"id": zone_id, "name": name})
        return zones
    except Exception:  # noqa: BLE001 - 下拉选项是锦上添花,失败不许影响页面
        return []


def track17_key(db: Session) -> str:
    """Resolve the W-S 17TRACK key from the central secret binding."""

    org_id = _target_org_id(db)
    if not org_id:
        raise RuntimeError(
            f"目标组织不存在：{TARGET_ORGANIZATION_NAME}（W 模块只挂国际贸易组织）"
        )
    try:
        key = SecretManager(db_session=db).get_key("track17", org_id)
    except SecretManagerError as exc:
        raise RuntimeError(f"17TRACK 密钥未绑定：{exc}") from exc
    if not key:
        raise RuntimeError("17TRACK 密钥未绑定（去密钥管理添加）。")
    return key


def _post_json(
    url: str,
    *,
    payload: object,
    headers: dict[str, str] | None = None,
    timeout: int,
    expect_json: bool = True,
) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        raw = response.read()
    if not expect_json:
        return {}
    if not raw:
        return {}
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("remote response is not a JSON object")
    return parsed


def _remote_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        reason = str(exc.reason).strip()
        return reason or "network error"
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _definitive_n8n_rejection(exc: Exception) -> bool:
    """Only client errors that clearly reject the request are safe to advance."""

    return (
        isinstance(exc, urllib.error.HTTPError)
        and 400 <= exc.code < 500
        and exc.code not in {408, 409, 425, 429}
    )


def _job_action(job: WSyncJob) -> str:
    payload = job.payload_json if isinstance(job.payload_json, dict) else {}
    action = str(payload.get("action") or "").strip()
    if action:
        return action
    if job.target_type == "shipping_class":
        return "upsert_shipping_class"
    return "order_tracking"


def _job_payload(job: WSyncJob) -> dict[str, Any]:
    stored = job.payload_json if isinstance(job.payload_json, dict) else {}
    nested = stored.get("payload")
    return nested if isinstance(nested, dict) else dict(stored)


def _n8n_envelope(job: WSyncJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "action": _job_action(job),
        "token": job.token,
        "payload": _job_payload(job),
        "callback_url": f"{_callback_base()}/w/sync/{job.job_id}/result",
    }


def _apply_job_failure(db: Session, job: WSyncJob, error: str) -> None:
    job.status = "failed"
    job.error = error[:2000]
    job.finished_at = _now()
    if job.target_type == "shipping_class":
        row = db.get(WShippingClass, job.target_id)
        if row is not None:
            row.sync_status = "failed"
            row.sync_error = error[:2000]
    elif job.target_type == "order_tracking":
        order = db.get(WOrder, job.target_id)
        if order is not None:
            order.writeback_status = "failed"


def _lock_job_and_target(
    db: Session,
    job_id: str,
) -> tuple[WSyncJob | None, WShippingClass | WOrder | None]:
    """Lock a sync target before its job so every writer uses one lock order."""

    probe = db.scalar(select(WSyncJob).where(WSyncJob.job_id == job_id))
    if probe is None:
        return None, None
    target: WShippingClass | WOrder | None = None
    if probe.target_type == "shipping_class":
        target = db.scalar(
            select(WShippingClass)
            .where(WShippingClass.id == probe.target_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    elif probe.target_type == "order_tracking":
        target = db.scalar(
            select(WOrder)
            .where(WOrder.id == probe.target_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    job = db.scalar(
        select(WSyncJob)
        .where(WSyncJob.job_id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return job, target


SYNC_STALE_MINUTES = 15


def reap_stale_sync_jobs(db: Session) -> int:
    """惰性收尸（照 P 队列语义）：dispatched 超过 15 分钟无回调按失联标 failed，
    连带把卡在 pending 的模板/回传状态放回 failed，让「重试同步」按钮有出口。"""

    deadline = _now() - timedelta(minutes=SYNC_STALE_MINUTES)
    stale = list(
        db.scalars(
            select(WSyncJob)
            .where(WSyncJob.status == "dispatched")
            .where(WSyncJob.dispatched_at < deadline)
            .with_for_update(skip_locked=True)
        ).all()
    )
    for job in stale:
        job.status = "failed"
        job.error = (
            f"n8n 超过 {SYNC_STALE_MINUTES} 分钟未回传，按失联处理"
            "（检查 n8n 执行记录后可重试）"
        )
        job.finished_at = _now()
        if job.target_type == "shipping_class":
            row = db.get(WShippingClass, job.target_id)
            if row is not None and row.sync_status == "pending":
                row.sync_status = "failed"
                row.sync_error = job.error
        elif job.target_type == "order_tracking":
            order = db.get(WOrder, job.target_id)
            if order is not None and order.writeback_status == "pending":
                order.writeback_status = "failed"
    if stale:
        db.flush()
    return len(stale)


def dispatch_sync_job(db: Session, job_id: str) -> tuple[WSyncJob, bool]:
    """Dispatch one already-persisted job without holding a DB transaction."""

    job, _target = _lock_job_and_target(db, job_id)
    if job is None:
        raise LookupError("sync job not found")
    if job.status in ("success", "failed"):
        succeeded = job.status == "success"
        db.commit()
        return job, succeeded
    webhook = (os.getenv(N8N_WEBHOOK_ENV) or "").strip()
    if not webhook:
        db.commit()
        return job, False
    if job.status == "dispatched":
        db.commit()
        return job, False
    if job.target_type == "order_tracking":
        active_dispatch = db.scalar(
            select(WSyncJob.id)
            .where(WSyncJob.target_type == "order_tracking")
            .where(WSyncJob.target_id == job.target_id)
            .where(WSyncJob.id != job.id)
            .where(WSyncJob.status == "dispatched")
            .limit(1)
        )
        if active_dispatch is not None:
            db.commit()
            return job, False
    envelope = _n8n_envelope(job)
    job.status = "dispatched"
    job.dispatched_at = _now()
    job.error = None
    db.commit()

    # Repository invariant: never retain a control-DB transaction over slow I/O.
    try:
        _post_json(
            webhook,
            payload=envelope,
            timeout=N8N_TIMEOUT_SECONDS,
            expect_json=False,
        )
    except Exception as exc:  # noqa: BLE001 - dispatch failure is persisted
        job, _target = _lock_job_and_target(db, job_id)
        if job is None:
            raise LookupError("sync job disappeared after dispatch") from exc
        if job.status in ("success", "failed"):
            db.commit()
            return job, True
        error = _remote_error(exc)
        next_job_id: str | None = None
        if _definitive_n8n_rejection(exc):
            _apply_job_failure(db, job, f"n8n dispatch failed: {error}")
            if job.target_type == "order_tracking":
                next_job_id = pending_order_writeback_job_id(db, job.target_id)
                if next_job_id is not None and isinstance(_target, WOrder):
                    _target.writeback_status = "pending"
        else:
            # A connection/read timeout can occur after n8n accepted the body.
            # Keep the job callback-eligible and serialize later writes behind it.
            uncertain = f"n8n dispatch uncertain: {error}"
            job.error = uncertain
            if job.target_type == "shipping_class":
                row = db.get(WShippingClass, job.target_id)
                if row is not None:
                    row.sync_error = uncertain
        db.commit()
        if next_job_id is not None:
            try:
                dispatch_sync_job(db, next_job_id)
            except Exception:  # noqa: BLE001 - the queued job remains durable
                db.rollback()
        return job, False

    job, _target = _lock_job_and_target(db, job_id)
    if job is None:
        raise LookupError("sync job disappeared after dispatch")
    db.commit()
    return job, True


def create_shipping_sync_job(
    db: Session,
    shipping_class: WShippingClass,
) -> WSyncJob:
    """Create an in-flight-safe n8n upsert job for one shipping template."""

    existing = db.scalar(
        select(WSyncJob.id)
        .where(WSyncJob.target_type == "shipping_class")
        .where(WSyncJob.target_id == shipping_class.id)
        .where(WSyncJob.status.in_(SYNC_IN_FLIGHT_STATUSES))
        .limit(1)
    )
    if existing is not None:
        raise RuntimeError("该模板已有同步任务在执行中。")

    zone_rates = (
        shipping_class.zone_rates_json
        if isinstance(shipping_class.zone_rates_json, list)
        else []
    )
    job = WSyncJob(
        job_id=uuid4().hex,
        target_type="shipping_class",
        target_id=shipping_class.id,
        token=secrets.token_urlsafe(32),
        status="pending",
        payload_json={
            "action": "upsert_shipping_class",
            "payload": {
                "slug": shipping_class.slug,
                "name": shipping_class.name,
                "description": shipping_class.description,
                "woo_class_id": shipping_class.woo_class_id,
                "zone_rates": zone_rates,
            },
        },
    )
    shipping_class.sync_status = "pending"
    shipping_class.sync_error = None
    db.add(job)
    db.flush()
    return job


def create_shipping_delete_job(
    db: Session,
    shipping_class: WShippingClass,
) -> WSyncJob:
    """派 n8n 删除 Woo 侧运费模板；回调 success 后本地行才真正删除。

    未来 GMC 同步走同一形状：action 命名空间预留 *_shipping_class 系列
    （upsert/delete），执行端按 action 分发即可扩展。
    """

    existing = db.scalar(
        select(WSyncJob.id)
        .where(WSyncJob.target_type == "shipping_class")
        .where(WSyncJob.target_id == shipping_class.id)
        .where(WSyncJob.status.in_(SYNC_IN_FLIGHT_STATUSES))
        .limit(1)
    )
    if existing is not None:
        raise RuntimeError("该模板已有同步任务在执行中。")

    job = WSyncJob(
        job_id=uuid4().hex,
        target_type="shipping_class",
        target_id=shipping_class.id,
        token=secrets.token_urlsafe(32),
        status="pending",
        payload_json={
            "action": "delete_shipping_class",
            "payload": {
                "slug": shipping_class.slug,
                "woo_class_id": shipping_class.woo_class_id,
            },
        },
    )
    shipping_class.sync_status = "pending"
    shipping_class.sync_error = None
    db.add(job)
    db.flush()
    return job


def supersede_order_writeback_jobs(db: Session, order_id: UUID) -> None:
    """Drop obsolete queued values without cancelling an already running flow."""

    stale_jobs = list(
        db.scalars(
            select(WSyncJob)
            .where(WSyncJob.target_type == "order_tracking")
            .where(WSyncJob.target_id == order_id)
            .where(WSyncJob.status == "pending")
            .with_for_update()
        ).all()
    )
    for stale_job in stale_jobs:
        stale_job.status = "failed"
        stale_job.error = "superseded by a newer tracking update"
        stale_job.finished_at = _now()


def create_order_writeback_job(db: Session, order: WOrder) -> WSyncJob:
    """Persist the latest n8n writeback and supersede stale in-flight jobs."""

    supersede_order_writeback_jobs(db, order.id)
    carrier_label = str(order.carrier_code) if order.carrier_code is not None else None
    job = WSyncJob(
        job_id=uuid4().hex,
        target_type="order_tracking",
        target_id=order.id,
        token=secrets.token_urlsafe(32),
        status="pending",
        payload_json={
            "action": "order_tracking",
            "payload": {
                "woo_order_id": order.woo_order_id,
                "tracking_number": order.tracking_number,
                "carrier_label": carrier_label,
            },
        },
    )
    order.writeback_status = "pending"
    db.add(job)
    db.flush()
    return job


def record_sync_result(
    db: Session,
    *,
    job_id: str,
    token: str | None,
    result_status: str,
    woo_class_id: int | None,
    error: str | None,
) -> WSyncJob | None:
    job, target = _lock_job_and_target(db, job_id)
    if job is None:
        return None
    if not token or not secrets.compare_digest(
        token.encode("utf-8"),
        job.token.encode("utf-8"),
    ):
        raise PermissionError("invalid job token")
    if job.status in ("success", "failed"):
        return job

    job.status = result_status
    job.error = error
    job.finished_at = _now()
    if job.target_type == "shipping_class":
        row = target if isinstance(target, WShippingClass) else None
        stored = job.payload_json if isinstance(job.payload_json, dict) else {}
        job_action = str(stored.get("action") or "upsert_shipping_class")
        if row is not None:
            if result_status == "success" and job_action == "delete_shipping_class":
                # Woo 侧已删，本地行随之删除（删除同步的最终一致点）。
                db.delete(row)
            elif result_status == "success":
                row.sync_status = "synced"
                if woo_class_id is not None:
                    row.woo_class_id = woo_class_id
                row.synced_at = _now()
                row.sync_error = None
            else:
                row.sync_status = "failed"
                row.sync_error = error
    elif job.target_type == "order_tracking":
        order = target if isinstance(target, WOrder) else None
        if order is not None:
            job_payload = _job_payload(job)
            payload_number = job_payload.get("tracking_number")
            payload_carrier = job_payload.get("carrier_label")
            current_carrier = (
                str(order.carrier_code) if order.carrier_code is not None else None
            )
            latest_job_id = db.scalar(
                select(WSyncJob.id)
                .where(WSyncJob.target_type == "order_tracking")
                .where(WSyncJob.target_id == job.target_id)
                .order_by(WSyncJob.id.desc())
                .limit(1)
            )
            newer_in_flight = db.scalar(
                select(WSyncJob.id)
                .where(WSyncJob.target_type == "order_tracking")
                .where(WSyncJob.target_id == job.target_id)
                .where(WSyncJob.id > job.id)
                .where(WSyncJob.status.in_(SYNC_IN_FLIGHT_STATUSES))
                .limit(1)
            )
            payload_is_current = (
                payload_number == order.tracking_number
                and payload_carrier == current_carrier
            )
            if latest_job_id == job.id and payload_is_current:
                order.writeback_status = result_status
            elif newer_in_flight is not None:
                order.writeback_status = "pending"
    db.flush()
    return job


def pending_order_writeback_job_id(
    db: Session,
    order_id: UUID,
) -> str | None:
    """Return the newest queued writeback; older queued values are superseded."""

    return db.scalar(
        select(WSyncJob.job_id)
        .where(WSyncJob.target_type == "order_tracking")
        .where(WSyncJob.target_id == order_id)
        .where(WSyncJob.status == "pending")
        .order_by(WSyncJob.id.desc())
        .limit(1)
    )


def upsert_orders(db: Session, payloads: list[dict[str, Any]]) -> tuple[int, int]:
    """Upsert Woo-owned fields while preserving all console tracking fields."""

    created = 0
    updated = 0
    for payload in payloads:
        woo_order_id = int(payload["woo_order_id"])
        row = db.scalar(select(WOrder).where(WOrder.woo_order_id == woo_order_id))
        if row is None:
            row = WOrder(
                id=uuid4(),
                woo_order_id=woo_order_id,
                order_number=str(payload["order_number"]),
                woo_status=str(payload["woo_status"]),
            )
            db.add(row)
            created += 1
        else:
            updated += 1
        for field in (
            "order_number",
            "woo_status",
            "customer_name",
            "country",
            "total",
            "currency",
            "items_json",
            "placed_at",
        ):
            if field in payload:
                setattr(row, field, payload[field])
    db.flush()
    return created, updated


def list_orders(
    db: Session,
    *,
    filter_name: str,
    limit: int,
) -> tuple[dict[str, int], list[WOrder]]:
    all_rows = list(db.scalars(select(WOrder)).all())
    summary = {
        "pending": sum(row.tracking_status == "none" for row in all_rows),
        "in_transit": sum(row.tracking_status in SHIPPING_STATUSES for row in all_rows),
        "delivered": sum(row.tracking_status == "delivered" for row in all_rows),
        "exception": sum(row.tracking_status in EXCEPTION_STATUSES for row in all_rows),
    }
    query = select(WOrder)
    if filter_name == "pending":
        query = query.where(WOrder.tracking_status == "none")
    elif filter_name == "tracked":
        query = query.where(WOrder.tracking_status != "none")
    rows = list(
        db.scalars(
            query.order_by(
                WOrder.placed_at.desc().nulls_last(),
                WOrder.created_at.desc(),
            ).limit(limit)
        ).all()
    )
    return summary, rows


def _tracking_request_item(
    tracking_number: str,
    carrier_code: int | None,
) -> dict[str, Any]:
    item: dict[str, Any] = {"number": tracking_number}
    if carrier_code is not None:
        item["carrier"] = carrier_code
    return item


def register_tracking(
    db: Session,
    tracking_number: str,
    carrier_code: int | None,
) -> tuple[bool, str | None]:
    """Register a persisted tracking number; failures become a non-blocking warning."""

    try:
        key = track17_key(db)
        request_item = _tracking_request_item(tracking_number, carrier_code)
        db.rollback()
        response = _post_json(
            f"{_track17_base()}/track/v2.2/register",
            payload=[request_item],
            headers={"17token": key},
            timeout=TRACK17_TIMEOUT_SECONDS,
        )
        _accepted_tracking_record(response, tracking_number)
    except Exception as exc:  # noqa: BLE001 - number must remain saved
        return False, f"17TRACK 注册失败：{_remote_error(exc)}"
    return True, None


def get_tracking_info(
    db: Session,
    tracking_number: str,
    carrier_code: int | None,
) -> dict[str, Any]:
    key = track17_key(db)
    request_item = _tracking_request_item(tracking_number, carrier_code)
    db.rollback()
    response = _post_json(
        f"{_track17_base()}/track/v2.2/gettrackinfo",
        payload=[request_item],
        headers={"17token": key},
        timeout=TRACK17_TIMEOUT_SECONDS,
    )
    return _accepted_tracking_record(response, tracking_number)


def _accepted_tracking_record(
    response: dict[str, Any],
    tracking_number: str,
) -> dict[str, Any]:
    if response.get("code") not in (None, 0):
        raise ValueError(str(response.get("message") or f"API code {response.get('code')}"))
    data = response.get("data")
    if not isinstance(data, dict):
        raise ValueError("17TRACK 返回缺少 data")
    accepted = data.get("accepted")
    if isinstance(accepted, list):
        for candidate in accepted:
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("number") or "") == tracking_number:
                return candidate
    rejected = data.get("rejected")
    if isinstance(rejected, list):
        for candidate in rejected:
            if not isinstance(candidate, dict):
                continue
            error = candidate.get("error")
            if isinstance(error, dict):
                message = error.get("message") or error.get("code")
            else:
                message = error
            if message:
                raise ValueError(str(message))
    raise ValueError("17TRACK 未接受该运单号")


def normalize_tracking_status(value: object) -> str:
    normalized = "".join(
        character
        for character in str(value or "").lower()
        if character.isalnum()
    )
    return _TRACK17_STATUS_MAP.get(normalized, "not_found")


def _tracking_info(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("track_info")
    if isinstance(value, dict):
        return value
    value = record.get("track")
    return value if isinstance(value, dict) else record


def _event_time(event: dict[str, Any]) -> str | None:
    for field in ("time_utc", "time_iso", "time"):
        value = event.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    raw = event.get("time_raw")
    if isinstance(raw, dict):
        date = str(raw.get("date") or "").strip()
        time = str(raw.get("time") or "").strip()
        timezone = str(raw.get("timezone") or "").strip()
        combined = "T".join(part for part in (date, time) if part)
        return f"{combined}{timezone}" if combined else None
    return None


def _event_location(event: dict[str, Any]) -> str | None:
    location = event.get("location")
    if isinstance(location, str):
        return location.strip() or None
    if isinstance(location, dict):
        parts = [
            str(location.get(field) or "").strip()
            for field in ("country", "state", "city", "street", "postal_code")
        ]
        joined = ", ".join(part for part in parts if part)
        return joined or None
    return None


def _event_description(event: dict[str, Any]) -> str | None:
    translation = event.get("description_translation")
    if isinstance(translation, dict):
        value = str(translation.get("description") or "").strip()
        if value:
            return value
    value = str(event.get("description") or event.get("details") or "").strip()
    return value or None


def tracking_events(record: dict[str, Any]) -> list[dict[str, str | None]]:
    info = _tracking_info(record)
    candidates: list[dict[str, Any]] = []
    tracking = info.get("tracking")
    if isinstance(tracking, dict):
        providers = tracking.get("providers")
        if isinstance(providers, list):
            for provider in providers:
                if not isinstance(provider, dict):
                    continue
                events = provider.get("events")
                if isinstance(events, list):
                    candidates.extend(event for event in events if isinstance(event, dict))
    simple_events = info.get("events")
    if isinstance(simple_events, list):
        candidates.extend(event for event in simple_events if isinstance(event, dict))
    if not candidates:
        latest = info.get("latest_event")
        if isinstance(latest, dict):
            candidates.append(latest)

    normalized: list[dict[str, str | None]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    candidates.sort(
        key=lambda event: _parse_datetime(_event_time(event))
        or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    for event in candidates:
        item = {
            "time": _event_time(event),
            "location": _event_location(event),
            "description": _event_description(event),
        }
        signature = (item["time"], item["location"], item["description"])
        if signature in seen:
            continue
        seen.add(signature)
        normalized.append(item)
        if len(normalized) == 50:
            break
    return normalized


def _latest_status(record: dict[str, Any]) -> str:
    info = _tracking_info(record)
    latest = info.get("latest_status")
    if isinstance(latest, dict):
        return normalize_tracking_status(latest.get("status"))
    if latest is not None:
        return normalize_tracking_status(latest)
    return normalize_tracking_status(record.get("status"))


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _latest_tracking_time(
    record: dict[str, Any],
    events: list[dict[str, str | None]],
) -> datetime | None:
    info = _tracking_info(record)
    latest = info.get("latest_event")
    if isinstance(latest, dict):
        value = _event_time(latest)
        parsed = _parse_datetime(value)
        if parsed is not None:
            return parsed
    for event in events:
        parsed = _parse_datetime(event.get("time"))
        if parsed is not None:
            return parsed
    return None


def apply_tracking_record(
    order: WOrder,
    record: dict[str, Any],
    *,
    deduplicate: bool,
) -> bool:
    events = tracking_events(record)
    status = _latest_status(record)
    incoming_time = _latest_tracking_time(record, events)
    existing_events = (
        order.tracking_events_json
        if isinstance(order.tracking_events_json, list)
        else []
    )
    existing_time = _parse_datetime(order.last_tracking_update)
    if deduplicate:
        if incoming_time is not None and existing_time is not None:
            if incoming_time <= existing_time:
                return False
        if (
            incoming_time is None
            and existing_events == events
            and order.tracking_status == status
        ):
            return False
    order.tracking_status = status
    order.tracking_events_json = events
    order.last_tracking_update = incoming_time or _now()
    return True


def tracking_records_from_webhook(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("event") != "TRACKING_UPDATED":
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    accepted = data.get("accepted")
    if isinstance(accepted, list):
        return [item for item in accepted if isinstance(item, dict)]
    return [data] if data.get("number") else []


def verify_track17_signature(raw_body: bytes, sign: str | None, key: str) -> bool:
    """Verify SHA256_HEX(original UTF-8 body + '/' + API key)."""

    if not sign:
        return False
    normalized_sign = sign.strip().lower()
    if len(normalized_sign) != 64 or any(
        character not in "0123456789abcdef" for character in normalized_sign
    ):
        return False
    source = raw_body + b"/" + key.encode("utf-8")
    expected = hashlib.sha256(source).hexdigest()
    return secrets.compare_digest(
        expected.encode("ascii"),
        normalized_sign.encode("ascii"),
    )


def track17_sign_mode() -> str:
    mode = (os.getenv(TRACK17_SIGN_MODE_ENV, "sha256") or "sha256").strip().lower()
    return "off" if mode == "off" else "sha256"


# n8n contract (implemented by the operator, not this repository):
# 1. action=upsert_shipping_class calls Woo REST POST/PUT
#    /wp-json/wc/v3/products/shipping_classes, updates each named zone's
#    flat_rate class cost from zone_rates, then POSTs callback_url with
#    X-Job-Token.
# 2. action=order_tracking writes the manually entered number to Woo note/meta,
#    then POSTs callback_url with X-Job-Token.
# 3. a separate scheduled flow reads processing/completed Woo orders and POSTs
#    them to /w/orders/ingest with X-Ingest-Token.
# Reliability requirements for the W sync flow: reserve job_id before doing any
# work and treat duplicate job_id deliveries idempotently; callback only after
# the Woo write has finished; once a delivery is accepted, always callback with
# success or failed (including Woo-side errors).  If transport is uncertain,
# operators must inspect n8n and send the original callback rather than start a
# newer write for the same order.
# Runtime configuration: N8N_W_SYNC_WEBHOOK, W_ORDERS_INGEST_TOKEN,
# W_17TRACK_BASE_URL (defaults to https://api.17track.net); the track17 key is
# provided only through the central key-management binding for w.site_ops.
