.PHONY: up down build logs migrate revision psql api-shell test rescore

up:
	docker compose up -d --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f api

migrate:
	docker compose run --rm api alembic upgrade head

revision:
	docker compose run --rm api alembic revision -m "$(m)"

psql:
	docker compose exec db psql -U sailready sailready

api-shell:
	docker compose exec api /bin/bash

test:
	docker compose run --rm api pytest -q

rescore:
	docker compose run --rm api python -m app.jobs.rescore

ingest-enc:
	docker compose run --rm api python -m app.charts.ingest_enc data/enc

warm-tiles:
	docker compose run --rm api python -m app.charts.warm_tiles
