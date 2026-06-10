"""Unit tests for the pure scoring engine — synthetic conditions, known outcomes."""
from datetime import datetime, timedelta, timezone

from app.engine.scoring import BoatProfile, Waypoint, score_trip

BOAT = BoatProfile(
    hull_speed_kts=6.4,
    draft_ft=3.5,
    motor_speed_kts=4.5,
    sail_speed_upwind_kts=3.5,
    sail_speed_reach_kts=5.5,
    sail_speed_downwind_kts=5.0,
    max_wind_kts=20.0,
    max_wave_ft=3.0,
    max_adverse_current_kts=1.5,
)

# ~10nm roughly east-west: Shell Point-ish to mid-bay-ish
WPS = [
    Waypoint(27.72, -82.40, "start"),
    Waypoint(27.66, -82.55, "mid"),
    Waypoint(27.60, -82.70, "destination"),
]

DEP = datetime(2026, 6, 13, 13, 0, tzinfo=timezone.utc)  # 9am EDT


def benign(i, t):
    return {
        "wind_speed_kts": 10.0,
        "wind_dir_deg": 90.0,  # easterly: downwind out, upwind back
        "wave_height_ft": 1.0,
        "current_speed_kts": 0.3,
        "current_dir_deg": 270.0,
        "tide_height_ft": 2.0,
    }


def test_benign_conditions_high_score():
    # 12h window: comfortable for ~17.5nm each way at these speeds
    result = score_trip(BOAT, WPS, DEP, DEP + timedelta(hours=12), 1.0, benign)
    assert result.feasible
    assert result.score >= 85
    assert result.turn_around_deadline is not None
    assert result.turn_around_deadline > result.outbound_arrival
    assert result.return_home <= DEP + timedelta(hours=12)
    # 4 legs: 2 out + 2 back
    assert len(result.legs) == 4


def test_tight_window_warns_and_suggests():
    """11h window vs ~10.2h needed (return is a beat — 25° off the wind is in
    the no-go zone, so the engine uses tacking VMG): warning + suggestion."""
    result = score_trip(BOAT, WPS, DEP, DEP + timedelta(hours=11), 1.0, benign)
    assert result.feasible  # warning, not violation
    assert 40 <= result.score < 85
    assert any(
        d.constraint_type == "time_budget" and d.severity == "warning"
        for d in result.drivers
    )
    assert any(s["type"] == "leave_earlier" for s in result.suggestions)


def test_return_gale_is_nogo():
    """Perfect morning, 28kt on the nose for the ride home -> violation, low score."""

    def building_wind(i, t):
        rec = dict(benign(i, t))
        if t > DEP + timedelta(hours=3):
            rec["wind_speed_kts"] = 28.0
            rec["wind_dir_deg"] = 90.0
            rec["wave_height_ft"] = 4.5
        return rec

    result = score_trip(BOAT, WPS, DEP, DEP + timedelta(hours=10), 1.0, building_wind)
    assert not result.feasible
    assert result.score < 40
    violations = [d for d in result.drivers if d.severity == "violation"]
    assert any(d.constraint_type == "wind" for d in violations)
    assert any(d.leg == "return" for d in violations)


def test_impossible_window_violates_time_budget():
    result = score_trip(BOAT, WPS, DEP, DEP + timedelta(hours=4), 2.0, benign)
    assert not result.feasible
    assert any(
        d.constraint_type == "time_budget" and d.severity == "violation"
        for d in result.drivers
    )
    # suggestion engine should notice the stay can't be shortened enough OR suggest it
    # (depends on magnitude) — at minimum the score must be punished
    assert result.score < 40


def test_foul_current_slows_return():
    """Same wind both ways, but strong foul current on the return drops SOG."""

    def foul_return_current(i, t):
        rec = dict(benign(i, t))
        if t > DEP + timedelta(hours=3):
            rec["current_speed_kts"] = 1.8
            rec["current_dir_deg"] = 270.0  # flowing west; return course is east
            rec["current_is_interpolated"] = True
        return rec

    result = score_trip(BOAT, WPS, DEP, DEP + timedelta(hours=12), 1.0, foul_return_current)
    out_legs = [leg for leg in result.legs if leg.leg == "outbound"]
    ret_legs = [leg for leg in result.legs if leg.leg == "return"]
    avg_out = sum(l.sog_kts for l in out_legs) / len(out_legs)
    avg_ret = sum(l.sog_kts for l in ret_legs) / len(ret_legs)
    assert avg_ret < avg_out  # the core insight: return is slower
    current_drivers = [d for d in result.drivers if d.constraint_type == "current"]
    assert any(d.severity == "violation" for d in current_drivers)
    assert any(d.is_interpolated for d in current_drivers)


