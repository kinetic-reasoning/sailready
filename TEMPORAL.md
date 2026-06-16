# SailReady × Temporal — durable trip orchestration (POC branch)

This branch (`temporal-poc`) replaces the polling watcher with a **durable
workflow per trip**. It's a working, screen-shareable example of where
Temporal fits a real app — and, just as importantly, where it doesn't.

## The thesis (the one line)

> Temporal is for when the **reliability of a long-running, multi-step process
> is itself the product.** SailReady's promise is *"we'll watch your weather
> window and tell you if it changes."* In `main`, that promise lives in a
> `while True: sleep(15m)` loop in one container — if it dies mid-trip, the
> promise silently breaks. Here, the promise is a workflow: it survives worker
> and host failure, because its state is an event history Temporal replays.

## What maps to what

| Temporal concept | SailReady reality | Code |
|---|---|---|
| **Workflow** (one per trip, `id = trip-{uuid}`) | A trip's days-to-weeks lifecycle: planning → underway → debrief | `app/temporal/workflows.py` |
| **Durable timer** | "Re-check every 3h within 48h of departure, 6h within a week, daily beyond" — survives restarts, exact, not polling | `recheck_interval()` + `wait_condition(timeout=)` |
| **Activity** (auto-retried) | Fetch NOAA/Open-Meteo + score + persist + notify — the existing `rescore_trip()`, wrapped | `app/temporal/activities.py` |
| **Signal** | Trip edited (re-pace), cancelled (stop), GPS position underway | `trip_edited`, `cancel_trip`, `update_position` |
| **Query** | "What's the live score / turn-around deadline?" — no DB hit, reads workflow state | `live_state` → `GET /trips/{id}/copilot` |
| **Continue-As-New** | Bound event history on long planning horizons | `RECHECKS_BEFORE_CONTINUE` in the run loop |
| **Workflow ID = entity ID** | Dedup + a stable handle to signal/query with no run-ID bookkeeping | `app/temporal/client.py` |

The same cadence logic, the same scoring engine, the same notifications — only
the **execution model** changes: a reconciliation loop that re-derives "what's
due" every 15 minutes becomes a durable function that *is* the trip's lifecycle.

## Where Temporal is NOT the answer (say this in the interview)

- **The scoring engine** (`app/engine/scoring.py`) — a pure, deterministic,
  millisecond function. It's the thing being orchestrated, never an
  orchestrator. (It's even called *inside* an activity rather than the workflow
  so the heavy condition arrays stay out of the event history.)
- **CRUD / auth / the conditions cache** — Postgres stays the source of truth
  for *domain* state; Temporal owns *process* state. That division is the point.
- **Sub-second GPS** — signals are durable, not a low-latency bus; underway you
  debounce to "on significant movement," not every 1 Hz fix, or history explodes.
- **For one user on a $12 droplet** — the polling watcher in `main` is genuinely
  correct *today*. Temporal earns its operational weight (a server + persistence
  store + workers) at the co-pilot / multi-user stage. Knowing *when not to
  adopt* is the senior signal.

## Run it

```bash
docker compose -f docker-compose.temporal.yml up -d --build
docker compose -f docker-compose.temporal.yml run --rm api alembic upgrade head
# if the worker raced the namespace registration on first boot, once:
docker compose -f docker-compose.temporal.yml restart temporal-worker
```

- App (dev auth, you are the dev user): http://localhost:8000/app
- **Temporal UI** (watch the workflow, time-travel its history): http://localhost:8080
- Mailpit: http://localhost:8025

## The demo script (≈3 minutes)

1. In the app: add a boat, drop a trip whose **departure is 1–2 days out**,
   save the route. Saving the route starts the workflow (`replace_waypoints`
   → `_sync_watch`).
2. In the **Temporal UI**, open `trip-{id}`. Show the history:
   `rescore_trip_activity` ran → **TimerStarted, 3h** (the tightening cadence).
   The workflow is *Running*, parked on a durable timer.
3. Query live state: `GET /api/v1/trips/{id}/copilot` → phase, score,
   turn-around deadline — read straight from the workflow, no DB query.
4. Cancel the trip (Settings → status, or `PUT /trips/{id}/status cancelled`).
   In the UI: `WorkflowExecutionSignaled cancel_trip` → `TimerCanceled` →
   `WorkflowExecutionCompleted`. The signal interrupted the durable wait.
5. The money shot: while the workflow is parked on its timer,
   `docker kill` the worker, then `docker start` it. The workflow resumes on
   the same timer — **the watch survived a total process death.** That's the
   one thing the polling loop in `main` cannot do.

## Files added on this branch

```
backend/app/temporal/
  shared.py      TripParams + pure recheck_interval (sandbox-safe)
  activities.py  rescore / recompute-copilot / debrief — wrap existing runner
  workflows.py   TripWorkflow: the lifecycle as durable code
  worker.py      the worker process (replaces app/jobs/watch.py here)
  client.py      start-or-update / signal / query helpers for the API
backend/app/api/copilot.py     position (signal) + co-pilot (query) endpoints
docker-compose.temporal.yml    app + Temporal server + UI + worker
```

Wiring into the existing API is deliberately minimal and flag-gated
(`TEMPORAL_ENABLED`): trip create/edit/cancel call `_sync_watch` / `_cancel_watch`
in `app/api/trips.py`, both no-ops when the flag is off, so `main`'s behavior
is untouched.
