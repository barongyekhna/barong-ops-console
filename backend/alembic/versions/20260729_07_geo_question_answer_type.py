"""Allow the repeatable `question_answer` guide type.

A cluster used to hold one of each singleton type, so after five pieces it was
"full" and new buyer questions had nowhere to live — generation refused outright.
Terrain monitoring (M4) showed the winnable ground is exactly those specific
questions, and each deserves its own page, so the type must repeat.

Revision ID: 20260729_07_geo_question_answer_type
Revises: 20260729_06_b2b_widget_jobs
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260729_07_geo_question_answer_type"
down_revision: str | Sequence[str] | None = "20260729_06_b2b_widget_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_geo_content_items_ck_geo_items_valid_type"
_OLD = (
    "item_type IN ('hub', 'how_it_works', 'comparison', 'scenario', 'qa', "
    "'product_spotlight')"
)
_NEW = (
    "item_type IN ('hub', 'how_it_works', 'comparison', 'scenario', 'qa', "
    "'question_answer', 'product_spotlight')"
)


# Raw SQL on purpose: the stored name is already the conv()-expanded one, and
# passing it back through op.drop_constraint makes the naming convention wrap it a
# second time (ck_geo_content_items_ck_geo_content_items_… → no such constraint).
def upgrade() -> None:
    op.execute(
        f"ALTER TABLE geo_content_items DROP CONSTRAINT IF EXISTS {_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE geo_content_items ADD CONSTRAINT {_CONSTRAINT} CHECK ({_NEW})"
    )


def downgrade() -> None:
    # Rows of the new type would violate the old rule; drop them first so the
    # downgrade cannot fail halfway.
    op.execute("DELETE FROM geo_content_items WHERE item_type = 'question_answer'")
    op.execute(
        f"ALTER TABLE geo_content_items DROP CONSTRAINT IF EXISTS {_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE geo_content_items ADD CONSTRAINT {_CONSTRAINT} CHECK ({_OLD})"
    )
