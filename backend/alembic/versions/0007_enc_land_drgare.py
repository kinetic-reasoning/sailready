"""ENC completeness: dredged areas, land areas, source layer tag.

DEPARE alone does not tile the water: dredged channels are DRGARE (with their
own depth values), land is LNDARE, unsurveyed water is UNSARE. The grounding
check needs all of them.

Revision ID: 0007
Revises: 0006
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE enc_depth_areas ADD COLUMN layer text NOT NULL DEFAULT 'DEPARE'",
    """
    CREATE TABLE enc_land (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        cell text NOT NULL,
        geom geometry(Geometry, 4326) NOT NULL
    )
    """,
    "CREATE INDEX enc_land_geom_idx ON enc_land USING GIST (geom)",
    "CREATE INDEX enc_land_cell_idx ON enc_land (cell)",
]


def upgrade() -> None:
    for s in STATEMENTS:
        op.execute(s)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS enc_land")
    op.execute("ALTER TABLE enc_depth_areas DROP COLUMN IF EXISTS layer")
