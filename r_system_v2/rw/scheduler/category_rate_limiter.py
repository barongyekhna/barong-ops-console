"""Balanced Keepa token allocator across selected categories."""

from __future__ import annotations

from dataclasses import dataclass


TOTAL_RATE_PER_MINUTE = 20


@dataclass(frozen=True)
class CategoryAllocation:
    category_id: str
    per_minute: int
    window_total: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "category_id": self.category_id,
            "per_minute": self.per_minute,
            "window_total": self.window_total,
        }


@dataclass(frozen=True)
class CategoryRatePlan:
    total_rate_per_min: int
    window_minutes: int
    total_batch: int
    allocations: list[CategoryAllocation]
    no_overuse: bool
    no_starvation: bool
    balanced: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "total_rate_per_min": self.total_rate_per_min,
            "window_minutes": self.window_minutes,
            "total_batch": self.total_batch,
            "allocations": [allocation.to_dict() for allocation in self.allocations],
            "no_overuse": self.no_overuse,
            "no_starvation": self.no_starvation,
            "balanced": self.balanced,
        }


class CategoryRateLimiter:
    """Distribute Keepa's 20/min budget evenly across categories."""

    def __init__(self, total_rate_per_min: int = TOTAL_RATE_PER_MINUTE) -> None:
        self.total_rate_per_min = min(total_rate_per_min, TOTAL_RATE_PER_MINUTE)

    def plan(self, category_ids: list[str], window_minutes: int) -> CategoryRatePlan:
        unique_categories = list(dict.fromkeys(category_ids))
        window_minutes = max(1, int(window_minutes))
        total_batch = self.total_rate_per_min * window_minutes
        if not unique_categories:
            return CategoryRatePlan(
                total_rate_per_min=self.total_rate_per_min,
                window_minutes=window_minutes,
                total_batch=0,
                allocations=[],
                no_overuse=True,
                no_starvation=True,
                balanced=True,
            )

        base = total_batch // len(unique_categories)
        remainder = total_batch % len(unique_categories)
        allocations: list[CategoryAllocation] = []
        for index, category_id in enumerate(unique_categories):
            window_total = base + (1 if index < remainder else 0)
            per_minute = window_total // window_minutes
            allocations.append(
                CategoryAllocation(
                    category_id=category_id,
                    per_minute=per_minute,
                    window_total=window_total,
                )
            )
        totals = [allocation.window_total for allocation in allocations]
        return CategoryRatePlan(
            total_rate_per_min=self.total_rate_per_min,
            window_minutes=window_minutes,
            total_batch=sum(totals),
            allocations=allocations,
            no_overuse=sum(totals) <= total_batch,
            no_starvation=all(total > 0 for total in totals),
            balanced=(max(totals) - min(totals) <= 1) if totals else True,
        )
