"""ENC vector chart tables: depth areas, soundings, hazards.

Shared reference data (no RLS) parsed from NOAA S-57 cells. Depths in METERS
below MLLW, as charted. DRVAL1 = conservative minimum depth of an area.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE enc_depth_areas (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        cell text NOT NULL,
        drval1_m numeric(7, 2),
        drval2_m numeric(7, 2),
        geom geometry(Geometry, 4326) NOT NULL
    )
    """,
    "CREATE INDEX enc_depth_areas_geom_idx ON enc_depth_areas USING GIST (geom)",
    "CREATE INDEX enc_depth_areas_cell_idx ON enc_depth_areas (cell)",
    """
    CREATE TABLE enc_soundings (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        cell text NOT NULL,
        depth_m numeric(7, 2) NOT NULL,
        geom geometry(Point, 4326) NOT NULL
    )
    """,
    "CREATE INDEX enc_soundings_geom_idx ON enc_soundings USING GIST (geom)",
    "CREATE INDEX enc_soundings_cell_idx ON enc_soundings (cell)",
    """
    CREATE TABLE enc_hazards (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        cell text NOT NULL,
        category text NOT NULL,
        valsou_m numeric(7, 2),
        watlev text,
        geom geometry(Geometry, 4326) NOT NULL
    )
    """,
    "CREATE INDEX enc_hazards_geom_idx ON enc_hazards USING GIST (geom)",
    "CREATE INDEX enc_hazards_cell_idx ON enc_hazards (cell)",
]


def upgrade() -> None:
    for s in STATEMENTS:
        op.execute(s)


def downgrade() -> None:
    for t in ["enc_hazards", "enc_soundings", "enc_depth_areas"]:
        op.execute(f"DROP TABLE IF EXISTS {t}")
