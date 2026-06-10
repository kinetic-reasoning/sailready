"""Server-side cache of NOAA ENC rendered tiles.

NOAA's Maritime Chart Service has no tile cache — every request is a live
render. We cache rendered PNGs locally; charts change on a weekly cycle, so
cached tiles get a generous TTL and are refreshed by re-fetch after expiry.

Revision ID: 0008
Revises: 0007
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE enc_tile_cache (
            z integer NOT NULL,
            x integer NOT NULL,
            y integer NOT NULL,
            png bytea NOT NULL,
            fetched_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (z, x, y)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS enc_tile_cache")
