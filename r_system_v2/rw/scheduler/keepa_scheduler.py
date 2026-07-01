"""Token-aware Keepa enrichment scheduler simulation."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from r_system_v2.rw.core.models import IngestionRecord, PipelineResult
from r_system_v2.rw.providers.keepa_provider import KeepaProvider


@dataclass
class SchedulerRunReport:
    rate_limit_per_min: int
    token_budget: int
    queued_before: int
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
            "processed": self.processed,
            "failed": self.failed,
            "retries": self.retries,
            "errors": self.errors,
            "success": self.success,
        }


class KeepaScheduler:
    """Queue-based scheduler with 20/min default token simulation."""

    def __init__(
        self,
        provider: KeepaProvider,
        processor: Callable[[IngestionRecord], PipelineResult],
        rate_limit_per_min: int = 20,
        max_retries: int = 2,
    ) -> None:
        self.provider = provider
        self.processor = processor
        self.rate_limit_per_min = rate_limit_per_min
        self.max_retries = max_retries
        self.queue: deque[IngestionRecord] = deque()
        self.results: list[PipelineResult] = []

    def enqueue(self, records: list[IngestionRecord]) -> None:
        self.queue.extend(records)

    def run_once(self) -> SchedulerRunReport:
        status = self.provider.status()
        token_budget = min(self.rate_limit_per_min, int(status.tokens_left), len(self.queue))
        report = SchedulerRunReport(
            rate_limit_per_min=self.rate_limit_per_min,
            token_budget=token_budget,
            queued_before=len(self.queue),
        )

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

