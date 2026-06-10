"""Daily rescore job: re-fetch forecasts and rescore every planning/active trip.

Runs as the ADMIN role (system job crosses all users — RLS would hide every
trip from the app role). Locally: `make rescore` or cron. In AWS: EventBridge
Scheduler -> Lambda invoking this module.
"""
import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.engine.runner import rescore_trip
from app.models import Trip


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL_ADMIN"])
    sessions = async_sessionmaker(engine, expire_on_commit=False)

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
            print(f"rescoring {len(trips)} trip(s)")
            for trip in trips:
                try:
                    result = await rescore_trip(db, trip)
                    print(f"  {trip.id} {trip.name or ''}: {result.score}%")
                except ValueError as exc:
                    print(f"  {trip.id} {trip.name or ''}: skipped ({exc})")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
