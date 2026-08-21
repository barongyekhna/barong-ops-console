"""Mark the Jilin manufacturing organization as org_type='factory'.

``org_type`` was a dead field (the frontend always created orgs as ``store`` and
nothing read it). The M series gates on ``org_type == 'factory'`` rather than on
the organization name, so the real factory org needs the real type. Idempotent
and keyed by org_id; no-op on databases that don't have that org.

Revision ID: 20260821_03_factory_org_type
Revises: 20260821_02_mfg_permissions
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260821_03_factory_org_type"
down_revision: str | Sequence[str] | None = "20260821_02_mfg_permissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JILIN_FACTORY_ORG_ID = "org_d7497212d213498cbf0513d75e486c20"


def _organizations() -> sa.TableClause:
    return sa.table(
        "organizations",
        sa.column("org_id", sa.String()),
        sa.column("org_type", sa.String()),
    )


def upgrade() -> None:
    table = _organizations()
    op.execute(
        table.update()
        .where(table.c.org_id == JILIN_FACTORY_ORG_ID)
        .values(org_type="factory")
    )


def downgrade() -> None:
    table = _organizations()
    op.execute(
        table.update()
        .where(table.c.org_id == JILIN_FACTORY_ORG_ID)
        .values(org_type="store")
    )
