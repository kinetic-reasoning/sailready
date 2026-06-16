"""The worker: the process that actually runs workflow + activity code.

The Temporal *server* is a durable event log + scheduler — it never executes
your code. Workers poll a task queue and do the work. This is the container
that replaces app/jobs/watch.py in the Temporal-enabled deployment.

    python -m app.temporal.worker
"""
import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from app.config import settings
from app.temporal.activities import (
    generate_debrief_activity,
    recompute_copilot_activity,
    rescore_trip_activity,
)
from app.temporal.shared import TASK_QUEUE
from app.temporal.workflows import TripWorkflow


async def main() -> None:
    client = await Client.connect(
        settings.temporal_target, namespace=settings.temporal_namespace
    )
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[TripWorkflow],
        activities=[
            rescore_trip_activity,
            recompute_copilot_activity,
            generate_debrief_activity,
        ],
    )
    print(f"[temporal-worker] polling {TASK_QUEUE} at {settings.temporal_target}", flush=True)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
