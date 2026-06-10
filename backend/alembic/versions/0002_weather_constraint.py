"""Add 'weather' to constraint_type enum (rain / thunderstorm scoring).

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE constraint_type ADD VALUE IF NOT EXISTS 'weather'")


def downgrade() -> None:
    pass  # Postgres cannot remove enum values; harmless to leave
