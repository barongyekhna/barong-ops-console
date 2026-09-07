"""Async Keepa worker that buffers DB persistence."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field

from r_system_v2.rw.ai.deepseek_screening import (
    DeepSeekScreeningSkill,
    deepseek_reject_code,
)
from r_system_v2.rw.category.category_tree import is_holiday_category_id
from r_system_v2.rw.core.keepa_buffer_queue import KeepaBufferQueue
from r_system_v2.rw.core.models import (
    DeepSeekScreening,
    IngestionRecord,
    PipelineResult,
    ProductState,
    RuleDecision,
    RuleEvaluation,
)
from r_system_v2.rw.core.rule_engine import RuleEngine
from r_system_v2.rw.processor.feature_extractor import extract_product_features
from r_system_v2.rw.providers.keepa_provider import MAX_REQUESTS_PER_MINUTE, KeepaProvider


@dataclass(frozen=True)
class KeepaWorkerRunReport:
    queued_before: int
    processed: int
    failed: int
    rate_limit_per_min: int
    max_concurrency: int
    async_fetch: bool = True
    non_blocking: bool = True
    queue_results: bool = True
    per_request_db_update: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict[str, int | bool | list[str]]:
        return {
            "queued_before": self.queued_before,
            "processed": self.processed,
            "failed": self.failed,
            "rate_limit_per_min": self.rate_limit_per_min,
            "max_concurrency": self.max_concurrency,
            "async_fetch": self.async_fetch,
            "non_blocking": self.non_blocking,
            "queue_results": self.queue_results,
            "per_request_db_update": self.per_request_db_update,
            "errors": self.errors,
            "success": self.success,
        }


class AsyncKeepaRateLimiter:
    """Awaitable no-burst limiter for Keepa's 20/min production cap."""

    def __init__(
        self,
        rate_limit_per_min: int = MAX_REQUESTS_PER_MINUTE,
        *,
        enforce_wall_clock: bool = True,
    ) -> None:
        self.rate_limit_per_min = min(rate_limit_per_min, MAX_REQUESTS_PER_MINUTE)
        self.enforce_wall_clock = enforce_wall_clock
        self._interval_seconds = 60.0 / self.rate_limit_per_min
        self._next_allowed_at = 0.0
        self._lock = threading.Lock()

    async def wait_turn(self) -> None:
        if not self.enforce_wall_clock:
            return
        sleep_for = self._reserve_delay()
        if sleep_for > 0:
            await asyncio.sleep(sleep_for)

    def wait_turn_sync(self) -> None:
        if not self.enforce_wall_clock:
            return
        sleep_for = self._reserve_delay()
        if sleep_for > 0:
            time.sleep(sleep_for)

    def _reserve_delay(self) -> float:
        with self._lock:
            now = time.monotonic()
            sleep_for = max(0.0, self._next_allowed_at - now)
            base = max(now, self._next_allowed_at)
            self._next_allowed_at = base + self._interval_seconds
            return sleep_for


