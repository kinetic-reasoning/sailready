"""Unit tests for the pure scoring engine — synthetic conditions, known outcomes."""
from datetime import datetime, timedelta, timezone

from app.engine.scoring import BoatProfile, Waypoint, score_trip

BOAT = BoatProfile(
    hull_speed_kts=6.4,
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
    """10h window for the same trip: engine flags the squeeze and suggests
    leaving earlier — the core product behavior."""
    result = score_trip(BOAT, WPS, DEP, DEP + timedelta(hours=10), 1.0, benign)
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
