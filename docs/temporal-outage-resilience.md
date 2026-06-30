# How Temporal turns a NOAA outage from an outage into a non-event

This is a real incident from local testing, kept as a worked example of *why* the
trip watch runs as a durable Temporal workflow instead of a polling loop — and of a
subtle way you can still get it wrong.

## What happened

While scoring a trip in the Tampa Bay area, NOAA's tide-prediction API
(`api.tidesandcurrents.noaa.gov`) started returning `504 Gateway Timeout` for several
minutes. Tide height is a required input to the grounding check, so every scoring
attempt threw:

```
httpx.HTTPStatusError: Server error '504 Gateway Timeout' for url
'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=predictions
&station=8726520&begin_date=20260630&end_date=20260701&...'
  File "/app/app/engine/runner.py", line 98, in rescore_trip
    data = await get_hourly_conditions(...)
  File "/app/app/conditions/coops.py", line 111, in fetch_tides
    resp.raise_for_status()
```

From the user's seat, scoring simply "never came back."

## The original behavior — and why it was wrong

The activity had a bounded retry policy and the workflow didn't guard the call:

```python
ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=6,          # gives up after ~1 minute of backoff
)
...
self._last = await workflow.execute_activity(rescore_trip_activity, ...)  # uncaught
```

So the worker retried six times over roughly a minute, then logged:

```
Completing activity as failed ({'activity_type': 'rescore_trip_activity',
 'attempt': 6, 'workflow_id': 'trip-7c2f29d0-...'})
```

Because nothing caught the resulting `ActivityError`, the exception propagated out of
the workflow's run method and **terminated the whole `TripWorkflow`**. A one-minute
upstream blip permanently killed a multi-day watch — the exact failure mode the
durable workflow exists to prevent. The Temporal UI showed the run as `Failed`, and
the trip had zero scores.

```
Status   WorkflowId                  Type
Failed   trip-7c2f29d0-fd89-...      TripWorkflow     <- died on the 504
Failed   trip-7c2f29d0-fd89-...      TripWorkflow     <- and again on retry
```

The irony: durability against infrastructure failure is the headline reason to use
Temporal here, and the configuration opted out of it.

## How Temporal addresses it

The machinery was always there; the fix is to use it. Three changes
(`app/temporal/workflows.py`, `app/temporal/activities.py`):

**1. Retry transient faults effectively forever, with a capped backoff.**

```python
ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=0,          # unlimited — ride out the outage until NOAA recovers
)
```

A 5-minute-capped backoff means a multi-hour outage costs at most one retry every five
minutes. The activity sits in **Retrying**, not **Failed** — the workflow stays alive
and consumes no worker thread while it waits.

**2. Classify errors so "transient" and "permanent" are treated differently.**

Retrying forever is wrong for a request that can *never* succeed (a malformed station
id returns `4xx` no matter how many times you ask). So the activity boundary
translates HTTP failures into the right Temporal semantics:

```python
try:
    return await rescore_trip(db, trip)
except httpx.HTTPStatusError as exc:
    if 400 <= exc.response.status_code < 500:
        raise ApplicationError(            # permanent — stop retrying immediately
            f"upstream rejected request ({exc.response.status_code})",
            type="UpstreamClientError", non_retryable=True,
        ) from exc
    raise                                  # 5xx / timeout — transient, let it retry
```

**3. Degrade instead of dying.** If an error *is* non-retryable, don't take the whole
multi-day watch down over one bad recheck — mark the trip `degraded`, skip this cycle,
and let the next durable timer try again:

```python
try:
    self._last = await workflow.execute_activity(rescore_trip_activity, ...)
    self._degraded = False
except ActivityError:
    self._degraded = True
    workflow.logger.warning("rescore failed (non-retryable) — skipping this cycle")
```

The `degraded` flag is exposed on the `live_state` query so the UI can surface
"scoring degraded: upstream tide API down" instead of going silent.

## The before/after, verified end-to-end

The same trip, during the same outage, under the new code stayed **Running** and then
**scored on its own the moment NOAA recovered** — no restart, no lost state:

```
Status    WorkflowId                  Type           StartTime
Running   trip-7c2f29d0-fd89-...      TripWorkflow   (survived the outage)
Failed    trip-7c2f29d0-fd89-...      TripWorkflow   (old code, same trip)
Failed    trip-7c2f29d0-fd89-...      TripWorkflow   (old code, same trip)
```

```
trip_scores for trip-7c2f29d0:  score 15, is_current=t, scored_at 16:47
```

That `Running` vs `Failed` split in the workflow history *is* the value proposition,
made concrete: identical inputs, identical outage, opposite outcomes.

## Reproduce / demo it

1. Point the tide client at an unreachable host (or pick a moment NOAA is flapping),
   start a trip, and set its route to kick off a `TripWorkflow`.
2. In the Temporal UI (`http://localhost:8080`) watch the `rescore_trip_activity`
   pending activity climb attempts and sit in **Retrying** — the workflow stays
   **Running**.
3. Restore connectivity. The next retry succeeds; the workflow scores and continues
   its recheck loop. Nothing was lost.

A clean way to make the multi-day pacing demonstrable on a call is Temporal's
time-skipping test environment, or a compressed `recheck_interval` for the demo build.
