"""Per-segment propulsion constraint on waypoints.

leg_mode on a waypoint governs the SEGMENT between it and the next waypoint
(stored on the lower-numbered end, so it applies in both directions):
  auto  - engine decides by wind and preference
  motor - forced motor (marina channels, tight water, bridges)
  sail  - forced sail

Revision ID: 0005
Revises: 0004
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE route_waypoints ADD COLUMN leg_mode text NOT NULL DEFAULT 'auto' "
        "CHECK (leg_mode IN ('auto', 'motor', 'sail'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE route_waypoints DROP COLUMN IF EXISTS leg_mode")
