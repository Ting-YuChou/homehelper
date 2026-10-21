COMPOSE := docker compose -f infra/docker-compose.yml

.PHONY: up down logs ps test test-integration lint fmt migrate ingest eval-smoke

up: ## Start postgres, redis, api, web
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

test: ## Unit tests
	uv run pytest

test-integration: ## Unit + integration tests (needs `make up`)
	RUN_INTEGRATION=1 uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	pnpm --filter web lint
	pnpm --filter web typecheck

fmt:
	uv run ruff check --fix .
	uv run ruff format .

migrate: ## Apply DB migrations (needs `make up`)
	uv run alembic -c apps/api/alembic.ini upgrade head

ingest:
	@echo "Not implemented yet (M1-04)"

eval-smoke:
	@echo "Not implemented yet (M2-05)"
