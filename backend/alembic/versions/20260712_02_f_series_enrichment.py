"""F 类目富化 — 运行台账 / 类目关键词 / 货源候选池

F 不复刻类目树（共享 K 的 k_category_google），这三张表是 F 自己的状态层：
选段爬取运行、每类目收割的关键词（跨运行去重累积）、1688 货源候选池
（红线只标记 automation_blocked，不毙掉，等人工放行进 K）。

Revision ID: 20260712_02_f_series_enrichment
Revises: 20260712_01_c19_native_access
Create Date: 2026-07-12
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20260712_02_f_series_enrichment"
down_revision: str | Sequence[str] | None = "20260712_01_c19_native_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNS = "f_enrichment_runs"
KEYWORDS = "f_category_keywords"
CANDIDATES = "f_category_candidates"


def upgrade() -> None:
    op.create_table(
        RUNS,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("selection_json", sa.JSON(), nullable=False),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default="queued"
        ),
        sa.Column(
            "categories_total", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("categories_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("keywords_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("serper_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("requested_by_username", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ("
            "'queued', 'running', 'succeeded', 'failed', "
            "'quota_exhausted', 'cancelled'"
            ")",
            name="ck_f_runs_valid_status",
        ),
    )
    op.create_index("ix_f_runs_status", RUNS, ["status"])
    op.create_index("ix_f_runs_created", RUNS, ["created_at"])

    op.create_table(
        KEYWORDS,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey(f"{RUNS}.id", name="fk_f_keywords_run_id_runs"),
            nullable=True,
        ),
        sa.Column("category_id", sa.String(length=32), nullable=False),
        sa.Column("category_path", sa.Text(), nullable=False),
        sa.Column("keyword_text", sa.String(length=512), nullable=False),
        sa.Column("keyword_type", sa.String(length=30), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=50),
            nullable=False,
            server_default="serper_search",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="candidate",
        ),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "keyword_type IN ('related', 'people_also_ask', 'organic_title')",
            name="ck_f_keywords_valid_type",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'approved', 'rejected')",
            name="ck_f_keywords_valid_status",
        ),
        sa.UniqueConstraint(
            "category_id",
            "keyword_text",
            name="uq_f_keywords_category_keyword",
        ),
    )
    op.create_index(
        "ix_f_keywords_category_status", KEYWORDS, ["category_id", "status"]
    )
    op.create_index("ix_f_keywords_run", KEYWORDS, ["run_id"])
    op.create_index("ix_f_keywords_created", KEYWORDS, ["created_at"])

    op.create_table(
        CANDIDATES,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey(f"{RUNS}.id", name="fk_f_candidates_run_id_runs"),
            nullable=True,
        ),
        sa.Column("category_id", sa.String(length=32), nullable=False),
        sa.Column("category_path", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column(
            "source", sa.String(length=50), nullable=False, server_default="manual"
        ),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column("price_cny", sa.Numeric(12, 2), nullable=True),
        sa.Column("moq", sa.Integer(), nullable=True),
        sa.Column("supplier_name", sa.String(length=255), nullable=True),
        sa.Column("weight_note", sa.String(length=255), nullable=True),
        sa.Column("red_flags_json", sa.JSON(), nullable=True),
        sa.Column(
            "automation_blocked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("k_product_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ("
            "'pending_review', 'approved', 'rejected', 'imported_to_k'"
            ")",
            name="ck_f_candidates_valid_status",
        ),
    )
    op.create_index(
        "ix_f_candidates_category_status", CANDIDATES, ["category_id", "status"]
    )
    op.create_index("ix_f_candidates_run", CANDIDATES, ["run_id"])
    op.create_index("ix_f_candidates_created", CANDIDATES, ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_f_candidates_created", table_name=CANDIDATES)
    op.drop_index("ix_f_candidates_run", table_name=CANDIDATES)
    op.drop_index("ix_f_candidates_category_status", table_name=CANDIDATES)
    op.drop_table(CANDIDATES)
    op.drop_index("ix_f_keywords_created", table_name=KEYWORDS)
    op.drop_index("ix_f_keywords_run", table_name=KEYWORDS)
    op.drop_index("ix_f_keywords_category_status", table_name=KEYWORDS)
    op.drop_table(KEYWORDS)
    op.drop_index("ix_f_runs_created", table_name=RUNS)
    op.drop_index("ix_f_runs_status", table_name=RUNS)
    op.drop_table(RUNS)
