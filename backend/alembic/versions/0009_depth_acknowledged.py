"""Local-knowledge depth acknowledgment on waypoints.

ENC DRVAL1 is the conservative minimum of a whole depth polygon — a skipper
who runs a creek daily can acknowledge a flagged waypoint, downgrading depth
violations to warnings (with an audit note). Charted land is never
acknowledgeable.

Revision ID: 0009
Revises: 0008
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE route_waypoints ADD COLUMN depth_acknowledged boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE route_waypoints DROP COLUMN IF EXISTS depth_acknowledged")
