"""TripWorkflow — one durable workflow instance per trip.

This is the whole point. The trip's multi-day lifecycle that today is spread
across a 15-minute polling loop (app/jobs/watch.py), a not-yet-built co-pilot,
and a someday debrief, collapses into one linear, durable function:

    PLANNING ──recheck on a tightening cadence──▶ DEPARTURE
             ──UNDERWAY: react to GPS, recompute turn-around──▶ RETURN-BY
             ──▶ DEBRIEF ──▶ done

Durability: if the worker or the whole VM dies mid-trip, the workflow resumes
from its event history exactly where it was — the "we're watching your window"
promise survives infrastructure failure, which a polling loop's in-memory
state does not.

Determinism: no wall-clock (workflow.now()), no I/O — every side effect goes
through an activity. The recheck loop uses Continue-As-New so a multi-week
planning horizon doesn't grow an unbounded event history.
"""
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.temporal.activities import (
        RescoreResult,
        generate_debrief_activity,
        recompute_copilot_activity,
        rescore_trip_activity,
    )
    from app.temporal.shared import TripParams, as_params, parse, recheck_interval

ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=6,  # NOAA/Open-Meteo flap; ride it out, don't fail the trip
)
# Keep event history bounded: after this many rechecks, Continue-As-New.
RECHECKS_BEFORE_CONTINUE = 200


@workflow.defn
class TripWorkflow:
    def __init__(self) -> None:
        self._cancelled = False
        self._edited = False
        self._latest_position: tuple[float, float] | None = None
        self._last: RescoreResult | None = None
        self._phase = "planning"

    # ---- signals: asynchronous events INTO the running workflow --------------
    @workflow.signal
    def cancel_trip(self) -> None:
        self._cancelled = True

    @workflow.signal
    def trip_edited(self, params) -> None:
        # times/route changed — wake the timer and re-pace against new params
        self._params = as_params(params)
        self._edited = True

    @workflow.signal
    def update_position(self, lat: float, lon: float) -> None:
        self._latest_position = (lat, lon)

    # ---- query: synchronous read of live state (no history event) ------------
    @workflow.query
    def live_state(self) -> dict:
        return {
            "phase": self._phase,
            "cancelled": self._cancelled,
            "score": self._last.score if self._last else None,
            "feasible": self._last.feasible if self._last else None,
            "turn_around_deadline": self._last.turn_around_deadline if self._last else None,
        }

    @workflow.run
    async def run(self, params, rechecks_so_far: int = 0) -> None:
        self._params = as_params(params)
        rechecks = rechecks_so_far

        # ---- PLANNING / PRE-LAUNCH: recheck on a tightening cadence ----------
        while workflow.now() < parse(self._params.return_by_time) and not self._cancelled:
            self._last = await workflow.execute_activity(
                rescore_trip_activity,
                self._params.trip_id,
                start_to_close_timeout=timedelta(seconds=90),
                retry_policy=ACTIVITY_RETRY,
            )
            if self._last.status in ("completed", "cancelled"):
                return

            now = workflow.now()
            departure = parse(self._params.departure_time)
            if now >= departure:
                self._phase = "underway"
                break

            rechecks += 1
            if rechecks >= RECHECKS_BEFORE_CONTINUE:
                # bound the event history on long horizons
                workflow.continue_as_new(args=[self._params, rechecks % RECHECKS_BEFORE_CONTINUE])

            hours_out = (departure - now).total_seconds() / 3600
            interval = recheck_interval(hours_out)
            # durable sleep that wakes early on cancel or edit
            self._edited = False
            try:
                await workflow.wait_condition(
                    lambda: self._cancelled or self._edited, timeout=interval
                )
            except asyncio.TimeoutError:
                pass  # normal: the timer fired, time to recheck

        # ---- UNDERWAY: react to GPS, recompute the turn-around deadline ------
        while (
            not self._cancelled
            and workflow.now() < parse(self._params.return_by_time)
        ):
            try:
                await workflow.wait_condition(
                    lambda: self._latest_position is not None or self._cancelled,
                    timeout=timedelta(hours=1),  # also recompute hourly with no fix
                )
            except asyncio.TimeoutError:
                pass
            if self._cancelled:
                break
            lat, lon = self._latest_position or (0.0, 0.0)
            self._latest_position = None
            self._last = await workflow.execute_activity(
                recompute_copilot_activity,
                args=[self._params.trip_id, lat, lon],
                start_to_close_timeout=timedelta(seconds=90),
                retry_policy=ACTIVITY_RETRY,
            )
            if self._last.status in ("completed", "cancelled"):
                break

        # ---- DEBRIEF --------------------------------------------------------
        self._phase = "debrief"
        if not self._cancelled:
            await workflow.execute_activity(
                generate_debrief_activity,
                self._params.trip_id,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=ACTIVITY_RETRY,
            )
        self._phase = "done"
