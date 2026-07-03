"""R-W Keepa to store pipeline runner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Sequence

from r_system_v2.rw.ai.deepseek_screening import DeepSeekScreeningSkill
from r_system_v2.rw.core.keepa_buffer_queue import KeepaBufferQueue
from r_system_v2.rw.core.models import IngestionRecord
from r_system_v2.rw.core.rule_engine import RuleEngine
from r_system_v2.rw.providers.keepa_provider import MAX_REQUESTS_PER_MINUTE, KeepaProvider
from r_system_v2.rw.workers.keepa_worker import KeepaWorker, KeepaWorkerRunReport


@dataclass(frozen=True)
class PipelineRunReport:
    keepa: dict[str, object]
    processed_asins: list[str]
    failed_asins: dict[str, str]

    @property
    def processed(self) -> int:
        return int(self.keepa.get("processed", 0))

    @property
    def failed(self) -> int:
        return int(self.keepa.get("failed", 0))

    def to_dict(self) -> dict[str, object]:
        return {
            "keepa": self.keepa,
            "processed_asins": self.processed_asins,
            "failed_asins": self.failed_asins,
            "processed": self.processed,
            "failed": self.failed,
        }


class PipelineRunner:
    """Run Keepa fetch, rule scoring, buffered write, and queue finalization."""

    def __init__(
        self,
        *,
        provider: KeepaProvider,
        buffer_queue: KeepaBufferQueue,
        rule_engine: RuleEngine | None = None,
        deepseek_skill: DeepSeekScreeningSkill | None = None,
        deepseek_inline: bool = False,
        enforce_wall_clock_rate: bool = True,
    ) -> None:
        self.provider = provider
        self.buffer_queue = buffer_queue
        self.rule_engine = rule_engine or RuleEngine()
        self.deepseek_skill = deepseek_skill
        self.deepseek_inline = deepseek_inline
        self.enforce_wall_clock_rate = enforce_wall_clock_rate
        self.category_bestseller_cache: dict[str, dict[str, object]] = {}

    def run(self, records: Sequence[IngestionRecord]) -> PipelineRunReport:
        return asyncio.run(self.run_async(records))

    async def run_async(self, records: Sequence[IngestionRecord]) -> PipelineRunReport:
        worker = KeepaWorker(
            provider=self.provider,
            buffer_queue=self.buffer_queue,
            rule_engine=self.rule_engine,
            deepseek_skill=self.deepseek_skill,
            deepseek_inline=self.deepseek_inline,
            max_concurrency=MAX_REQUESTS_PER_MINUTE,
            enforce_wall_clock_rate=self.enforce_wall_clock_rate,
            category_bestseller_cache=self.category_bestseller_cache,
        )
        worker.enqueue(list(records))
        report = await worker.run_once(max_items=len(records))
        await self.buffer_queue.flush()
        failed = _failed_asins(report)
        requested = {record.asin for record in records}
        return PipelineRunReport(
            keepa=report.to_dict(),
            processed_asins=sorted(requested - set(failed)),
            failed_asins=failed,
        )


def _failed_asins(report: KeepaWorkerRunReport) -> dict[str, str]:
    failed: dict[str, str] = {}
    for error in report.errors:
        asin, _, message = error.partition(":")
        failed[asin.strip()] = message.strip() or error
    return failed
