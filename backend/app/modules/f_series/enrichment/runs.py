"""F 富化运行引擎：建运行 → 后台线程逐类目收割关键词 → 台账可轮询。

- 额度：共用 R-A 的日额度台账（``ra_provider_quota_usage``），Serper 花一次记
  一次；F 是用户手动触发，天然优先于 R-A 的夜巡消耗。额度见底 → 运行温和停在
  ``quota_exhausted``，已收割的全部保留，明天重跑同一选段自动去重续上。
- 执行：serper 调用快（秒级），单线程顺序爬完即可，不需要独立 worker 进程；
  线程用自己的 SessionLocal，HTTP 前 rollback 结束事务（防 idle-in-transaction）。
- 收尸：running 超过 RUN_STALE_MINUTES 无进度更新的运行按失联标 failed
  （惰性，list 时执行——和 P 派单队列同款语义）。
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from r_system_v2.core.secret_manager import SecretManager, SecretManagerError
from r_system_v2.ra.quota_ledger import (
    PROVIDER_SERPER,
    RAQuotaExhaustedError,
    try_consume,
)

from ....db.session import SessionLocal
from ....models.organization import OrganizationRecord
from ....models.user import User
from ....services.data_isolation import without_org_data_isolation
from . import constants as C
from . import serper_client
from . import sourcing
from .models import FCategoryKeyword, FEnrichmentRun
from .service import expand_selection, keyword_query_for_node

RUN_MODES = ("full", "keywords_only", "sourcing_only")


def _now() -> datetime:
    return datetime.now(UTC)


def _target_org_id(db: Session) -> str | None:
    return db.scalar(
        select(OrganizationRecord.org_id)
        .where(OrganizationRecord.org_name == C.TARGET_ORGANIZATION_NAME)
        .where(OrganizationRecord.status != "deleted")
        .limit(1)
    )


def _serper_key(db: Session) -> str:
    org_id = _target_org_id(db)
    if not org_id:
        raise RuntimeError(
            f"目标组织不存在：{C.TARGET_ORGANIZATION_NAME}（F 模块只挂国际贸易组织）"
        )
    try:
        key = SecretManager(db_session=db).get_key("serper", org_id)
    except SecretManagerError as exc:
        raise RuntimeError(f"Serper 密钥未配置：{exc}") from exc
    if not key:
        raise RuntimeError("Serper 密钥未配置（api-key-orchestration 里绑一把即可）。")
    return key


def create_run(
    db: Session,
    *,
    category_ids: list[str],
    user: User | None,
    mode: str = "full",
) -> tuple[FEnrichmentRun, list[dict[str, Any]]]:
    if mode not in RUN_MODES:
        raise ValueError(f"未知的运行模式：{mode}")
    nodes = expand_selection(db, category_ids)
    run = FEnrichmentRun(
        id=uuid4(),
        selection_json=[
            {"id": n["id"], "name": n["name"], "full_path": n["full_path"]}
            for n in nodes
        ],
        status="queued",
        mode=mode,
        categories_total=len(nodes),
        requested_by_user_id=user.id if user is not None else None,
        requested_by_username=user.username if user is not None else None,
    )
    db.add(run)
    db.flush()
    return run, nodes


def _existing_keyword_set(db: Session, category_id: str) -> set[str]:
    rows = db.execute(
        select(FCategoryKeyword.keyword_text).where(
            FCategoryKeyword.category_id == category_id
        )
    ).all()
    return {str(row[0]).strip().lower() for row in rows}


def execute_run(run_id: UUID) -> None:
    """线程入口：自己的 Session、逐节点爬取、进度落库。任何异常都收进 run。

    整体豁免 C18G 隔离：运行引擎只碰全局额度台账、共享类目树和 F 自己的
    无 org 列表——后台线程本来就没有隔离上下文，这里保证内联执行（测试）
    与线程执行行为一致。
    """
    with without_org_data_isolation(), SessionLocal() as db:
        run = db.get(FEnrichmentRun, run_id)
        if run is None or run.status not in ("queued", "running"):
            return
        run.status = "running"
        run.started_at = run.started_at or _now()
        db.commit()

        mode = run.mode or "keywords_only"
        do_keywords = mode in ("full", "keywords_only")
        do_sourcing = mode in ("full", "sourcing_only")
        node_errors: list[str] = []
        # 兜底 except 收下的「这个节点炸了」，与 channel_note / 降级提示分开记。
        # 只有它才是判「这趟到底成没成」的依据（2026-09-04）。
        hard_failures: list[str] = []

        api_key = ""
        if do_keywords:
            try:
                api_key = _serper_key(db)
            except Exception as exc:  # noqa: BLE001 - 密钥/组织问题直接失败收账
                db.rollback()
                run = db.get(FEnrichmentRun, run_id)
                run.status = "failed"
                run.error = str(exc)[:500]
                run.finished_at = _now()
                db.commit()
                return

        provider = None
        org_id = ""
        if do_sourcing:
            # 图搜接力的种子图靠 Serper：sourcing_only 模式也要钥匙。
            # 拿不到只跳过接力段（词搜照跑），不毙运行。
            # 冷进程首跑时编排层惰性导入可达数秒，事务空转会被 8s 闸掐线
            # ——先清事务，失败重试一次（第二次走热路径，毫秒级）。
            if not api_key:
                for attempt in (1, 2):
                    try:
                        db.rollback()
                        api_key = _serper_key(db)
                        break
                    except Exception:  # noqa: BLE001
                        db.rollback()
                        if attempt == 2:
                            node_errors.append(
                                "图搜接力已跳过：Serper 密钥获取失败（词搜段照常）"
                            )
            try:
                org_id = _target_org_id(db) or ""
                if not org_id:
                    raise sourcing.FSourcingUnavailableError(
                        f"目标组织不存在：{C.TARGET_ORGANIZATION_NAME}"
                    )
                provider = sourcing.build_provider(db, org_id=org_id)
            except sourcing.FSourcingUnavailableError as exc:
                if mode == "sourcing_only":
                    db.rollback()
                    run = db.get(FEnrichmentRun, run_id)
                    run.status = "failed"
                    run.error = str(exc)[:500]
                    run.finished_at = _now()
                    db.commit()
                    return
                # full 模式优雅降级：词照收，找货段跳过并记提示。
                do_sourcing = False
                node_errors.append(f"1688 找货段已跳过：{str(exc)[:160]}")

        nodes = list(run.selection_json or [])
        for node in nodes[run.categories_done :]:
            # ---- 关键词段（Serper）----
            keywords: list[dict[str, Any]] = []
            if do_keywords:
                try:
                    try_consume(db, PROVIDER_SERPER)  # 内部自带 commit
                except RAQuotaExhaustedError as exc:
                    run = db.get(FEnrichmentRun, run_id)
                    run.status = "quota_exhausted"
                    run.error = str(exc)
                    run.finished_at = _now()
                    db.commit()
                    return
                try:
                    # Serper 最长 12s：先结束打开的 SQL 事务（R-A 踩过的坑）。
                    db.rollback()
                    raw = serper_client.serper_search(
                        api_key=api_key,
                        query=keyword_query_for_node(node),
                    )
                    keywords = serper_client.extract_keywords(raw)
                except Exception as exc:  # noqa: BLE001 - 单节点失败不阻断整批
                    message = f"{node.get('name')}: {str(exc)[:120]}"
                    node_errors.append(message)
                    hard_failures.append(message)

            run = db.get(FEnrichmentRun, run_id)
            if run is None or run.status == "cancelled":
                db.rollback()
                return
            seen = _existing_keyword_set(db, str(node["id"]))
            added = 0
            for item in keywords:
                if item["keyword_text"].strip().lower() in seen:
                    continue
                seen.add(item["keyword_text"].strip().lower())
                db.add(
                    FCategoryKeyword(
                        id=uuid4(),
                        run_id=run.id,
                        category_id=str(node["id"]),
                        category_path=str(node["full_path"]),
                        keyword_text=item["keyword_text"],
                        keyword_type=item["keyword_type"],
                        rank=item.get("rank"),
                        source="serper_search",
                        status="candidate",
                    )
                )
                added += 1
            if do_keywords:
                run.serper_calls += 1
            run.keywords_found += added
            db.commit()

            # ---- 找货段 v2（画像驱动，F 独立总闸在 sourcing 内逐产品记账）----
            if do_sourcing and provider is not None:
                try:
                    # DeepSeek 画像 + 逐产品 1688 词搜都是慢 HTTP：先结束事务。
                    db.rollback()
                    result = sourcing.source_category(
                        db,
                        node=node,
                        provider=provider,
                        org_id=org_id,
                        run_id=run_id,
                        serper_api_key=api_key or None,
                    )
                    run = db.get(FEnrichmentRun, run_id)
                    if run is None or run.status == "cancelled":
                        db.rollback()
                        return
                    run.candidates_found += result["candidates_created"]
                    run.alibaba_calls += result["calls_used"]
                    note = result.get("channel_note")
                    if note and note not in node_errors:
                        node_errors.append(note)
                    for warning in result.get("warnings") or []:
                        message = f"{node.get('name')} 找货降级: {str(warning)[:140]}"
                        if message not in node_errors:
                            node_errors.append(message)
                except RAQuotaExhaustedError as exc:
                    db.rollback()
                    run = db.get(FEnrichmentRun, run_id)
                    run.status = "quota_exhausted"
                    run.error = str(exc)
                    run.finished_at = _now()
                    db.commit()
                    return
                except sourcing.FSourcingNoMatchError as exc:
                    # 无新增 ≠ 没花钱：调用数随异常带回，台账不丢账。
                    db.rollback()
                    node_errors.append(
                        f"{node.get('name')} 找货: {str(exc)[:160]}"
                    )
                    run = db.get(FEnrichmentRun, run_id)
                    if run is None or run.status == "cancelled":
                        db.rollback()
                        return
                    run.alibaba_calls += exc.calls_used
                except Exception as exc:  # noqa: BLE001 - 单节点失败不阻断整批
                    db.rollback()
                    message = f"{node.get('name')} 找货: {str(exc)[:160]}"
                    node_errors.append(message)
                    hard_failures.append(message)
                    run = db.get(FEnrichmentRun, run_id)
                    if run is None or run.status == "cancelled":
                        db.rollback()
                        return

            run.categories_done += 1
            if node_errors:
                run.error = "；".join(node_errors)[:500]
            db.commit()

        run = db.get(FEnrichmentRun, run_id)
        if run is not None and run.status == "running":
            # 跑完循环 ≠ 成功。2026-09-04：画像抢建撞唯一键把找货打死，
            # 异常被逐节点兜底吃掉，台账照报「完成」，用户看着 0 候选以为跑通了。
            # 炸了又一无所获，就老实说失败；有产出但带报错，状态留 succeeded、
            # 报错原文照挂（前端把这种标成「完成·有报错」）。
            produced = (run.keywords_found or 0) + (run.candidates_found or 0)
            run.status = "failed" if hard_failures and produced == 0 else "succeeded"
            run.error = "；".join(node_errors)[:500] if node_errors else None
            run.finished_at = _now()
            db.commit()


def start_run(run_id: UUID) -> None:
    """默认后台 daemon 线程；F_ENRICHMENT_INLINE=1 时同步执行（测试用）。"""
    if os.getenv("F_ENRICHMENT_INLINE") == "1":
        execute_run(run_id)
        return
    threading.Thread(
        target=execute_run,
        args=(run_id,),
        name=f"f-enrichment-{run_id.hex[:8]}",
        daemon=True,
    ).start()


def reap_stale_runs(db: Session) -> None:
    """惰性收尸：running 超时无进度更新 → failed（线程随进程重启而消失的场景）。"""
    deadline = _now() - timedelta(minutes=C.RUN_STALE_MINUTES)
    stale = db.scalars(
        select(FEnrichmentRun)
        .where(FEnrichmentRun.status.in_(["queued", "running"]))
        .where(FEnrichmentRun.updated_at < deadline)
    ).all()
    for run in stale:
        run.status = "failed"
        run.error = (
            f"运行超过 {C.RUN_STALE_MINUTES} 分钟无进度更新，按失联处理"
            "（可重新对同一选段发起，已收割的关键词自动去重续上）"
        )
        run.finished_at = _now()
    if stale:
        db.flush()
