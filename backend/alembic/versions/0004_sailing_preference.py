"""Boat sailing preference + pointing ability.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE boats ADD COLUMN sailing_preference text NOT NULL DEFAULT 'sail' "
        "CHECK (sailing_preference IN ('sail', 'fastest', 'motor'))"
    )
    op.execute(
        "ALTER TABLE boats ADD COLUMN min_upwind_angle_deg numeric(4,1) NOT NULL DEFAULT 45"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE boats DROP COLUMN IF EXISTS sailing_preference")
    op.execute("ALTER TABLE boats DROP COLUMN IF EXISTS min_upwind_angle_deg")
