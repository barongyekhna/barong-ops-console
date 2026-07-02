"""Keepa token distribution across selected R-W categories."""

from __future__ import annotations

from dataclasses import dataclass

from r_system_v2.rw.providers.keepa_provider import MAX_REQUESTS_PER_MINUTE


@dataclass(frozen=True)
class TokenAllocation:
    category_id: str
    tokens: int

    def to_dict(self) -> dict[str, int | str]:
        return {
            "category_id": self.category_id,
            "tokens": self.tokens,
        }


@dataclass(frozen=True)
class TokenDistribution:
    total_tokens: int
    allocated_tokens: int
    allocations: list[TokenAllocation]
    next_cursor: int
    balanced: bool
    no_starvation: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "total_tokens": self.total_tokens,
            "allocated_tokens": self.allocated_tokens,
            "allocations": [allocation.to_dict() for allocation in self.allocations],
            "next_cursor": self.next_cursor,
            "balanced": self.balanced,
            "no_starvation": self.no_starvation,
        }


class TokenDistributor:
    """Even round-robin distributor for Keepa's 20/min budget."""

    def __init__(self, max_tokens_per_minute: int = MAX_REQUESTS_PER_MINUTE) -> None:
        self.max_tokens_per_minute = max(1, min(max_tokens_per_minute, MAX_REQUESTS_PER_MINUTE))
        self.cursor = 0

    def distribute(
        self,
        category_ids: list[str],
        requested_tokens: int,
    ) -> TokenDistribution:
        categories = list(dict.fromkeys(category_id for category_id in category_ids if category_id))
        total_tokens = max(0, min(int(requested_tokens), self.max_tokens_per_minute))
        if total_tokens == 0 or not categories:
            return TokenDistribution(
                total_tokens=total_tokens,
                allocated_tokens=0,
                allocations=[],
                next_cursor=self.cursor,
                balanced=True,
                no_starvation=True,
            )

        base = total_tokens // len(categories)
        remainder = total_tokens % len(categories)
        rotated = categories[self.cursor % len(categories) :] + categories[: self.cursor % len(categories)]
        token_map = dict.fromkeys(categories, base)
        for category_id in rotated[:remainder]:
            token_map[category_id] += 1

        allocations = [
            TokenAllocation(category_id=category_id, tokens=token_map[category_id])
            for category_id in categories
            if token_map[category_id] > 0
        ]
        self.cursor = (self.cursor + remainder) % len(categories)
        counts = [allocation.tokens for allocation in allocations]
        return TokenDistribution(
            total_tokens=total_tokens,
            allocated_tokens=sum(counts),
            allocations=allocations,
            next_cursor=self.cursor,
            balanced=(max(counts) - min(counts) <= 1) if counts else True,
            no_starvation=total_tokens < len(categories) or all(count > 0 for count in counts),
        )
