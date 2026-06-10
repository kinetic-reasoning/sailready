"""Ingest NOAA ENC S-57 vector cells into PostGIS.

Parses depth areas (DEPARE), soundings (SOUNDG), and hazards
(OBSTRN/WRECKS/UWTROC) from downloaded ENC zips into the enc_* tables —
the data foundation for the grounding check and the Phase 2 channel-graph
router.

Usage (one-shot, admin role):
    docker compose run --rm api python -m app.charts.ingest_enc [data/enc]

S-57 gotchas handled per SPEC §6a:
  - SPLIT_MULTIPOINT/ADD_SOUNDG_DEPTH so soundings arrive as points with depth
  - DRVAL1 = conservative minimum depth of an area (meters below MLLW)
  - null VALSOU on a hazard means depth unknown -> treat as dangerous
  - cell directories kept intact so update files (.001...) auto-apply
"""
import asyncio
import os
import sys
import tempfile
import zipfile
from pathlib import Path

# Must be set before GDAL opens anything
os.environ.setdefault(
    "OGR_S57_OPTIONS",
    "SPLIT_MULTIPOINT=ON,ADD_SOUNDG_DEPTH=ON,UPDATES=APPLY,RETURN_PRIMITIVES=OFF",
)

from pyogrio import list_layers  # noqa: E402
from pyogrio.raw import read as ogr_read  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

HAZARD_LAYERS = ("OBSTRN", "WRECKS", "UWTROC", "UNSARE")
# DEPARE alone does not tile the water — dredged channels are DRGARE with
# their own DRVAL1/DRVAL2 (and they're exactly where boats go)
DEPTH_AREA_LAYERS = ("DEPARE", "DRGARE")


def _read_layer(path: str, layer: str):
    """Returns (field_names, geometry_wkb_list, field_columns) or None."""
    available = {name for name, _ in list_layers(path)}
    if layer not in available:
        return None
    meta, _index, geometry, field_data = ogr_read(path, layer=layer)
    return list(meta["fields"]), geometry, field_data


def _field(names: list[str], field_data, name: str, i: int):
    try:
        idx = names.index(name)
    except ValueError:
        return None
    value = field_data[idx][i]
    if value is None:
        return None
    try:
        import math

        if isinstance(value, float) and math.isnan(value):
            return None
    except TypeError:
        pass
    return value


async def ingest_cell(conn, zip_path: Path) -> dict:
    cell = zip_path.stem
    counts = {"depth_areas": 0, "soundings": 0, "hazards": 0, "land": 0}

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        base_files = list(Path(tmp).rglob("*.000"))
        if not base_files:
            print(f"  {cell}: no .000 base file found, skipping")
            return counts
        s57_path = str(base_files[0])

        # idempotent re-ingest
        for table in ("enc_depth_areas", "enc_soundings", "enc_hazards", "enc_land"):
            await conn.execute(text(f"DELETE FROM {table} WHERE cell = :c"), {"c": cell})

        # --- depth areas: DEPARE + DRGARE (dredged channels) -------------------
        for layer in DEPTH_AREA_LAYERS:
            result = _read_layer(s57_path, layer)
            if not result:
                continue
            names, geoms, fields = result
            rows = [
                {
                    "cell": cell,
                    "layer": layer,
                    "d1": _field(names, fields, "DRVAL1", i),
                    "d2": _field(names, fields, "DRVAL2", i),
                    "wkb": bytes(geoms[i]),
                }
                for i in range(len(geoms))
                if geoms[i] is not None
            ]
            if rows:
                await conn.execute(
                    text(
                        "INSERT INTO enc_depth_areas (cell, layer, drval1_m, drval2_m, geom) "
                        "VALUES (:cell, :layer, :d1, :d2, "
                        "ST_Force2D(ST_SetSRID(ST_GeomFromWKB(:wkb), 4326)))"
                    ),
                    rows,
                )
            counts["depth_areas"] += len(rows)

        # --- land areas (LNDARE) — "you're aground" + future routing mask ------
        result = _read_layer(s57_path, "LNDARE")
        if result:
            names, geoms, fields = result
            rows = [
                {"cell": cell, "wkb": bytes(geoms[i])}
                for i in range(len(geoms))
                if geoms[i] is not None
            ]
            if rows:
                await conn.execute(
                    text(
                        "INSERT INTO enc_land (cell, geom) VALUES (:cell, "
                        "ST_Force2D(ST_SetSRID(ST_GeomFromWKB(:wkb), 4326)))"
                    ),
                    rows,
                )
            counts["land"] = len(rows)

        # --- SOUNDG ----------------------------------------------------------
        result = _read_layer(s57_path, "SOUNDG")
        if result:
            names, geoms, fields = result
            rows = []
            for i in range(len(geoms)):
                depth = _field(names, fields, "DEPTH", i)
                if depth is None or geoms[i] is None:
                    continue
                rows.append({"cell": cell, "d": float(depth), "wkb": bytes(geoms[i])})
            if rows:
                await conn.execute(
                    text(
                        "INSERT INTO enc_soundings (cell, depth_m, geom) "
                        "VALUES (:cell, :d, "
                        "ST_Force2D(ST_SetSRID(ST_GeomFromWKB(:wkb), 4326)))"
                    ),
                    rows,
                )
            counts["soundings"] = len(rows)

        # --- hazards -----------------------------------------------------------
        hazard_rows = []
        for layer in HAZARD_LAYERS:
            result = _read_layer(s57_path, layer)
            if not result:
                continue
            names, geoms, fields = result
            for i in range(len(geoms)):
                if geoms[i] is None:
                    continue
                valsou = _field(names, fields, "VALSOU", i)
                watlev = _field(names, fields, "WATLEV", i)
                hazard_rows.append(
                    {
                        "cell": cell,
                        "cat": layer,
                        "v": float(valsou) if valsou is not None else None,
                        "w": str(watlev) if watlev is not None else None,
                        "wkb": bytes(geoms[i]),
                    }
                )
        if hazard_rows:
            await conn.execute(
                text(
                    "INSERT INTO enc_hazards (cell, category, valsou_m, watlev, geom) "
                    "VALUES (:cell, :cat, :v, :w, "
                    "ST_Force2D(ST_SetSRID(ST_GeomFromWKB(:wkb), 4326)))"
                ),
                hazard_rows,
            )
        counts["hazards"] = len(hazard_rows)

    return counts


async def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/enc")
    zips = sorted(src.glob("*.zip"))
    if not zips:
        print(f"no ENC zips found in {src}")
        sys.exit(1)

    engine = create_async_engine(os.environ["DATABASE_URL_ADMIN"])
    totals = {"depth_areas": 0, "soundings": 0, "hazards": 0, "land": 0}
    async with engine.begin() as conn:
        for zp in zips:
            counts = await ingest_cell(conn, zp)
            print(
                f"  {zp.stem}: {counts['depth_areas']} depth areas, "
                f"{counts['soundings']} soundings, {counts['hazards']} hazards, "
                f"{counts['land']} land"
            )
            for k in totals:
                totals[k] += counts[k]
    await engine.dispose()
    print(
        f"TOTAL: {totals['depth_areas']} depth areas, "
        f"{totals['soundings']} soundings, {totals['hazards']} hazards, "
        f"{totals['land']} land areas"
    )


if __name__ == "__main__":
    asyncio.run(main())
