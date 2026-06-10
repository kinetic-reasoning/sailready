"""Glue between the pure scoring engine and the world: fetches conditions,
runs score_trip(), persists results, and fires notifications. Called
identically by the API endpoint and the daily rescore job (SPEC §8)."""
import asyncio
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from geoalchemy2.shape import to_shape
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.charts.depth import charted_depth_at
from app.conditions.service import get_hourly_conditions
from app.config import settings
from app.engine.scoring import BoatProfile, ScoreResult, Waypoint, score_trip
from app.models import Boat, Notification, ScoreDriver, Trip, TripScore, User

CONDITIONS_PAD_BEFORE = timedelta(hours=3)  # room for leave-earlier probes
CONDITIONS_PAD_AFTER = timedelta(hours=8)  # room for deadline search overruns


def _f(value) -> float | None:
    return float(value) if value is not None else None


def boat_profile(boat: Boat) -> BoatProfile:
    profile = BoatProfile(hull_speed_kts=float(boat.hull_speed_kts))
    profile.draft_ft = _f(boat.draft_ft)
    profile.motor_speed_kts = _f(boat.motor_speed_kts)
    profile.sail_speed_upwind_kts = _f(boat.sail_speed_upwind_kts)
    profile.sail_speed_reach_kts = _f(boat.sail_speed_reach_kts)
    profile.sail_speed_downwind_kts = _f(boat.sail_speed_downwind_kts)
    if boat.max_wind_kts is not None:
        profile.max_wind_kts = float(boat.max_wind_kts)
    if boat.max_wave_ft is not None:
        profile.max_wave_ft = float(boat.max_wave_ft)
    if boat.max_adverse_current_kts is not None:
        profile.max_adverse_current_kts = float(boat.max_adverse_current_kts)
    profile.sailing_preference = boat.sailing_preference
    profile.min_upwind_angle_deg = float(boat.min_upwind_angle_deg)
    return profile


def build_lookup(per_waypoint: dict[int, dict[datetime, dict]]):
    """Nearest-hour conditions lookup with a ±3h tolerance."""

    def lookup(index: int, t: datetime) -> dict | None:
        hours = per_waypoint.get(index)
        if not hours:
            return None
        base = t.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        for dh in (0, 1, -1, 2, -2, 3, -3):
            rec = hours.get(base + timedelta(hours=dh))
            if rec is not None:
                return rec
        return None

    return lookup


async def rescore_trip(db: AsyncSession, trip: Trip) -> ScoreResult:
    """Fetch conditions for every waypoint, run the engine, persist, notify."""
    boat = (await db.execute(select(Boat).where(Boat.id == trip.boat_id))).scalar_one()
    if not trip.waypoints:
        raise ValueError("trip has no route waypoints yet")

    waypoints = []
    for wp in trip.waypoints:
        pt = to_shape(wp.location)
        # static chart facts per waypoint — the engine combines charted depth
        # with tide at the simulated arrival time
        chart = await charted_depth_at(db, pt.y, pt.x)
        waypoints.append(
            Waypoint(
                lat=pt.y,
                lon=pt.x,
                name=wp.name,
                leg_mode=wp.leg_mode,
                depth_acknowledged=wp.depth_acknowledged,
                charted_min_depth_m=chart["charted_min_depth_m"],
                on_land=chart["on_land"],
                unsurveyed=chart["unsurveyed"],
                hazard_unknown_depth_nearby=any(
                    h["depth_unknown"] for h in chart["hazards_within_200m"]
                ),
            )
        )

    t_from = trip.departure_time - CONDITIONS_PAD_BEFORE
    t_to = trip.return_by_time + CONDITIONS_PAD_AFTER

    per_waypoint: dict[int, dict[datetime, dict]] = {}
    alerts: list[dict] = []
    for i, wpt in enumerate(waypoints):
        is_destination = i == len(waypoints) - 1
        data = await get_hourly_conditions(
            db, wpt.lat, wpt.lon, t_from, t_to, include_alerts=is_destination
        )
        per_waypoint[i] = {
            datetime.fromisoformat(rec["valid_time"]): rec for rec in data["hours"]
        }
        if is_destination:
            alerts = data["alerts"]

    result = score_trip(
        boat_profile(boat),
        waypoints,
        trip.departure_time,
        trip.return_by_time,
        float(trip.time_at_destination_hrs),
        build_lookup(per_waypoint),
    )

    # Marine warnings gate the score regardless of the numbers
    for alert in alerts:
        severe = alert.get("severity") in ("Severe", "Extreme")
        from app.engine.scoring import Driver  # local import to keep engine pure

        result.drivers.insert(
            0,
            Driver(
                constraint_type="wind",
                severity="violation" if severe else "warning",
                description=f"NWS: {alert.get('headline') or alert.get('event')}",
            ),
        )
        result.score = min(result.score, 20 if severe else 55)
        if severe:
            result.feasible = False

    previous_score = trip.current_score
    await _persist(db, trip, result)
    await _maybe_notify(db, trip, previous_score, result)
    return result


