"""Persist the full score report on trip_scores so it can be re-viewed.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE trip_scores ADD COLUMN feasible boolean NOT NULL DEFAULT true",
    "ALTER TABLE trip_scores ADD COLUMN legs jsonb NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE trip_scores ADD COLUMN conditions_summary jsonb NOT NULL DEFAULT '{}'::jsonb",
    "ALTER TABLE trip_scores ADD COLUMN outbound_arrival timestamptz",
    "ALTER TABLE trip_scores ADD COLUMN return_home timestamptz",
]


def upgrade() -> None:
    for s in STATEMENTS:
        op.execute(s)


def downgrade() -> None:
    for col in ["feasible", "legs", "conditions_summary", "outbound_arrival", "return_home"]:
        op.execute(f"ALTER TABLE trip_scores DROP COLUMN IF EXISTS {col}")
