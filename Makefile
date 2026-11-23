# usage-reporter (Design-001). Thin index over uv; `make help` lists targets.

UV ?= uv
COMPOSE := docker compose -f docker/docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help sync lint format typecheck test-unit test test-integration coverage run up down

help: ## List targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

sync: ## Create or refresh .venv from uv.lock
	$(UV) sync --locked

lint: ## ruff and the import contracts
	$(UV) run ruff check src tests
	$(UV) run ruff format --check src tests
	$(UV) run lint-imports

format: ## Auto-fix ruff findings and formatting
	$(UV) run ruff check --fix src tests
	$(UV) run ruff format src tests

typecheck: ## mypy (strict)
	$(UV) run mypy

test-unit: ## Unit tests only (no Docker)
	$(UV) run pytest tests/unit

test: ## Unit and integration tests (integration starts Docker via testcontainers)
	$(UV) run pytest tests/unit tests/integration

test-integration: ## Integration tests; set REPORTER_TEST_RUCIO_URL to reuse a running stack
	$(UV) run pytest tests/integration -m integration

coverage: ## Tests with coverage report
	$(UV) run pytest tests/unit tests/integration --cov --cov-report=term-missing --cov-report=xml

run: ## Run one cycle locally (dry-run unless REPORTER_DRY_RUN=false)
	$(UV) run usage-reporter

up: ## Start the local stack (Rucio + seeded history) and wait until healthy
	$(COMPOSE) up -d --wait

down: ## Stop the local stack and wipe volumes
	$(COMPOSE) down -v
