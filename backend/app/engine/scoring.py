"""The scoring engine — a pure function (SPEC §8).

score_trip() knows nothing about databases, HTTP, or users. It takes a boat
profile, ordered waypoints, the time window, and a conditions lookup, and
simulates the round trip hour by hour:

  - leg time is a feedback loop: foul current slows a leg -> you reach the
    next waypoint later -> conditions there have shifted (SPEC §3)
  - return legs are computed under conditions at return o'clock, not departure
  - score = worst constraint violation across all sampled points, never an
    average (SPEC §2)
  - turn-around deadline = latest depart-destination time that still gets you
    home inside the window, found by binary search over return simulations
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app.geo import haversine_nm

# Conservative defaults when the skipper hasn't set comfort limits
DEFAULT_MAX_WIND_KTS = 20.0
DEFAULT_MAX_WAVE_FT = 3.0
DEFAULT_MAX_ADVERSE_CURRENT_KTS = 1.5

MOTOR_WIND_THRESHOLD_KTS = 6.0  # below this, assume motoring
MIN_SOG_KTS = 0.3  # floor so simulation can't divide by ~zero


@dataclass
class BoatProfile:
    hull_speed_kts: float
    motor_speed_kts: float | None = None
    sail_speed_upwind_kts: float | None = None
    sail_speed_reach_kts: float | None = None
    sail_speed_downwind_kts: float | None = None
    max_wind_kts: float = DEFAULT_MAX_WIND_KTS
    max_wave_ft: float = DEFAULT_MAX_WAVE_FT
    max_adverse_current_kts: float = DEFAULT_MAX_ADVERSE_CURRENT_KTS


@dataclass
class Waypoint:
    lat: float
    lon: float
    name: str | None = None


# (waypoint_index, time) -> conditions record or None
ConditionsLookup = Callable[[int, datetime], Optional[dict]]


@dataclass
class Driver:
    constraint_type: str
    severity: str
    description: str
    leg: str | None = None
    waypoint_order: int | None = None
    actual_value: float | None = None
    threshold_value: float | None = None
    is_interpolated: bool = False


@dataclass
class LegResult:
    leg: str
    from_order: int
    to_order: int
    start: datetime
    end: datetime
    distance_nm: float
    sog_kts: float
    mode: str  # sail | motor


@dataclass
class ScoreResult:
    score: int
    feasible: bool
    drivers: list[Driver]
    legs: list[LegResult]
    outbound_arrival: datetime
    return_home: datetime
    turn_around_deadline: datetime | None
    max_reachable_distance_nm: float | None
    suggestions: list[dict] = field(default_factory=list)


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _wind_angle_off_bow(wind_from_deg: float, course_deg: float) -> float:
    """0 = wind on the nose, 180 = dead downwind."""
    return abs((wind_from_deg - course_deg + 180) % 360 - 180)


def _boat_speed(boat: BoatProfile, rec: dict, course: float) -> tuple[float, str]:
    motor = boat.motor_speed_kts or boat.hull_speed_kts * 0.7
    wind = rec.get("wind_speed_kts")
    wind_from = rec.get("wind_dir_deg")
    has_polars = any(
        s is not None
        for s in (
            boat.sail_speed_upwind_kts,
            boat.sail_speed_reach_kts,
            boat.sail_speed_downwind_kts,
        )
    )
    if wind is None or wind_from is None or wind < MOTOR_WIND_THRESHOLD_KTS or not has_polars:
        return min(motor, boat.hull_speed_kts), "motor"

    angle = _wind_angle_off_bow(wind_from, course)
    if angle < 50:
        speed = boat.sail_speed_upwind_kts
    elif angle <= 120:
        speed = boat.sail_speed_reach_kts
    else:
        speed = boat.sail_speed_downwind_kts
    if speed is None:
        return min(motor, boat.hull_speed_kts), "motor"
    return min(speed, boat.hull_speed_kts), "sail"


def _current_along_course(rec: dict, course: float) -> float:
    """Signed knots: positive = fair current pushing along the course."""
    speed = rec.get("current_speed_kts")
    direction = rec.get("current_dir_deg")  # direction current flows TOWARD
    if speed is None or direction is None:
        return 0.0
    return speed * math.cos(math.radians(direction - course))


def _severity(ratio: float) -> str:
    if ratio > 1.0:
        return "violation"
    if ratio >= 0.85:
        return "warning"
    return "ok"


def _constraint_score(ratio: float) -> int:
    """Map a constraint ratio (actual/threshold) to a 0-100 contribution."""
    if ratio > 1.0:
        return max(5, int(40 - (ratio - 1.0) * 150))
    if ratio >= 0.85:
        return int(89 - (ratio - 0.85) / 0.15 * 29)
    return 100


class _Simulation:
    def __init__(
        self,
        boat: BoatProfile,
        waypoints: list[Waypoint],
        lookup: ConditionsLookup,
    ):
        self.boat = boat
        self.wps = waypoints
        self.lookup = lookup
        self.drivers: list[Driver] = []
        self.legs: list[LegResult] = []
        self.constraint_scores: list[int] = [100]
        self._wave_gap_noted = False

    def _check(
        self,
        constraint: str,
        actual: float | None,
        threshold: float,
        leg: str,
        wp_order: int,
        when: datetime,
        what: str,
        interpolated: bool = False,
    ) -> None:
        if actual is None:
            return
        ratio = actual / threshold if threshold > 0 else 0.0
        sev = _severity(ratio)
        self.constraint_scores.append(_constraint_score(ratio))
        if sev != "ok":
            local = when.astimezone(when.tzinfo or timezone.utc)
            self.drivers.append(
                Driver(
                    constraint_type=constraint,
                    severity=sev,
                    leg=leg,
                    waypoint_order=wp_order,
                    actual_value=round(actual, 2),
                    threshold_value=threshold,
                    is_interpolated=interpolated,
                    description=(
                        f"{what} {actual:.1f} vs limit {threshold:.1f} "
                        f"({leg} leg, waypoint {wp_order}, {local:%a %H:%M %Z})"
                    ),
                )
            )

    def _check_waypoint(self, wp_order: int, rec: dict, leg: str, when: datetime) -> None:
        b = self.boat
        self._check("wind", rec.get("wind_speed_kts"), b.max_wind_kts, leg, wp_order, when, "wind kt")
        wave = rec.get("wave_height_ft")
        if wave is not None:
            self._check("wave", wave, b.max_wave_ft, leg, wp_order, when, "waves ft")
        elif not self._wave_gap_noted:
            self._wave_gap_noted = True
            self.drivers.append(
                Driver(
                    constraint_type="wave",
                    severity="ok",
                    leg=leg,
                    waypoint_order=wp_order,
                    description=(
                        "wave data unavailable at one or more waypoints "
                        "(global swell model gap inside the bay) — not scored"
                    ),
                )
            )

    def run_leg_sequence(
        self, order: list[int], start_time: datetime, leg: str, check: bool = True
    ) -> datetime:
        t = start_time
        for k in range(len(order) - 1):
            i, j = order[k], order[k + 1]
            a, b = self.wps[i], self.wps[j]
            course = bearing_deg(a.lat, a.lon, b.lat, b.lon)
            distance = haversine_nm(a.lat, a.lon, b.lat, b.lon)
            rec = self.lookup(i, t) or {}

            speed, mode = _boat_speed(self.boat, rec, course)
            along = _current_along_course(rec, course)
            sog = max(speed + along, MIN_SOG_KTS)

            if check:
                self._check_waypoint(i, rec, leg, t)
                adverse = max(0.0, -along)
                self._check(
                    "current",
                    adverse if adverse > 0 else None,
                    self.boat.max_adverse_current_kts,
                    leg,
                    i,
                    t,
                    "adverse current kt",
                    interpolated=bool(rec.get("current_is_interpolated")),
                )

            end = t + timedelta(hours=distance / sog)
            if check:
                self.legs.append(
                    LegResult(
                        leg=leg,
                        from_order=i,
                        to_order=j,
                        start=t,
                        end=end,
                        distance_nm=round(distance, 2),
                        sog_kts=round(sog, 2),
                        mode=mode,
                    )
                )
            t = end

        if check:
            rec = self.lookup(order[-1], t) or {}
            self._check_waypoint(order[-1], rec, leg, t)
        return t


def score_trip(
    boat: BoatProfile,
    waypoints: list[Waypoint],
    departure_time: datetime,
    return_by_time: datetime,
    time_at_destination_hrs: float,
    lookup: ConditionsLookup,
    _depth: int = 0,
) -> ScoreResult:
    sim = _Simulation(boat, waypoints, lookup)
    n = len(waypoints)
    out_order = list(range(n))
    ret_order = list(reversed(out_order))

    outbound_arrival = sim.run_leg_sequence(out_order, departure_time, "outbound")
    depart_destination = outbound_arrival + timedelta(hours=time_at_destination_hrs)
    return_home = sim.run_leg_sequence(ret_order, depart_destination, "return")

    # --- time budget: the core constraint -----------------------------------
    window_hrs = (return_by_time - departure_time).total_seconds() / 3600
    used_hrs = (return_home - departure_time).total_seconds() / 3600
    budget_ratio = used_hrs / window_hrs if window_hrs > 0 else 99.0
    sim.constraint_scores.append(_constraint_score(budget_ratio))
    budget_sev = _severity(budget_ratio)
    tz = return_by_time.tzinfo or timezone.utc
    if budget_sev != "ok":
        sim.drivers.append(
            Driver(
                constraint_type="time_budget",
                severity=budget_sev,
                leg="return",
                actual_value=round(used_hrs, 1),
                threshold_value=round(window_hrs, 1),
                description=(
                    f"round trip needs {used_hrs:.1f}h of your {window_hrs:.1f}h window — "
                    f"home {return_home.astimezone(tz):%a %H:%M} vs "
                    f"deadline {return_by_time.astimezone(tz):%a %H:%M}"
                ),
            )
        )

    # --- turn-around deadline (binary search over return simulations) --------
    def return_feasible(depart_dest: datetime) -> bool:
        probe = _Simulation(boat, waypoints, lookup)
        home = probe.run_leg_sequence(ret_order, depart_dest, "return", check=False)
        return home <= return_by_time

    turn_around: datetime | None = None
    if return_feasible(outbound_arrival):
        lo, hi = outbound_arrival, return_by_time
        for _ in range(12):
            mid = lo + (hi - lo) / 2
            if return_feasible(mid):
                lo = mid
            else:
                hi = mid
        turn_around = lo

    # --- dynamic max reachable distance --------------------------------------
    max_reach: float | None = None
    out_legs = [leg for leg in sim.legs if leg.leg == "outbound"]
    ret_legs = [leg for leg in sim.legs if leg.leg == "return"]
    out_hrs = sum((leg.end - leg.start).total_seconds() for leg in out_legs) / 3600
    ret_hrs = sum((leg.end - leg.start).total_seconds() for leg in ret_legs) / 3600
    if out_hrs > 0 and ret_hrs > 0:
        sog_out = sum(leg.distance_nm for leg in out_legs) / out_hrs
        sog_ret = sum(leg.distance_nm for leg in ret_legs) / ret_hrs
        avail = max(window_hrs - time_at_destination_hrs, 0)
        if sog_out + sog_ret > 0:
            max_reach = round(avail * sog_out * sog_ret / (sog_out + sog_ret), 1)

    score = min(sim.constraint_scores)
    feasible = all(d.severity != "violation" for d in sim.drivers)

    # --- suggestions (skipped in recursive probes) ----------------------------
    suggestions: list[dict] = []
    if _depth == 0:
        if budget_ratio > 1.0 and time_at_destination_hrs > 0:
            overrun = used_hrs - window_hrs
            if overrun < time_at_destination_hrs:
                suggestions.append(
                    {
                        "type": "shorten_stay",
                        "description": (
                            f"Shorten time at destination by {overrun:.1f}h "
                            f"to fit the window"
                        ),
                    }
                )
        if score < 75:
            for hours_earlier in (1, 2):
                probe = score_trip(
                    boat,
                    waypoints,
                    departure_time - timedelta(hours=hours_earlier),
                    return_by_time,
                    time_at_destination_hrs,
                    lookup,
                    _depth=1,
                )
                if probe.score >= score + 10:
                    adjusted = departure_time - timedelta(hours=hours_earlier)
                    suggestions.append(
                        {
                            "type": "leave_earlier",
                            "description": (
                                f"Leaving {hours_earlier}h earlier improves the "
                                f"score to {probe.score}%"
                            ),
                            "adjusted_departure": adjusted.isoformat(),
                        }
                    )
                    break

    return ScoreResult(
        score=score,
        feasible=feasible,
        drivers=sim.drivers,
        legs=sim.legs,
        outbound_arrival=outbound_arrival,
        return_home=return_home,
        turn_around_deadline=turn_around,
        max_reachable_distance_nm=max_reach,
        suggestions=suggestions,
    )