def test_afternoon_thunderstorm_is_nogo():
    """Classic Florida: clear morning, thunderstorm cell on the return."""

    def afternoon_storms(i, t):
        rec = dict(benign(i, t))
        if t > DEP + timedelta(hours=4):
            rec["weather_code"] = 95
            rec["rain_prob_pct"] = 85.0
        return rec

    result = score_trip(BOAT, WPS, DEP, DEP + timedelta(hours=12), 1.0, afternoon_storms)
    assert not result.feasible
    assert result.score <= 15
    storm = [d for d in result.drivers if d.constraint_type == "weather"]
    assert any(d.severity == "violation" for d in storm)
    assert all(d.leg == "return" for d in storm)  # morning was clean


def test_rain_warns_but_can_still_go():
    def rainy(i, t):
        rec = dict(benign(i, t))
        rec["rain_prob_pct"] = 75.0
        rec["weather_code"] = 61  # plain rain, no thunder
        return rec

    result = score_trip(BOAT, WPS, DEP, DEP + timedelta(hours=12), 1.0, rainy)
    assert result.feasible  # wet, not dangerous
    assert 55 <= result.score < 85
    assert any(
        d.constraint_type == "weather" and d.severity == "warning" for d in result.drivers
    )


EW_WPS = [Waypoint(27.60, -82.70, "west"), Waypoint(27.60, -82.50, "east")]  # due E-W


def east_wind(i, t):
    return {"wind_speed_kts": 12.0, "wind_dir_deg": 90.0, "wave_height_ft": 1.0}


def test_beating_dead_upwind_uses_vmg():
    """Outbound course 090 with wind FROM 090 = no-go zone -> tack at VMG."""
    result = score_trip(BOAT, EW_WPS, DEP, DEP + timedelta(hours=14), 0.5, east_wind)
    outbound = [l for l in result.legs if l.leg == "outbound"][0]
    assert outbound.mode == "sail-tack"
    assert outbound.tack_headings is not None
    # VMG = 3.5 * cos(45°) ≈ 2.47 — beating is slow, that's the point
    assert abs(outbound.boat_speed_kts - 3.5 * 0.7071) < 0.05
    # return is dead downwind -> plain sail at downwind speed
    ret = [l for l in result.legs if l.leg == "return"][0]
    assert ret.mode == "sail"
    assert ret.boat_speed_kts == BOAT.sail_speed_downwind_kts


def test_fastest_preference_motors_when_beating_is_slower():
    from dataclasses import replace

    fastest = replace(BOAT, sailing_preference="fastest")
    result = score_trip(fastest, EW_WPS, DEP, DEP + timedelta(hours=14), 0.5, east_wind)
    outbound = [l for l in result.legs if l.leg == "outbound"][0]
    # motor 4.5 beats VMG 2.47 -> motors upwind
    assert outbound.mode == "motor"
    assert outbound.boat_speed_kts == 4.5
    # downwind sail (5.0) beats motor (4.5) -> sails home
    ret = [l for l in result.legs if l.leg == "return"][0]
    assert ret.mode == "sail"


def test_forced_motor_leg_overrides_good_sailing_wind():
    """Marina channel: leg 0-1 forced motor even with a perfect beam reach.
    The constraint is on the segment, so it applies on the return too."""
    wps = [
        Waypoint(27.60, -82.70, "marina", leg_mode="motor"),
        Waypoint(27.60, -82.60, "channel end"),
        Waypoint(27.60, -82.50, "destination"),
    ]

    def beam_reach(i, t):
        return {"wind_speed_kts": 12.0, "wind_dir_deg": 0.0}  # northerly, course east

    result = score_trip(BOAT, wps, DEP, DEP + timedelta(hours=14), 0.5, beam_reach)
    seg01 = [l for l in result.legs if {l.from_order, l.to_order} == {0, 1}]
    seg12 = [l for l in result.legs if {l.from_order, l.to_order} == {1, 2}]
    assert all(l.mode == "motor" and l.leg_mode == "motor" for l in seg01)  # both directions
    assert all(l.mode == "sail" for l in seg12)  # open water sails the reach


