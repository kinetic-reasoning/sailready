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

# Placeholder until the scoring engine lands (Step 4) — will invoke the rescore job
rescore:
	@echo "scoring engine not built yet (build sequence step 4)"