async def _persist(db: AsyncSession, trip: Trip, result: ScoreResult) -> None:
    forecast_date = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)

    await db.execute(
        update(TripScore)
        .where(TripScore.trip_id == trip.id, TripScore.forecast_date != forecast_date)
        .values(is_current=False)
    )
    row = (
        await db.execute(
            select(TripScore).where(
                TripScore.trip_id == trip.id, TripScore.forecast_date == forecast_date
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = TripScore(trip_id=trip.id, forecast_date=forecast_date)
        db.add(row)
    else:
        # Idempotent daily rescore: re-running a day overwrites it (SPEC §8)
        await db.execute(delete(ScoreDriver).where(ScoreDriver.trip_score_id == row.id))

    row.score = result.score
    row.is_current = True
    row.feasible = result.feasible
    row.scored_at = now
    row.turn_around_deadline = result.turn_around_deadline
    row.max_reachable_distance_nm = result.max_reachable_distance_nm
    row.suggestions = result.suggestions
    row.conditions_summary = result.conditions_summary
    row.outbound_arrival = result.outbound_arrival
    row.return_home = result.return_home
    row.legs = [
        {
            **{k: v for k, v in vars(leg).items() if not isinstance(v, datetime)},
            "start": leg.start.isoformat(),
            "end": leg.end.isoformat(),
        }
        for leg in result.legs
    ]
    await db.flush()

    for d in result.drivers:
        db.add(
            ScoreDriver(
                trip_score_id=row.id,
                constraint_type=d.constraint_type,
                waypoint_order=d.waypoint_order,
                leg=d.leg,
                severity=d.severity,
                actual_value=d.actual_value,
                threshold_value=d.threshold_value,
                is_interpolated=d.is_interpolated,
                description=d.description,
            )
        )

    trip.current_score = result.score
    trip.current_score_updated_at = now
    await db.flush()


def _send_email_sync(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = "alerts@sailready.local"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.send_message(msg)


async def _maybe_notify(
    db: AsyncSession, trip: Trip, previous_score: int | None, result: ScoreResult
) -> None:
    if previous_score is None:
        return  # first ever score — nothing to compare against
    user = (await db.execute(select(User).where(User.id == trip.user_id))).scalar_one()

    crossed_threshold = (
        result.score < user.alert_score_threshold <= previous_score
    )
    big_drop = previous_score - result.score >= user.alert_score_drop
    if not (crossed_threshold or big_drop):
        return

    trip_name = trip.name or "your trip"
    subject = f"SailReady: {trip_name} dropped to {result.score}%"
    top_drivers = [d for d in result.drivers if d.severity != "ok"][:3]
    reasons = "\n".join(f"  - {d.description}" for d in top_drivers) or "  (no detail)"
    body = (
        f"{trip_name} was rescored: {previous_score}% -> {result.score}%.\n\n"
        f"Main factors:\n{reasons}\n\n"
        f"Departure: {trip.departure_time:%a %Y-%m-%d %H:%M %Z}\n"
    )

    db.add(
        Notification(
            user_id=trip.user_id,
            trip_id=trip.id,
            type="score_threshold" if crossed_threshold else "score_drop",
            channel="email",
            subject=subject,
            body=body,
        )
    )
    await db.flush()
    try:
        await asyncio.to_thread(_send_email_sync, user.email, subject, body)
    except OSError:
        pass  # mail relay down — in-app notification row still exists
