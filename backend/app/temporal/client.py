"""Thin client helpers the API uses to drive workflows.

Workflow ID = "trip-{uuid}". Using the business entity's ID as the workflow ID
gives two things for free: dedup (starting the same trip twice is a no-op via
the reuse policy) and a stable handle to signal/query without tracking run IDs.
"""
from temporalio.client import Client, WorkflowFailureError
from temporalio.service import RPCError

from app.config import settings
from app.temporal.shared import TASK_QUEUE, TripParams
from app.temporal.workflows import TripWorkflow

_client: Client | None = None


async def get_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(
            settings.temporal_target, namespace=settings.temporal_namespace
        )
    return _client


def workflow_id(trip_id: str) -> str:
    return f"trip-{trip_id}"


async def start_or_update_trip_watch(params: TripParams) -> None:
    """Create-or-update: start the workflow, or if one is already running for
    this trip, signal it that the trip's params changed. The workflow ID being
    the trip ID is what makes this clean — no run-ID bookkeeping."""
    client = await get_client()
    try:
        await client.start_workflow(
            TripWorkflow.run,
            args=[params],
            id=workflow_id(params.trip_id),
            task_queue=TASK_QUEUE,
        )
    except Exception as exc:  # already running -> it's an edit
        if "already" in str(exc).lower():
            await signal_edited(params.trip_id, params)
        else:
            raise


async def _handle(trip_id: str):
    client = await get_client()
    return client.get_workflow_handle(workflow_id(trip_id))


async def signal_position(trip_id: str, lat: float, lon: float) -> None:
    await (await _handle(trip_id)).signal(TripWorkflow.update_position, args=[lat, lon])


async def signal_edited(trip_id: str, params: TripParams) -> None:
    await (await _handle(trip_id)).signal(TripWorkflow.trip_edited, params)


async def signal_cancel(trip_id: str) -> None:
    await (await _handle(trip_id)).signal(TripWorkflow.cancel_trip)


async def query_state(trip_id: str) -> dict | None:
    try:
        return await (await _handle(trip_id)).query(TripWorkflow.live_state)
    except (RPCError, WorkflowFailureError):
        return None  # no running workflow for this trip
