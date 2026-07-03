"""Persistent R-W category queue scheduler."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from r_system_v2.rw.core.models import IngestionRecord
from r_system_v2.rw.scheduler.token_distributor import TokenDistribution, TokenDistributor


@dataclass(frozen=True)
class CategorySchedulerReport:
    selected_categories: list[str]
    requested_tokens: int
    claimed: int
    queue_pending_before: int
    distribution: dict[str, Any]
    categories_claimed: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_categories": self.selected_categories,
            "requested_tokens": self.requested_tokens,
            "claimed": self.claimed,
            "queue_pending_before": self.queue_pending_before,
            "distribution": self.distribution,
            "categories_claimed": self.categories_claimed,
            "no_starvation": all(count > 0 for count in self.categories_claimed.values())
            if self.categories_claimed
            else True,
        }


class CategoryScheduler:
    """Claim ASIN tasks from ``enrich_queue`` with category-aware fairness."""

    def __init__(self, token_distributor: TokenDistributor | None = None) -> None:
        self.token_distributor = token_distributor or TokenDistributor()

    def pending_count(self, db: Session, selected_categories: list[str]) -> int:
        rows = self._pending_rows(db, selected_categories, limit=10_000)
        return len(rows)

    def purge_processed_products(self, db: Session) -> int:
        result = db.execute(
            text(
                """
                DELETE FROM enrich_queue
                WHERE EXISTS (
                  SELECT 1 FROM products_rw p WHERE p.asin = enrich_queue.asin
                )
                """
            )
        )
        return int(result.rowcount or 0)

    def release_stale_picks(self, db: Session, *, older_than_seconds: int) -> int:
        if db.get_bind().dialect.name == "postgresql":
            result = db.execute(
                text(
                    """
                    UPDATE enrich_queue
                    SET picked = false,
                        retry_count = retry_count + 1,
                        last_error = 'stale_pick_released',
                        picked_at = NULL
                    WHERE picked = true
                      AND picked_at < CURRENT_TIMESTAMP - (:older_than_seconds * INTERVAL '1 second')
                    """
                ),
                {"older_than_seconds": max(1, older_than_seconds)},
            )
            return int(result.rowcount or 0)
        result = db.execute(
            text(
                """
                UPDATE enrich_queue
                SET picked = false,
                    retry_count = retry_count + 1,
                    last_error = 'stale_pick_released',
                    picked_at = NULL
                WHERE picked = true
                  AND picked_at < datetime('now', '-' || :older_than_seconds || ' seconds')
                """
            ),
            {"older_than_seconds": max(1, older_than_seconds)},
        )
        return int(result.rowcount or 0)

    def claim(
        self,
        db: Session,
        *,
        selected_categories: list[str],
        requested_tokens: int,
    ) -> tuple[list[IngestionRecord], CategorySchedulerReport]:
        categories = list(dict.fromkeys(selected_categories))
        rows = self._pending_rows(db, categories, limit=max(100, requested_tokens * 20))
        distribution = self.token_distributor.distribute(categories, requested_tokens)
        records = self._choose_records(rows, distribution, requested_tokens)
        asins = [record.asin for record in records]
        if asins:
            self._mark_picked(db, asins)
        by_category: dict[str, int] = {}
        for record in records:
            category_id = record.category_id or "未分类"
            by_category[category_id] = by_category.get(category_id, 0) + 1
        return records, CategorySchedulerReport(
            selected_categories=categories,
            requested_tokens=requested_tokens,
            claimed=len(records),
            queue_pending_before=len(rows),
            distribution=distribution.to_dict(),
            categories_claimed=by_category,
        )

    def enqueue_discovered(
        self,
        db: Session,
        *,
        category_id: str,
        asins: list[str],
        marketplace: str = "US",
    ) -> int:
        inserted = 0
        for asin in asins:
            processed = db.execute(
                text("SELECT 1 FROM products_rw WHERE asin = :asin LIMIT 1"),
                {"asin": asin},
            ).first()
            if processed:
                continue
            result = db.execute(
                text(
                    """
                    INSERT INTO enrich_queue (
                      asin, marketplace, source_query, category_id,
                      category_path, picked, retry_count, enqueued_at
                    )
                    VALUES (
                      :asin, :marketplace, :source_query, :category_id,
                      :category_path, false, 0, CURRENT_TIMESTAMP
                    )
                    ON CONFLICT (asin) DO NOTHING
                    """
                ),
                {
                    "asin": asin,
                    "marketplace": marketplace,
                    "source_query": f"keepa_category:{category_id}",
                    "category_id": category_id,
                    "category_path": category_id,
                },
            )
            inserted += int(result.rowcount or 0)
        return inserted

    def _pending_rows(
        self,
        db: Session,
        selected_categories: list[str],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        categories = list(dict.fromkeys(selected_categories))
        if categories:
            statement = text(
                """
                SELECT asin, marketplace, source_query, category_id
                FROM enrich_queue q
                WHERE picked = false
                  AND (category_id IN :categories OR category_id IS NULL)
                  AND NOT EXISTS (
                    SELECT 1 FROM products_rw p WHERE p.asin = q.asin
                  )
                ORDER BY enqueued_at ASC, asin ASC
                LIMIT :limit
                """
            ).bindparams(bindparam("categories", expanding=True))
            params = {"categories": categories, "limit": limit}
        else:
            statement = text(
                """
                SELECT asin, marketplace, source_query, category_id
                FROM enrich_queue q
                WHERE picked = false
                  AND NOT EXISTS (
                    SELECT 1 FROM products_rw p WHERE p.asin = q.asin
                  )
                ORDER BY enqueued_at ASC, asin ASC
                LIMIT :limit
                """
            )
            params = {"limit": limit}
        return [dict(row) for row in db.execute(statement, params).mappings().all()]

    def _choose_records(
        self,
        rows: list[dict[str, Any]],
        distribution: TokenDistribution,
        requested_tokens: int,
    ) -> list[IngestionRecord]:
        grouped: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        for row in rows:
            grouped[str(row.get("category_id") or "未分类")].append(row)

        chosen: list[dict[str, Any]] = []
        seen: set[str] = set()
        for allocation in distribution.allocations:
            queue = grouped.get(allocation.category_id, deque())
            for _ in range(allocation.tokens):
                if not queue:
                    break
                row = queue.popleft()
                if str(row["asin"]) in seen:
                    continue
                chosen.append(row)
                seen.add(str(row["asin"]))

        categories = [allocation.category_id for allocation in distribution.allocations]
        for category_id in grouped:
            if category_id not in categories:
                categories.append(category_id)
        if "未分类" in grouped and "未分类" not in categories:
            categories.append("未分类")
        while len(chosen) < requested_tokens and categories:
            made_progress = False
            for category_id in categories:
                queue = grouped.get(category_id)
                if not queue:
                    continue
                row = queue.popleft()
                if str(row["asin"]) in seen:
                    continue
                chosen.append(row)
                seen.add(str(row["asin"]))
                made_progress = True
                if len(chosen) >= requested_tokens:
                    break
            if not made_progress:
                break

        return [
            IngestionRecord(
                asin=str(row["asin"]),
                source_query=str(row.get("source_query") or row["asin"]),
                marketplace=str(row.get("marketplace") or "US"),
                category_id=str(row["category_id"]) if row.get("category_id") else None,
            )
            for row in chosen
        ]

    def _mark_picked(self, db: Session, asins: list[str]) -> None:
        statement = text(
            """
            UPDATE enrich_queue
            SET picked = true,
                picked_at = CURRENT_TIMESTAMP
            WHERE asin IN :asins
            """
        ).bindparams(bindparam("asins", expanding=True))
        db.execute(statement, {"asins": asins})
