COMPOSE := docker compose -f infra/docker-compose.yml

.PHONY: up down logs ps test test-agent-cov test-integration lint fmt migrate seed-mock ingest eval-smoke openapi

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

test-agent-cov: ## Journey engine + guardrail tests with the >= 90% coverage gate (spec M3-05)
	uv run pytest apps/api/tests/unit/agent --cov=homehelper.agent.engine \
		--cov=homehelper.agent.guardrails --cov-report=term-missing --cov-fail-under=90

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
	uv run homehelper db upgrade

seed-mock: ## Reset the MCP mock tables to data/mock/ (needs `make migrate`)
	uv run homehelper mcp seed

ingest: ## Build a new kb_version from the reviewed manifest (needs `make up migrate`)
	uv run homehelper ingest

eval-smoke: ## Smoke suite against the stub agent (LLM simulator + judge, about USD 0.16)
	uv run evals run --suite smoke

openapi: ## Regenerate the OpenAPI schema and the web app's TS types (contract check, spec §18.5)
	uv run python -m homehelper.api.openapi apps/web/lib/api/openapi.json
	pnpm --filter web gen:api
