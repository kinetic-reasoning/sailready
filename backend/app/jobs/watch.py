"""Trip watcher — the airline-style "we're watching your trip" loop.

Continuously re-checks planning/active trips on a cadence that tightens as
departure approaches, persisting fresh scores and firing notifications/email
when a score crosses the user's alert thresholds (runner._maybe_notify).

Upstream API politeness: rescores read through the conditions cache
(forecast TTL 3h, tide/current predictions 24h), so even the 3h cadence hits
each external API at most once per TTL per location — no polling spam.

Runs as the ADMIN role (crosses all users; RLS would blind the app role).
Locally: a compose service. In AWS: EventBridge Scheduler -> Lambda.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.engine.runner import rescore_trip
from app.models import Trip

TICK_SECONDS = 15 * 60  # how often the watcher wakes to see what's due


def recheck_interval(hours_to_departure: float) -> timedelta:
    if hours_to_departure <= 48:
        return timedelta(hours=3)  # departure imminent: forecast churn matters
    if hours_to_departure <= 7 * 24:
        return timedelta(hours=6)
    return timedelta(hours=24)  # far out: daily is plenty


async def tick(sessions) -> None:
    now = datetime.now(timezone.utc)
    async with sessions() as db:
        async with db.begin():
            trips = (
                (
                    await db.execute(
                        select(Trip)
                        .where(Trip.status.in_(["planning", "active"]))
                        .options(selectinload(Trip.waypoints))
                    )
                )
                .scalars()
                .all()
            )
            for trip in trips:
                if trip.return_by_time < now:
                    continue  # window already passed
                if not trip.waypoints:
                    continue  # nothing to check yet
                hours_out = max(
                    (trip.departure_time - now).total_seconds() / 3600, 0.0
                )
                due = recheck_interval(hours_out)
                last = trip.current_score_updated_at
                if last is not None and now - last < due:
                    continue
                try:
                    result = await rescore_trip(db, trip)
                    print(
                        f"[watch] {trip.name or trip.id}: {result.score}% "
                        f"(next check in {due})",
                        flush=True,
                    )
                except Exception as exc:  # noqa: BLE001 — keep the watcher alive
                    print(f"[watch] {trip.id} failed: {exc}", flush=True)


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL_ADMIN"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    print("[watch] trip watcher started", flush=True)
    while True:
        try:
            await tick(sessions)
        except Exception as exc:  # noqa: BLE001
            print(f"[watch] tick error: {exc}", flush=True)
        await asyncio.sleep(TICK_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