def test_crab_corrected_course_to_steer():
    def cross_current(i, t):
        # course 090, current flowing due south (180) at 1kt = pushing to starboard
        return {
            "wind_speed_kts": 12.0, "wind_dir_deg": 180.0,  # beam reach
            "current_speed_kts": 1.0, "current_dir_deg": 180.0,
        }

    result = score_trip(BOAT, EW_WPS, DEP, DEP + timedelta(hours=14), 0.5, cross_current)
    outbound = [l for l in result.legs if l.leg == "outbound"][0]
    assert outbound.mode == "sail"
    # crab into the current: CTS should be NORTH of the 090 course
    assert outbound.cts_deg is not None
    assert 75 <= outbound.cts_deg < 90


def test_gusts_scored_with_tolerance():
    """Sustained 15kt is fine for a 20kt limit, but 30kt gusts blow through
    the 24kt gust tolerance (20 * 1.2) -> violation."""

    def gusty(i, t):
        rec = dict(benign(i, t))
        rec["wind_speed_kts"] = 15.0
        rec["wind_gust_kts"] = 30.0
        return rec

    result = score_trip(BOAT, WPS, DEP, DEP + timedelta(hours=12), 1.0, gusty)
    assert not result.feasible
    gust_drivers = [d for d in result.drivers if "gusts" in d.description]
    assert any(d.severity == "violation" for d in gust_drivers)
    assert result.conditions_summary["max_gust_kts"]["value"] == 30.0
    assert result.conditions_summary["max_gust_kts"]["limit"] == 24.0


def test_moderate_gusts_within_tolerance_ok():
    def breezy(i, t):
        rec = dict(benign(i, t))
        rec["wind_speed_kts"] = 14.0
        rec["wind_gust_kts"] = 19.0  # under 24kt tolerance and under 0.85 warning band
        return rec

    result = score_trip(BOAT, WPS, DEP, DEP + timedelta(hours=12), 1.0, breezy)
    assert not any("gusts" in d.description for d in result.drivers)


# --- grounding checks ----------------------------------------------------------


def test_waypoint_on_charted_land_is_violation():
    wps = [
        Waypoint(27.72, -82.40, "marina"),
        Waypoint(27.66, -82.55, "oops", on_land=True),
        Waypoint(27.60, -82.70, "destination"),
    ]
    result = score_trip(BOAT, wps, DEP, DEP + timedelta(hours=12), 1.0, benign)
    assert not result.feasible
    assert result.score <= 15
    land = [d for d in result.drivers if "charted LAND" in d.description]
    assert len(land) == 1  # deduped across outbound + return visits
    assert land[0].constraint_type == "depth"


def test_grounding_depends_on_tide_at_arrival_time():
    """Thin water passable at high tide, grounding at low — the time-shifted
    core insight applied to depth: outbound clears, return doesn't."""
    wps = [
        Waypoint(27.72, -82.40, "start", charted_min_depth_m=3.0),
        Waypoint(27.66, -82.55, "thin spot", charted_min_depth_m=1.2),  # 3.9ft charted
        Waypoint(27.60, -82.70, "destination", charted_min_depth_m=3.0),
    ]

    def falling_tide(i, t):
        rec = dict(benign(i, t))
        # high tide early (outbound), dead low for the return
        rec["tide_height_ft"] = 2.0 if t < DEP + timedelta(hours=3) else 0.0
        return rec

    result = score_trip(BOAT, wps, DEP, DEP + timedelta(hours=12), 1.0, falling_tide)
    # need 4.5ft; outbound has 3.9+2.0=5.9 (ok), return has 3.9+0.0=3.9 (violation)
    depth = [d for d in result.drivers if d.constraint_type == "depth"]
    assert all(d.leg == "return" for d in depth)
    assert any(d.severity == "violation" for d in depth)
    assert not result.feasible
    assert result.conditions_summary["depth_need_vs_have_ft"]["value"] == 4.5
    assert result.conditions_summary["depth_need_vs_have_ft"]["limit"] == 3.9


def test_unsurveyed_water_warns_not_blocks():
    wps = [
        Waypoint(27.72, -82.40, "start", charted_min_depth_m=3.0),
        Waypoint(27.66, -82.55, "gray area", unsurveyed=True, charted_min_depth_m=3.0),
        Waypoint(27.60, -82.70, "destination", charted_min_depth_m=3.0),
    ]
    result = score_trip(BOAT, wps, DEP, DEP + timedelta(hours=12), 1.0, benign)
    assert result.feasible  # warning, not violation
    assert any(
        d.constraint_type == "depth" and "unsurveyed" in d.description for d in result.drivers
    )


