SHELL       := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
UV ?= uv
COMPOSE := docker compose -f docker/docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help sync lint format typecheck audit test-unit test test-integration coverage run up down image run-image

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

audit: ## Known vulnerabilities in the locked runtime dependencies (pip-audit)
	$(UV) export --frozen --no-dev --no-emit-project --format requirements-txt > .audit-requirements.txt
	$(UV) run pip-audit --strict --disable-pip --require-hashes -r .audit-requirements.txt
	@rm -f .audit-requirements.txt

test-unit: ## Unit tests only (no Docker)
	$(UV) run pytest tests/unit

test: ## Unit and integration tests (integration starts Docker via testcontainers)
	$(UV) run pytest tests/unit tests/integration

test-integration: ## Integration tests; set REPORTER_TEST_{RUCIO,KEYCLOAK,ARGO}_URL to reuse a running stack
	$(UV) run pytest tests/integration -m integration

coverage: ## Tests with coverage report
	$(UV) run pytest tests/unit tests/integration --cov --cov-report=term-missing --cov-report=xml

run: ## One run against `make up` (docker/local.env); REPORTER_DRY_RUN=false make run posts to the stub
	@rc=0; $(UV) run --env-file docker/local.env usage-reporter || rc=$$?; echo "exit code $$rc"

up: ## Start the local stack (Rucio + seeded history, Keycloak) and wait until healthy
	$(COMPOSE) up -d --wait

down: ## Stop the local stack and wipe volumes
	$(COMPOSE) down -v

image: ## Build the container image (usage-reporter:dev)
	docker build -t usage-reporter:dev .

run-image: image ## One run of the container against `make up` (docker/local.env)
	@rc=0; docker run --rm --network host \
	  --env-file <(sed -E "s/^(REPORTER_PROJECTS=)'(.*)'$$/\1\2/" docker/local.env) \
	  usage-reporter:dev || rc=$$?; echo "exit code $$rc"
