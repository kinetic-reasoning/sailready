"""Charted depth lookup — the seed of the grounding check.

Depths are charted in METERS below MLLW. DRVAL1 is the conservative minimum
of a depth area; with overlapping cells the minimum across matches is used.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

M_TO_FT = 3.28084


async def charted_depth_at(db: AsyncSession, lat: float, lon: float) -> dict:
    params = {"lat": lat, "lon": lon}

    on_land = (
        await db.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM enc_land "
                "WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)))"
            ),
            params,
        )
    ).scalar()

    unsurveyed = (
        await db.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM enc_hazards WHERE category = 'UNSARE' "
                "AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)))"
            ),
            params,
        )
    ).scalar()

    depth_row = (
        await db.execute(
            text(
                "SELECT min(drval1_m) AS drval1, count(*) AS areas, "
                "bool_or(layer = 'DRGARE') AS in_dredged "
                "FROM enc_depth_areas "
                "WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"
            ),
            params,
        )
    ).one()

    soundings = (
        await db.execute(
            text(
                "SELECT depth_m, "
                "ST_Distance(geom::geography, "
                "  ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS dist_m "
                "FROM enc_soundings "
                "ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) "
                "LIMIT 5"
            ),
            params,
        )
    ).all()

    hazards = (
        await db.execute(
            text(
                "SELECT category, valsou_m, watlev, "
                "ST_Distance(geom::geography, "
                "  ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography) AS dist_m "
                "FROM enc_hazards "
                "WHERE ST_DWithin(geom::geography, "
                "  ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 200) "
                "ORDER BY dist_m LIMIT 10"
            ),
            params,
        )
    ).all()

    drval1 = float(depth_row.drval1) if depth_row.drval1 is not None else None
    return {
        "point": {"lat": lat, "lon": lon},
        "on_land": bool(on_land),
        "unsurveyed": bool(unsurveyed),
        "in_dredged_channel": bool(depth_row.in_dredged),
        "charted_min_depth_m": drval1,
        "charted_min_depth_ft": round(drval1 * M_TO_FT, 1) if drval1 is not None else None,
        "depth_areas_found": depth_row.areas,
        "nearby_soundings": [
            {
                "depth_m": float(s.depth_m),
                "depth_ft": round(float(s.depth_m) * M_TO_FT, 1),
                "distance_m": round(s.dist_m),
            }
            for s in soundings
        ],
        "hazards_within_200m": [
            {
                "category": h.category,
                # null sounding on a hazard = depth unknown = assume dangerous
                "depth_m": float(h.valsou_m) if h.valsou_m is not None else None,
                "depth_unknown": h.valsou_m is None,
                "water_level_code": h.watlev,
                "distance_m": round(h.dist_m),
            }
            for h in hazards
        ],
    }
