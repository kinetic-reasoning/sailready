"""Home port on the user profile.

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN home_port_name text")
    op.execute("ALTER TABLE users ADD COLUMN home_port_lat numeric(9,5)")
    op.execute("ALTER TABLE users ADD COLUMN home_port_lon numeric(9,5)")


def downgrade() -> None:
    for col in ("home_port_name", "home_port_lat", "home_port_lon"):
        op.execute(f"ALTER TABLE users DROP COLUMN IF EXISTS {col}")
