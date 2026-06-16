"""Types and pure helpers shared between the workflow and its clients.

This module is imported INSIDE the Temporal workflow sandbox, so it must stay
deterministic and dependency-light: dataclasses + pure functions only. No
sqlalchemy, no I/O, no wall-clock — the workflow gets time from workflow.now().
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

TASK_QUEUE = "sailready-trips"


@dataclass
class TripParams:
    """Everything the workflow needs to pace itself — no DB handle, all JSON-safe.
    Times are ISO-8601 strings (datetimes survive Temporal's data converter, but
    strings keep the event history obvious when you read it in the UI)."""

    trip_id: str
    departure_time: str  # ISO-8601
    return_by_time: str  # ISO-8601


def as_params(x) -> "TripParams":
    """Coerce whatever the data converter handed us into a TripParams.
    Temporal's JSON converter may deliver a dataclass as a plain dict across
    the workflow boundary; this makes the workflow robust either way."""
    return x if isinstance(x, TripParams) else TripParams(**x)


def parse(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def recheck_interval(hours_to_departure: float) -> timedelta:
    """Cadence tightens as departure nears — ported verbatim from the polling
    watcher (app/jobs/watch.py) to show the logic is unchanged; only the
    *execution model* moves from a reconciliation loop to a durable timer."""
    if hours_to_departure <= 48:
        return timedelta(hours=3)
    if hours_to_departure <= 7 * 24:
        return timedelta(hours=6)
    return timedelta(hours=24)
