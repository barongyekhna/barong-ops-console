"""Batch persistence for R-W Keepa ingestion results."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from r_system_v2.rw.core.models import PipelineResult


metadata = sa.MetaData()

products_rw = sa.Table(
    "products_rw",
    metadata,
    sa.Column("asin", sa.Text, primary_key=True),
    sa.Column("marketplace", sa.Text),
    sa.Column("source_query", sa.Text),
    sa.Column("title", sa.Text),
    sa.Column("brand", sa.Text),
    sa.Column("category", sa.Text),
    sa.Column("category_id", sa.Text),
    sa.Column("category_path", sa.Text),
    sa.Column("price", sa.Numeric(10, 2)),
    sa.Column("bsr", sa.Integer),
    sa.Column("reviews", sa.Integer),
    sa.Column("seller_count", sa.Integer),
    sa.Column("landed_cost", sa.Numeric(10, 2)),
    sa.Column("est_net_margin", sa.Numeric(8, 4)),
    sa.Column("brand_share", sa.Numeric(8, 4)),
    sa.Column("price_trend", sa.Text),
    sa.Column("rating", sa.Numeric(3, 1)),
    sa.Column("skill_score", sa.Integer),
    sa.Column("state", sa.Text),
    sa.Column("rule_reject_reason", sa.Text),
    sa.Column("features", sa.JSON),
    sa.Column("last_keepa_pull", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)

rule_results = sa.Table(
    "rule_results",
    metadata,
    sa.Column("asin", sa.Text),
    sa.Column("decision", sa.Text),
    sa.Column("reasons", sa.JSON),
    sa.Column("checks", sa.JSON),
    sa.Column("evaluated_at", sa.DateTime(timezone=True)),
)

ai_evaluations = sa.Table(
    "ai_evaluations",
    metadata,
    sa.Column("asin", sa.Text),
    sa.Column("layer", sa.Text),
    sa.Column("model", sa.Text),
    sa.Column("score", sa.Integer),
    sa.Column("verdict", sa.Text),
    sa.Column("payload", sa.JSON),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


@dataclass(frozen=True)
class BatchWriteReport:
    batch_size: int
    product_upserts: int
    rule_results_inserted: int
    ai_evaluations_inserted: int
    transactions: int
    statements: int
    per_item_commits: bool = False

    @property
    def active(self) -> bool:
        return self.batch_size > 0 and self.transactions == 1 and not self.per_item_commits

    def to_dict(self) -> dict[str, int | bool]:
        return {
            "batch_size": self.batch_size,
            "product_upserts": self.product_upserts,
            "rule_results_inserted": self.rule_results_inserted,
            "ai_evaluations_inserted": self.ai_evaluations_inserted,
            "transactions": self.transactions,
            "statements": self.statements,
            "per_item_commits": self.per_item_commits,
            "active": self.active,
        }


class SQLAlchemyBatchWriter:
    """Writes one flushed Keepa batch using bulk SQL inside one transaction."""

    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self.session_factory = session_factory
        self.total_batches = 0
        self.total_products = 0
        self.total_transactions = 0

    def write(self, results: Sequence[PipelineResult]) -> BatchWriteReport:
        if self.session_factory is None:
            raise RuntimeError("session_factory is required for write()")
        db = self.session_factory()
        try:
            report = self.write_batch(db, results)
            return report
        finally:
            db.close()

    def write_batch(
        self,
        db: Session,
        results: Sequence[PipelineResult],
    ) -> BatchWriteReport:
        if not results:
            return BatchWriteReport(
                batch_size=0,
                product_upserts=0,
                rule_results_inserted=0,
                ai_evaluations_inserted=0,
                transactions=0,
                statements=0,
            )

        product_rows = [_product_row(result) for result in results]
        rule_rows = [_rule_row(result) for result in results]
        ai_rows = [
            row
            for result in results
            if result.deepseek_screening is not None
            for row in [_ai_row(result)]
        ]

        statements = 0
        transaction = nullcontext() if db.in_transaction() else db.begin()
        with transaction:
            self._bulk_upsert_products(db, product_rows)
            statements += 1
            if rule_rows:
                db.execute(sa.insert(rule_results), rule_rows)
                statements += 1
            if ai_rows:
                db.execute(sa.insert(ai_evaluations), ai_rows)
                statements += 1

        self.total_batches += 1
        self.total_products += len(product_rows)
        self.total_transactions += 1
        return BatchWriteReport(
            batch_size=len(results),
            product_upserts=len(product_rows),
            rule_results_inserted=len(rule_rows),
            ai_evaluations_inserted=len(ai_rows),
            transactions=1,
            statements=statements,
        )

    def _bulk_upsert_products(
        self,
        db: Session,
        rows: Sequence[dict[str, Any]],
    ) -> None:
        dialect_name = db.get_bind().dialect.name
        if dialect_name == "postgresql":
            statement = pg_insert(products_rw).values(list(rows))
        elif dialect_name == "sqlite":
            statement = sqlite_insert(products_rw).values(list(rows))
        else:
            db.execute(sa.insert(products_rw), list(rows))
            return

        excluded = statement.excluded
        update_columns = {
            column.name: getattr(excluded, column.name)
            for column in products_rw.c
            if column.name not in {"asin", "created_at"}
        }
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[products_rw.c.asin],
                set_=update_columns,
            )
        )


class InMemoryBatchWriter:
    """Fast test writer that preserves batch semantics without a database."""

    def __init__(self) -> None:
        self.products: dict[str, dict[str, Any]] = {}
        self.rule_results: list[dict[str, Any]] = []
        self.ai_evaluations: list[dict[str, Any]] = []
        self.reports: list[BatchWriteReport] = []
        self.transaction_count = 0
        self.max_batch_size = 0

    def write(self, results: Sequence[PipelineResult]) -> BatchWriteReport:
        product_rows = [_product_row(result) for result in results]
        rule_rows = [_rule_row(result) for result in results]
        ai_rows = [
            row
            for result in results
            if result.deepseek_screening is not None
            for row in [_ai_row(result)]
        ]
        for row in product_rows:
            self.products[str(row["asin"])] = row
        self.rule_results.extend(rule_rows)
        self.ai_evaluations.extend(ai_rows)
        self.transaction_count += 1 if results else 0
        self.max_batch_size = max(self.max_batch_size, len(results))
        report = BatchWriteReport(
            batch_size=len(results),
            product_upserts=len(product_rows),
            rule_results_inserted=len(rule_rows),
            ai_evaluations_inserted=len(ai_rows),
            transactions=1 if results else 0,
            statements=sum(1 for rows in (product_rows, rule_rows, ai_rows) if rows),
        )
        self.reports.append(report)
        return report

    def to_dict(self) -> dict[str, int | bool]:
        return {
            "products": len(self.products),
            "rule_results": len(self.rule_results),
            "ai_evaluations": len(self.ai_evaluations),
            "transactions": self.transaction_count,
            "max_batch_size": self.max_batch_size,
            "per_item_commits": False,
            "active": self.transaction_count > 0,
        }


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _state_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _product_row(result: PipelineResult) -> dict[str, Any]:
    product = result.product
    return {
        "asin": product.asin,
        "marketplace": product.marketplace,
        "source_query": product.source_query,
        "title": product.title,
        "brand": product.brand,
        "category": product.category,
        "category_id": product.category_id,
        "category_path": ">".join(product.category_path),
        "price": product.price,
        "bsr": product.bsr,
        "reviews": product.reviews,
        "seller_count": product.seller_count,
        "landed_cost": product.landed_cost,
        "est_net_margin": product.est_net_margin,
        "brand_share": product.brand_share,
        "price_trend": product.price_trend,
        "rating": product.rating,
        "skill_score": product.skill_score,
        "state": _state_value(product.state),
        "rule_reject_reason": product.rule_reject_reason,
        "features": dict(product.features),
        "last_keepa_pull": _parse_datetime(result.keepa_data.fetched_at),
        "created_at": _parse_datetime(product.created_at),
        "updated_at": _parse_datetime(product.updated_at),
    }


def _rule_row(result: PipelineResult) -> dict[str, Any]:
    rule = result.rule_evaluation
    return {
        "asin": rule.asin,
        "decision": _state_value(rule.decision),
        "reasons": list(rule.reasons),
        "checks": dict(rule.checks),
        "evaluated_at": _parse_datetime(rule.evaluated_at),
    }


def _ai_row(result: PipelineResult) -> dict[str, Any]:
    if result.deepseek_screening is None:
        raise ValueError("deepseek_screening is required")
    screening = result.deepseek_screening
    return {
        "asin": screening.asin,
        "layer": "deepseek",
        "model": "deepseek-chat",
        "score": screening.score,
        "verdict": screening.verdict,
        "payload": dict(screening.strict_json),
        "created_at": _parse_datetime(screening.evaluated_at),
    }
