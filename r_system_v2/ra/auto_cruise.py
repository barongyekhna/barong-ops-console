"""R-A auto-cruise scheduler: the daemon that makes selection fully automatic.

Runs inside the r-a-worker container next to RaProfitJobWorker and does four
things on a loop:

1. 每日巡库：每天自动创建一个 auto_cruise 任务（无关键词），由现有的
   RaProfitJobWorker 认领执行，跑到当日 1688 图搜预算耗尽为止。
2. 存量夜扫：夜间用 DeepSeek 批量给未打分的存量产品打 prescreen 分，
   只花 DeepSeek 的钱，为白天的付费额度排出优先队列。
3. 误杀抽检：每天抽取若干被初筛 cut 的产品，用免费的 1688 官方词搜
   做利润探针；误杀率过高时写告警。
4. Opus 复核：RA_OPUS_DAILY_REVIEW=true 时，把当日 GPT 放行的 top N
   交给 Opus 做最终把关。

All actions are idempotent per-day and guarded by env switches so the daemon
can be safely restarted at any time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import os
import time
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from r_system_v2.ra.auto_profit import _ra_profit_not_processed_sql
from r_system_v2.ra.events import emit_event
from r_system_v2.ra.exchange_rate import get_usd_cny_quote
from r_system_v2.ra.job_queue import create_auto_profit_job
from r_system_v2.ra.prescreen import (
    ensure_prescreen_schema,
    prescreen_daily_stats,
    prescreen_mode,
    record_audit_result,
    run_prescreen_for_product,
    sample_cut_products_for_audit,
)
from r_system_v2.ra.profit_engine import ProfitInput, calculate_us_profit, decimal_value
from r_system_v2.ra.quota_ledger import (
    PROVIDER_1688_CPS_IMAGE_SEARCH,
    PROVIDER_1688_IMAGE_SEARCH,
    remaining_today,
)
from r_system_v2.ra.supplier_keyword_skill import build_supplier_keyword_profile


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except ValueError:
        return default


class RaAutoCruiseScheduler:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        org_id: str,
        without_isolation: Callable[[], Any],
        poll_seconds: float = 60.0,
    ) -> None:
        self.session_factory = session_factory
        self.org_id = org_id
        self.without_isolation = without_isolation
        self.poll_seconds = max(15.0, poll_seconds)

    # ---------------------------------------------------------------- loop
    def run_forever(
        self,
        *,
        should_stop: Callable[[], bool],
        log: Callable[[str], None],
    ) -> None:
        log(
            "R-A auto-cruise scheduler started "
            f"enabled={self.enabled()} night_scan={self.night_scan_enabled()} "
            f"audit={self.audit_enabled()}"
        )
        while not should_stop():
            try:
                self.tick(log=log)
            except Exception as exc:  # pragma: no cover - daemon guardrail.
                log(f"R-A auto-cruise error={exc}")
            time.sleep(self.poll_seconds)

    def tick(self, *, log: Callable[[str], None]) -> None:
        if not self.org_id:
            return
        if self.enabled():
            self._ensure_daily_cruise_job(log=log)
        if self.night_scan_enabled() and self._in_night_window():
            self._night_scan_batch(log=log)
        if self.audit_enabled() and self._in_audit_window():
            self._daily_audit(log=log)
        # Opus 每日 top10 已按用户要求移除——改为分组页手动「Opus 建议」按钮。
        self._process_expansion_jobs(log=log)

    # ------------------------------------------------------------ switches
    def enabled(self) -> bool:
        return _env_flag("RA_AUTO_CRUISE_ENABLED", default=True)

    def night_scan_enabled(self) -> bool:
        return _env_flag("RA_NIGHT_SCAN_ENABLED", default=True) and prescreen_mode() != "off"

    def audit_enabled(self) -> bool:
        return _env_flag("RA_PRESCREEN_AUDIT_ENABLED", default=True)

    def _in_night_window(self) -> bool:
        start = _env_int("RA_NIGHT_SCAN_START_HOUR", 18, 0, 23)
        end = _env_int("RA_NIGHT_SCAN_END_HOUR", 23, 0, 23)
        hour = datetime.now(UTC).hour
        if start <= end:
            return start <= hour <= end
        return hour >= start or hour <= end

    def _in_audit_window(self) -> bool:
        return datetime.now(UTC).hour == _env_int("RA_AUDIT_HOUR", 1, 0, 23)

    # ----------------------------------------------------- daily cruise job
    def _ensure_daily_cruise_job(self, *, log: Callable[[str], None]) -> None:
        with self.session_factory() as db:
            with self.without_isolation():
                # 24 小时连轴转：只要没有活跃/预算暂停的巡库任务就建下一个。
                # completed/partial 不再阻挡——跑完立刻续建，直到预算耗尽(paused)。
                row = db.execute(
                    text(
                        """
                        SELECT run_id, status
                        FROM ra_selection_runs
                        WHERE org_id = :org_id
                          AND channel = 'profit_auto'
                          AND COALESCE(filters->>'auto_cruise', 'false') = 'true'
                          AND status IN ('queued', 'running', 'paused')
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"org_id": self.org_id},
                ).mappings().first()
                if row is not None:
                    # 有活跃巡库任务，或预算已尽等次日自动续跑——不重复建。
                    return
                # 防空转：上一个巡库 run 一个产品都没处理（仓库暂无新品）时冷却 30 分钟。
                idle_row = db.execute(
                    text(
                        """
                        SELECT 1
                        FROM ra_selection_runs
                        WHERE org_id = :org_id
                          AND channel = 'profit_auto'
                          AND COALESCE(filters->>'auto_cruise', 'false') = 'true'
                          AND status IN ('completed', 'partial')
                          AND COALESCE((counts->>'processed_products')::int, 0) = 0
                          AND COALESCE(finished_at, updated_at)
                              > CURRENT_TIMESTAMP - INTERVAL '30 minutes'
                        LIMIT 1
                        """
                    ),
                    {"org_id": self.org_id},
                ).first()
                if idle_row is not None:
                    return
                failed_today = db.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM ra_selection_runs
                        WHERE org_id = :org_id
                          AND channel = 'profit_auto'
                          AND COALESCE(filters->>'auto_cruise', 'false') = 'true'
                          AND created_at::date = CURRENT_DATE
                          AND status = 'failed'
                        """
                    ),
                    {"org_id": self.org_id},
                ).scalar()
                if int(failed_today or 0) >= 3:
                    # 防失败风暴：当天连挂 3 次就停手，等人排查。
                    return
                cross_remaining = remaining_today(db, PROVIDER_1688_IMAGE_SEARCH)
                cps_remaining = remaining_today(db, PROVIDER_1688_CPS_IMAGE_SEARCH)
                remaining = (cross_remaining or 0) + (cps_remaining or 0)
                keyword_first = (
                    os.getenv("RA_1688_SEARCH_STRATEGY", "keyword_first")
                    .strip()
                    .lower()
                    != "image_first"
                )
                if not keyword_first and remaining <= 0:
                    # 图搜优先模式才受图搜额度约束；词搜优先时词搜免费不限量，
                    # 双通道图搜（跨境+分销）都尽时只影响兜底（顺延止损兜住）。
                    return
                payload = create_auto_profit_job(
                    db,
                    org_id=self.org_id,
                    query="",
                    asin_limit=_env_int("RA_CRUISE_BATCH_SIZE", 20, 1, 20),
                    run_ai_chain=True,
                    selection_channel="both",
                    triggered_by="auto_cruise",
                    auto_cruise=True,
                    target_profit_pass=_env_int("RA_CRUISE_TARGET_PASS", 50, 1, 50),
                    max_products_per_job=_env_int(
                        "RA_CRUISE_MAX_PRODUCTS",
                        400,
                        1,
                        2000,
                    ),
                )
                emit_event(
                    db,
                    org_id=self.org_id,
                    run_id=str(payload.get("run_id") or ""),
                    stage="run_status",
                    verdict="cruise_created",
                    detail={"source": "auto_cruise", "remaining_image_search": remaining},
                )
                log(f"R-A auto-cruise created daily run run_id={payload.get('run_id')}")

    # --------------------------------------------------------- night scan
    def _night_scan_batch(self, *, log: Callable[[str], None]) -> None:
        batch = _env_int("RA_NIGHT_SCAN_BATCH", 40, 1, 200)
        daily_cap = _env_int("RA_NIGHT_SCAN_DAILY", 1000, 1, 20000)
        with self.session_factory() as db:
            with self.without_isolation():
                ensure_prescreen_schema(db)
                scanned_today = db.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM ra_prescreen
                        WHERE org_id = :org_id
                          AND created_at::date = CURRENT_DATE
                        """
                    ),
                    {"org_id": self.org_id},
                ).scalar()
                if int(scanned_today or 0) >= daily_cap:
                    return
                unscored = self._load_unscored_products(db, limit=batch)
                if not unscored:
                    return
        scanned = 0
        for product in unscored[:batch]:
            with self.session_factory() as db:
                with self.without_isolation():
                    try:
                        result = run_prescreen_for_product(
                            db,
                            org_id=self.org_id,
                            product=product,
                            run_id=None,
                        )
                        if not result.get("cached"):
                            scanned += 1
                    except Exception as exc:
                        log(f"R-A night-scan prescreen failed asin={product.get('asin')} error={exc}")
                        return
        if scanned:
            log(f"R-A night-scan scored {scanned} products")

    def _load_unscored_products(
        self,
        db: Session,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """直接从 products_rw 取"未打过 prescreen 分"的存量产品。"""
        rows = db.execute(
            text(
                f"""
                SELECT p.asin, p.title, p.title_zh, p.category, p.category_path,
                       p.brand, p.price, p.features, p.skill_score, p.image_url
                FROM products_rw p
                WHERE COALESCE(LOWER(CAST(p.state AS TEXT)), '') NOT LIKE '%reject%'
                  AND {_ra_profit_not_processed_sql(db)}
                  AND NOT EXISTS (
                    SELECT 1 FROM ra_prescreen pp
                    WHERE pp.org_id = :org_id
                      AND UPPER(pp.asin) = UPPER(CAST(p.asin AS TEXT))
                      AND pp.created_at > CURRENT_TIMESTAMP - INTERVAL '30 days'
                  )
                ORDER BY p.skill_score DESC NULLS LAST, p.updated_at DESC NULLS LAST
                LIMIT :limit
                """
            ),
            {"org_id": self.org_id, "limit": max(1, min(limit, 200))},
        ).mappings()
        return [dict(row) for row in rows]

    # -------------------------------------------------------------- audit
    def _daily_audit(self, *, log: Callable[[str], None]) -> None:
        sample_size = _env_int("RA_AUDIT_SAMPLE_SIZE", 20, 1, 50)
        with self.session_factory() as db:
            with self.without_isolation():
                samples = sample_cut_products_for_audit(
                    db,
                    org_id=self.org_id,
                    limit=sample_size,
                )
        if not samples:
            return
        false_kills = 0
        audited = 0
        for sample in samples:
            outcome = self._audit_probe(sample, log=log)
            if outcome is None:
                continue
            audited += 1
            if outcome:
                false_kills += 1
        if audited == 0:
            return
        rate = false_kills / audited
        with self.session_factory() as db:
            with self.without_isolation():
                stats = prescreen_daily_stats(db, org_id=self.org_id)
                emit_event(
                    db,
                    org_id=self.org_id,
                    run_id=None,
                    stage="audit",
                    verdict="alert" if rate > 0.05 else "ok",
                    detail={
                        "audited": audited,
                        "false_kills": false_kills,
                        "false_kill_rate": round(rate, 4),
                        "daily_stats": stats,
                        "note": (
                            "初筛误杀率超过 5%，建议放宽阈值或检查 prompt。"
                            if rate > 0.05
                            else "初筛误杀率在阈值内。"
                        ),
                    },
                )
        log(
            "R-A prescreen audit done "
            f"audited={audited} false_kills={false_kills} rate={rate:.2%}"
        )

    def _audit_probe(
        self,
        sample: dict[str, Any],
        *,
        log: Callable[[str], None],
    ) -> bool | None:
        """免费词搜利润探针。True=疑似误杀, False=cut 合理, None=无法判定。"""
        asin = str(sample.get("asin") or "").strip().upper()
        try:
            with self.session_factory() as db:
                with self.without_isolation():
                    product = db.execute(
                        text(
                            """
                            SELECT asin, title, title_zh, category, price, features, image_url
                            FROM products_rw
                            WHERE UPPER(asin) = :asin
                            LIMIT 1
                            """
                        ),
                        {"asin": asin},
                    ).mappings().first()
                    if product is None:
                        record_audit_result(
                            db,
                            prescreen_id=str(sample["id"]),
                            audit_status="skipped_no_product",
                        )
                        return None
                    product = dict(product)
                    provider = self._official_provider(db)
                    if provider is None:
                        record_audit_result(
                            db,
                            prescreen_id=str(sample["id"]),
                            audit_status="skipped_no_provider",
                        )
                        return None
                    keyword_profile = build_supplier_keyword_profile(
                        None, org_id=None, product=product
                    )
            offers = provider.search_offers_keyword_only(
                product=product,
                keyword_profile=keyword_profile,
                limit=5,
            )
            prices = [
                decimal_value(offer.unit_price_cny)
                for offer in offers
                if decimal_value(offer.unit_price_cny) is not None
            ]
            with self.session_factory() as db:
                with self.without_isolation():
                    if not prices:
                        record_audit_result(
                            db,
                            prescreen_id=str(sample["id"]),
                            audit_status="no_supplier_found",
                        )
                        return False
                    quote = get_usd_cny_quote()
                    features = product.get("features")
                    if isinstance(features, str):
                        import json as _json

                        try:
                            features = _json.loads(features)
                        except _json.JSONDecodeError:
                            features = {}
                    if not isinstance(features, dict):
                        features = {}
                    result = calculate_us_profit(
                        ProfitInput(
                            asin=asin,
                            sell_price_usd=decimal_value(product.get("price")),
                            fba_fee_usd=decimal_value(features.get("fba_fee_usd")),
                            unit_price_cny=min(prices),
                            domestic_shipping_cny=None,
                            actual_weight_kg=(
                                decimal_value(features.get("package_weight_g")) / Decimal(1000)
                                if decimal_value(features.get("package_weight_g")) is not None
                                else None
                            ),
                            length_cm=None,
                            width_cm=None,
                            height_cm=None,
                            exchange_rate_usd_cny=quote.rate,
                        )
                    )
                    margin = result.gross_margin
                    false_kill = bool(result.verdict == "pass")
                    record_audit_result(
                        db,
                        prescreen_id=str(sample["id"]),
                        audit_status="false_kill" if false_kill else "cut_confirmed",
                        audit_detail={
                            "gross_margin": float(margin) if margin is not None else None,
                            "verdict": result.verdict,
                            "supplier_count": len(prices),
                            "min_price_cny": float(min(prices)),
                            "probe": "official_keyword_search",
                        },
                    )
                    return false_kill
        except Exception as exc:
            log(f"R-A audit probe failed asin={asin} error={exc}")
            try:
                with self.session_factory() as db:
                    with self.without_isolation():
                        record_audit_result(
                            db,
                            prescreen_id=str(sample["id"]),
                            audit_status="probe_error",
                            audit_detail={"error": str(exc)[:300]},
                        )
            except Exception:
                pass
            return None

    def _official_provider(self, db: Session):
        try:
            from r_system_v2.ra.supplier_discovery import _supplier_api_provider

            provider = _supplier_api_provider(db, org_id=self.org_id)
        except Exception:
            return None
        if getattr(provider, "provider_name", "") == "mock_1688_api":
            return None
        if not hasattr(provider, "search_offers_keyword_only"):
            return None
        return provider

    # -------------------------------------------------- category expansion
    def _process_expansion_jobs(self, *, log: Callable[[str], None]) -> None:
        """认领并执行「1688 扩品」后台任务（每 tick 最多一个）。"""
        from r_system_v2.ra.category_expansion import (
            claim_next_expansion,
            run_expansion,
        )

        with self.session_factory() as db:
            with self.without_isolation():
                job = claim_next_expansion(db, org_id=self.org_id)
        if job is None:
            return
        log(f"R-A expansion claimed id={job.get('id')} asin={job.get('asin')}")
        try:
            with self.session_factory() as db:
                with self.without_isolation():
                    run_expansion(db, org_id=self.org_id, job=job)
            log(f"R-A expansion done id={job.get('id')}")
        except Exception as exc:
            log(f"R-A expansion failed id={job.get('id')} error={exc}")
            try:
                with self.session_factory() as db:
                    with self.without_isolation():
                        from r_system_v2.ra.category_expansion import mark_expansion_failed

                        mark_expansion_failed(db, job_id=str(job["id"]), error=str(exc))
            except Exception:
                pass