def test_acknowledged_depth_downgrades_violation_to_warning():
    wps = [
        Waypoint(27.72, -82.40, "start", charted_min_depth_m=3.0),
        Waypoint(27.66, -82.55, "home creek", charted_min_depth_m=0.9, depth_acknowledged=True),
        Waypoint(27.60, -82.70, "destination", charted_min_depth_m=3.0),
    ]

    def low_tide(i, t):
        rec = dict(benign(i, t))
        rec["tide_height_ft"] = 0.3  # 0.9m charted + 0.3 tide = 3.25ft < 4.5 needed
        return rec

    result = score_trip(BOAT, wps, DEP, DEP + timedelta(hours=12), 1.0, low_tide)
    depth = [d for d in result.drivers if d.constraint_type == "depth"]
    assert depth and all(d.severity == "warning" for d in depth)
    assert all("acknowledged" in d.description for d in depth)
    assert result.feasible  # downgraded — no violations remain
    # acknowledged = informed, not penalized: the score is untouched by depth
    baseline = score_trip(
        BOAT,
        [
            Waypoint(27.72, -82.40, "start", charted_min_depth_m=3.0),
            Waypoint(27.66, -82.55, "deep here", charted_min_depth_m=3.0),
            Waypoint(27.60, -82.70, "destination", charted_min_depth_m=3.0),
        ],
        DEP, DEP + timedelta(hours=12), 1.0, low_tide,
    )
    assert result.score == baseline.score
    # and the summary's worst-depth row ignores acknowledged waypoints
    assert result.conditions_summary["depth_need_vs_have_ft"]["limit"] > 4.5


def test_land_cannot_be_acknowledged():
    wps = [
        Waypoint(27.72, -82.40, "start", charted_min_depth_m=3.0),
        Waypoint(27.66, -82.55, "nope", on_land=True, depth_acknowledged=True),
        Waypoint(27.60, -82.70, "destination", charted_min_depth_m=3.0),
    ]
    result = score_trip(BOAT, wps, DEP, DEP + timedelta(hours=12), 1.0, benign)
    assert not result.feasible  # land is land
    assert any(
        d.constraint_type == "depth" and d.severity == "violation" for d in result.drivers
    )


def test_zero_margin_clears_what_default_margin_flags():
    """Charted 1.2m (3.9ft) at 0.0 tide: draft 3.5 clears with 0 margin
    (datum-correct — charted depth IS the water at MLLW), flags with 1ft."""
    from dataclasses import replace

    wps = [
        Waypoint(27.72, -82.40, "start", charted_min_depth_m=3.0),
        Waypoint(27.66, -82.55, "thin", charted_min_depth_m=1.2),
        Waypoint(27.60, -82.70, "destination", charted_min_depth_m=3.0),
    ]

    def dead_low(i, t):
        rec = dict(benign(i, t))
        rec["tide_height_ft"] = 0.0
        return rec

    flagged = score_trip(BOAT, wps, DEP, DEP + timedelta(hours=12), 1.0, dead_low)
    assert any(
        d.constraint_type == "depth" and d.severity == "violation" for d in flagged.drivers
    )

    confident = replace(BOAT, grounding_margin_ft=0.0)
    cleared = score_trip(confident, wps, DEP, DEP + timedelta(hours=12), 1.0, dead_low)
    # need 3.5, have 3.9 -> ratio 0.90: a warning band note, but no violation
    assert not any(
        d.constraint_type == "depth" and d.severity == "violation" for d in cleared.drivers
    )
    assert cleared.feasible


def test_no_draft_skips_grounding():
    from dataclasses import replace

    no_draft = replace(BOAT, draft_ft=None)
    wps = [Waypoint(27.72, -82.40, on_land=True), Waypoint(27.60, -82.70)]
    result = score_trip(no_draft, wps, DEP, DEP + timedelta(hours=12), 1.0, benign)
    assert not any(d.constraint_type == "depth" for d in result.drivers)


def test_missing_wave_data_noted_not_scored():
    def no_waves(i, t):
        rec = dict(benign(i, t))
        rec["wave_height_ft"] = None
        return rec

    result = score_trip(BOAT, WPS, DEP, DEP + timedelta(hours=12), 1.0, no_waves)
    gap_notes = [
        d for d in result.drivers if d.constraint_type == "wave" and d.severity == "ok"
    ]
    assert len(gap_notes) == 1  # noted exactly once
    assert result.score >= 85  # absence of data doesn't tank the score
