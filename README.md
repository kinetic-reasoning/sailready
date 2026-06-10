# SailReady (sailready.ai)

Sailing trip-planning and decision engine. Creates a Trip (start, destination, departure/return window, boat), samples forecast conditions at each waypoint **at the time you'll actually be there**, and scores Go/No-Go based on the worst constraint violation — including whether the return leg closes the loop inside your window.

Full specification: [SPEC.md](SPEC.md)

## Local development

Requirements: Docker + Docker Compose.

```bash
make up        # build + start PostGIS, API (hot reload), Mailpit
make migrate   # apply database migrations
make logs      # tail the API
```

- API: http://localhost:8000 — interactive docs at http://localhost:8000/docs
- Mailpit (catches all outbound email): http://localhost:8025
- Postgres: localhost:5432 (`sailready`/`sailready`)

Local auth runs in dev mode (`AUTH_MODE=dev`): all requests resolve to the dev user configured in `docker-compose.yml`. Real auth (AWS Cognito + Google OAuth) arrives with the cloud deployment step.

### Database roles

- `sailready` — admin/migration role (owns schema, applies RLS policies)
- `sailready_app` — what the API connects as; **row-level security enforced**, cannot see other users' rows even if application code has a bug

## Layout

```
backend/          FastAPI app (Python 3.12)
  app/            application code
  alembic/        database migrations
frontend/         React PWA (build sequence step 5)
docker-compose.yml
SPEC.md           the single source of truth for all decisions
```
