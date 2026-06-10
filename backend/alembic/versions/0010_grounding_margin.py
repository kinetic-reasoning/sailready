"""Per-boat grounding margin.

Charted depths are below MLLW and tide predictions are above MLLW, so
available-water math is datum-correct with zero margin. The margin is the
skipper's comfort padding (negative tides beyond the mean, wind setdown,
sounding error) — a per-boat choice, not an engine constant.

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE boats ADD COLUMN grounding_margin_ft numeric(3,1) NOT NULL DEFAULT 1.0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE boats DROP COLUMN IF EXISTS grounding_margin_ft")
