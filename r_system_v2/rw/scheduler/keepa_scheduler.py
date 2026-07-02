"""Token-aware Keepa enrichment scheduler."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from r_system_v2.rw.core.models import IngestionRecord, PipelineResult
from r_system_v2.rw.providers.keepa_provider import (
    MAX_REQUESTS_PER_MINUTE,
    NO_BURST_MODE,
    QUEUE_BASED_INGESTION_REQUIRED,
    KeepaProvider,
)
from r_system_v2.rw.scheduler.category_rate_limiter import CategoryRateLimiter, CategoryRatePlan


@dataclass
class SchedulerRunReport:
    rate_limit_per_min: int
    token_budget: int
    queued_before: int
    tokens_left: int
    refill_in_sec: int
    refill_aware: bool = True
    no_burst_mode: bool = NO_BURST_MODE
    queue_based_ingestion: bool = QUEUE_BASED_INGESTION_REQUIRED
    provider_mock_mode: bool = False
    processed: int = 0
    failed: int = 0
    retries: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict[str, int | bool | list[str]]:
        return {
            "rate_limit_per_min": self.rate_limit_per_min,
            "token_budget": self.token_budget,
            "queued_before": self.queued_before,
            "tokens_left": self.tokens_left,
            "refill_in_sec": self.refill_in_sec,
            "refill_aware": self.refill_aware,
            "no_burst_mode": self.no_burst_mode,
            "queue_based_ingestion": self.queue_based_ingestion,
            "provider_mock_mode": self.provider_mock_mode,
            "processed": self.processed,
            "failed": self.failed,
            "retries": self.retries,
            "errors": self.errors,
            "success": self.success,
        }


class KeepaScheduler:
    """Queue-based scheduler capped at the production 20 token/min rate."""

    def __init__(
        self,
        provider: KeepaProvider,
        processor: Callable[[IngestionRecord], PipelineResult],
        rate_limit_per_min: int = MAX_REQUESTS_PER_MINUTE,
        max_retries: int = 2,
        category_rate_limiter: CategoryRateLimiter | None = None,
    ) -> None:
        self.provider = provider
        self.processor = processor
        self.rate_limit_per_min = min(rate_limit_per_min, MAX_REQUESTS_PER_MINUTE)
        self.max_retries = max_retries
        self.category_rate_limiter = category_rate_limiter or CategoryRateLimiter(
            self.rate_limit_per_min,
        )
        self.queue: deque[IngestionRecord] = deque()
        self.results: list[PipelineResult] = []

    def enqueue(self, records: list[IngestionRecord]) -> None:
        self.queue.extend(records)

    def enqueue_by_category(
        self,
        records_by_category: dict[str, list[IngestionRecord]],
        *,
        window_minutes: int = 10,
    ) -> CategoryRatePlan:
        plan = self.category_rate_limiter.plan(
            list(records_by_category.keys()),
            window_minutes,
        )
        for allocation in plan.allocations:
            records = records_by_category.get(allocation.category_id, [])
            self.queue.extend(records[: allocation.window_total])
        return plan

    def run_once(self) -> SchedulerRunReport:
        status = self.provider.status()
        token_budget = min(
            MAX_REQUESTS_PER_MINUTE,
            self.rate_limit_per_min,
            int(status.tokens_left),
            len(self.queue),
        )
        report = SchedulerRunReport(
            rate_limit_per_min=self.rate_limit_per_min,
            token_budget=token_budget,
            queued_before=len(self.queue),
            tokens_left=int(status.tokens_left),
            refill_in_sec=int(status.refill_in_sec),
            provider_mock_mode=bool(status.mock_mode),
        )

        if token_budget <= 0:
            return report

        for _ in range(token_budget):
            record = self.queue.popleft()
            result = self._process_with_retry(record, report)
            if result:
                self.results.append(result)
                report.processed += 1
            else:
                report.failed += 1

        return report

    def _process_with_retry(
        self,
        record: IngestionRecord,
        report: SchedulerRunReport,
    ) -> PipelineResult | None:
        attempts = 0
        while attempts <= self.max_retries:
            try:
                return self.processor(record)
            except Exception as exc:  # pragma: no cover - exercised by failure audits.
                attempts += 1
                if attempts <= self.max_retries:
                    report.retries += 1
                    continue
                report.errors.append(f"{record.asin}: {exc}")
                return None
        return None
