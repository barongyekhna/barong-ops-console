"""Async Keepa worker that buffers DB persistence."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
from r_system_v2.rw.core.keepa_buffer_queue import KeepaBufferQueue
from r_system_v2.rw.core.models import (
    DeepSeekScreening,
    IngestionRecord,
    PipelineResult,
    ProductState,
    RuleDecision,
    utc_now_iso,
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
        self._lock = asyncio.Lock()

    async def wait_turn(self) -> None:
        if not self.enforce_wall_clock:
            return
        async with self._lock:
            now = time.monotonic()
            if now < self._next_allowed_at:
                await asyncio.sleep(self._next_allowed_at - now)
            self._next_allowed_at = time.monotonic() + self._interval_seconds


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
        self.rate_limiter = AsyncKeepaRateLimiter(
            rate_limit_per_min,
            enforce_wall_clock=enforce_wall_clock_rate,
        )
        self.rate_limit_per_min = self.rate_limiter.rate_limit_per_min
        self.max_concurrency = min(max(1, max_concurrency), self.rate_limit_per_min)
        self.queue: asyncio.Queue[IngestionRecord] = asyncio.Queue()

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
            product.category_id = record.category_id
            product.category_path = [record.category_id, product.category]
        if self.deepseek_skill is not None and hasattr(self.deepseek_skill, "translate_title"):
            translation = await asyncio.to_thread(
                self.deepseek_skill.translate_title,
                product.title,
            )
            if getattr(translation, "title_zh", None):
                product.title_zh = translation.title_zh
                product.title_zh_source = translation.source
                product.title_zh_updated_at = utc_now_iso()
            product.features["title_translation"] = (
                translation.to_dict()
                if hasattr(translation, "to_dict")
                else {"source": "deepseek_translation_unavailable"}
            )
        transitions.append(ProductState.ENRICHED.value)

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
                if deepseek_screening.passed:
                    product.features["score_action"] = "pass"
                    product.transition_to(ProductState.AI1_PASSED)
                else:
                    product.features["score_action"] = "reject"
                    product.transition_to(ProductState.AI1_REJECTED)
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