class KeepaWorker:
    """Non-blocking Keepa fetcher that flushes results through a batch buffer."""

    def __init__(
        self,
        *,
        provider: KeepaProvider,
        buffer_queue: KeepaBufferQueue,
        rule_engine: RuleEngine | None = None,
        deepseek_skill: DeepSeekScreeningSkill | None = None,
        deepseek_inline: bool = True,
        rate_limit_per_min: int = MAX_REQUESTS_PER_MINUTE,
        max_concurrency: int = MAX_REQUESTS_PER_MINUTE,
        enforce_wall_clock_rate: bool = True,
        rate_limiter: AsyncKeepaRateLimiter | None = None,
        category_bestseller_cache: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.provider = provider
        self.buffer_queue = buffer_queue
        self.rule_engine = rule_engine or RuleEngine()
        self.deepseek_inline = deepseek_inline
        self.deepseek_skill = (
            deepseek_skill
            if deepseek_skill is not None
            else DeepSeekScreeningSkill()
            if deepseek_inline
            else None
        )
        self.rate_limiter = rate_limiter or AsyncKeepaRateLimiter(
            rate_limit_per_min,
            enforce_wall_clock=enforce_wall_clock_rate,
        )
        self.rate_limit_per_min = self.rate_limiter.rate_limit_per_min
        self.max_concurrency = min(max(1, max_concurrency), self.rate_limit_per_min)
        self.queue: asyncio.Queue[IngestionRecord] = asyncio.Queue()
        self.category_bestseller_cache = (
            category_bestseller_cache if category_bestseller_cache is not None else {}
        )

    def enqueue(self, records: list[IngestionRecord]) -> None:
        for record in records:
            self.queue.put_nowait(record)

    async def run_once(self, max_items: int | None = None) -> KeepaWorkerRunReport:
        queued_before = self.queue.qsize()
        limit = min(
            queued_before,
            max_items if max_items is not None else self.rate_limit_per_min,
            self.rate_limit_per_min,
        )
        errors: list[str] = []
        if limit <= 0:
            return KeepaWorkerRunReport(
                queued_before=queued_before,
                processed=0,
                failed=0,
                rate_limit_per_min=self.rate_limit_per_min,
                max_concurrency=self.max_concurrency,
            )

        records = [self.queue.get_nowait() for _ in range(limit)]
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def guarded_process(record: IngestionRecord) -> PipelineResult | str:
            async with semaphore:
                try:
                    return await self._process_record(record)
                except Exception as exc:  # pragma: no cover - audit path.
                    return f"{record.asin}: {exc}"

        results = await asyncio.gather(*(guarded_process(record) for record in records))
        processed = 0
        failed = 0
        for result in results:
            if isinstance(result, str):
                failed += 1
                errors.append(result)
            else:
                await self.buffer_queue.put(result)
                processed += 1

        await self.buffer_queue.flush_due()
        return KeepaWorkerRunReport(
            queued_before=queued_before,
            processed=processed,
            failed=failed,
            rate_limit_per_min=self.rate_limit_per_min,
            max_concurrency=self.max_concurrency,
            errors=errors,
        )

    async def drain(self) -> list[KeepaWorkerRunReport]:
        reports: list[KeepaWorkerRunReport] = []
        while not self.queue.empty():
            reports.append(await self.run_once())
        await self.buffer_queue.flush()
        return reports

    async def _process_record(self, record: IngestionRecord) -> PipelineResult:
        start = time.perf_counter()
        transitions = [record.state.value]
        await self.rate_limiter.wait_turn()
        keepa_data = await self.provider.fetch_product_async(
            record.asin,
            source_query=record.source_query,
        )
        product = extract_product_features(record.source_query, keepa_data)
        if record.category_id:
            product.features["selected_keepa_category_id"] = record.category_id
            product.features["selected_keepa_category_path"] = [
                record.category_id,
                *product.category_path,
            ]
            product.category_id = record.category_id
            self._apply_category_bestseller_rank(record.category_id, product)
        # 2026-09-07 起 R-W 不再逐个产品调模型翻译标题：抓回来的绝大多数会被
        # 规则/初筛/R-A 筛掉，逐个翻是白烧 token。中文名改由 R-A 抽词那一次
        # DeepSeek 调用顺带产出（只对走到付费搜索的产品），见
        # r_system_v2/ra/profit_service.persist_title_zh。
        transitions.append(ProductState.ENRICHED.value)

        if is_holiday_category_id(record.category_id):
            return self._process_holiday_product(
                record=record,
                keepa_data=keepa_data,
                product=product,
                transitions=transitions,
                started_at=start,
            )

        rule_evaluation = self.rule_engine.evaluate(product)
        deepseek_screening: DeepSeekScreening | None = None
        if rule_evaluation.decision is RuleDecision.RULE_PASSED:
            product.transition_to(ProductState.RULE_PASSED)
            transitions.append(product.state.value)
            if self.deepseek_inline:
                if self.deepseek_skill is None:
                    raise RuntimeError("deepseek_skill_required")
                product.features["deepseek_mode"] = "inline"
                deepseek_screening = self.deepseek_skill.evaluate(product)
                product.skill_score = deepseek_screening.score
                product.features["deepseek_score"] = deepseek_screening.score
                product.features["deepseek_verdict"] = deepseek_screening.verdict
                product.features["deepseek_reason"] = deepseek_screening.top_reason
                product.features["score_reason"] = deepseek_screening.top_reason
                if deepseek_screening.verdict == "cut":
                    product.rule_reject_reason = deepseek_reject_code(
                        deepseek_screening.top_reason,
                    )
                    product.features["score_action"] = "reject"
                    product.features["ra_review_required"] = False
                    product.transition_to(ProductState.AI1_REJECTED)
                else:
                    product.features["score_action"] = "pending_review"
                    product.features["ra_review_required"] = True
                    product.transition_to(ProductState.AI1_PASSED)
            else:
                product.features["deepseek_mode"] = "cron_pending"
                product.features["score_action"] = "pending_review"
        else:
            product.rule_reject_reason = ",".join(rule_evaluation.reasons)
            product.features["score_action"] = "reject"
            product.transition_to(ProductState.REJECTED)

        transitions.append(product.state.value)
        return PipelineResult(
            asin=record.asin,
            ingestion=record,
            keepa_data=keepa_data,
            product=product,
            rule_evaluation=rule_evaluation,
            deepseek_screening=deepseek_screening,
            transitions=transitions,
            latency_ms=round((time.perf_counter() - start) * 1000, 3),
        )

    def _apply_category_bestseller_rank(self, category_id: str, product) -> None:
        cached = self.category_bestseller_cache.get(category_id)
        parent_rank = _positive_int_feature(product.features, "parent_category_rank")
        parent_name = _string_feature(product.features, "parent_category_name")
        subcategory_rank = _positive_int_feature(product.features, "subcategory_rank")
        if cached is None and parent_rank is not None and subcategory_rank == 1:
            cached = {
                "rank": parent_rank,
                "category": parent_name or product.category,
                "asin": product.asin,
            }
            self.category_bestseller_cache[category_id] = cached
        if cached is None:
            return
        product.features["bestseller_parent_rank"] = cached.get("rank")
        product.features["bestseller_parent_category"] = cached.get("category")
        product.features["category_bestseller_asin"] = cached.get("asin")

    def _process_holiday_product(
        self,
        *,
        record: IngestionRecord,
        keepa_data,
        product,
        transitions: list[str],
        started_at: float,
    ) -> PipelineResult:
        monthly_sales = _positive_int_feature(
            product.features,
            "monthly_sales",
        ) or _positive_int_feature(product.features, "monthly_sales_estimate") or 0
        score = _holiday_sales_score(monthly_sales=monthly_sales, bsr=product.bsr)
        product.features["holiday_mode"] = "sales_only"
        product.features["hard_rule_exempt"] = True
        product.features["deepseek_mode"] = "skipped_holiday_sales_only"
        product.features["deepseek_score"] = score
        product.features["deepseek_verdict"] = "keep" if score >= 75 else "hold"
        product.features["deepseek_reason"] = "节日产品按销量模式处理，不套用普通硬门规则。"
        product.features["holiday_sales_score"] = score
        rule_evaluation = RuleEvaluation(
            asin=product.asin,
            decision=RuleDecision.RULE_PASSED,
            reasons=[],
            checks={"holiday_sales_only": True},
        )
        product.transition_to(ProductState.RULE_PASSED)
        transitions.append(product.state.value)
        product.skill_score = score
        product.features["score_action"] = "pending_review"
        product.features["score_reason"] = product.features["deepseek_reason"]
        product.features["ra_review_required"] = True
        product.transition_to(ProductState.AI1_PASSED)
        transitions.append(product.state.value)
        return PipelineResult(
            asin=record.asin,
            ingestion=record,
            keepa_data=keepa_data,
            product=product,
            rule_evaluation=rule_evaluation,
            deepseek_screening=None,
            transitions=transitions,
            latency_ms=round((time.perf_counter() - started_at) * 1000, 3),
        )


def _positive_int_feature(features: dict[str, object], key: str) -> int | None:
    value = features.get(key)
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _string_feature(features: dict[str, object], key: str) -> str | None:
    value = features.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _holiday_sales_score(*, monthly_sales: int, bsr: int) -> int:
    if monthly_sales >= 1_000:
        return 95
    if monthly_sales >= 500:
        return 86
    if monthly_sales >= 100:
        return 76
    if monthly_sales >= 50:
        return 66
    if bsr and bsr <= 10_000:
        return 70
    if bsr and bsr <= 50_000:
        return 62
    return 45
