SHELL       := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
UV ?= uv
COMPOSE := docker compose -f docker/docker-compose.yml
CHART        := charts/dep-dlm-usage-reporter
KUBE_VERSION ?= 1.30.0

# pin the current release (https://github.com/aquasecurity/trivy/releases)
TRIVY_VERSION ?= 0.76.2
TRIVY := docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
           -v $(HOME)/.cache/trivy:/root/.cache aquasec/trivy:$(TRIVY_VERSION)

.DEFAULT_GOAL := help

.PHONY: help
help: ## List targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk -F':.*?## ' '{printf "  %-18s %s\n", $$1, $$2}'

.PHONY: sync
sync: ## Create or refresh .venv from uv.lock
	$(UV) sync --locked

.PHONY: hooks
hooks: ## Install the git pre-commit hook
	$(UV) run pre-commit install

.PHONY: check
check: ## ruff, format, import contracts, mypy (strict) and hadolint via pre-commit
	$(UV) run pre-commit run --all-files

.PHONY: scan
scan: ## Trivy: secrets and fixable HIGH/CRITICAL vulnerabilities in usage-reporter:dev (make image first)
	$(TRIVY) image --scanners vuln,secret --severity HIGH,CRITICAL \
	  --ignore-unfixed --exit-code 1 usage-reporter:dev

.PHONY: format
format: ## Auto-fix ruff findings and formatting
	$(UV) run ruff check --fix src tests
	$(UV) run ruff format src tests

.PHONY: audit
audit: ## Known vulnerabilities in the locked runtime dependencies (pip-audit)
	$(UV) export --frozen --no-dev --no-emit-project --format requirements-txt > .audit-requirements.txt
	$(UV) run pip-audit --strict --disable-pip --require-hashes -r .audit-requirements.txt
	@rm -f .audit-requirements.txt

.PHONY: test-unit
test-unit: ## Unit tests only (no Docker)
	$(UV) run pytest tests/unit

.PHONY: test-integration
test-integration: ## Integration tests; set REPORTER_TEST_{RUCIO,KEYCLOAK,ARGO}_URL to reuse a running stack
	$(UV) run pytest tests/integration -m integration

.PHONY: test
test: ## Unit and integration tests (integration starts Docker via testcontainers)
	$(UV) run pytest tests/unit tests/integration

.PHONY: coverage
coverage: ## Tests with coverage report
	$(UV) run pytest tests/unit tests/integration --cov --cov-report=term-missing --cov-report=xml

.PHONY: run
run: ## One run against `make up` (docker/local.env); REPORTER_DRY_RUN=false make run posts to the stub
	@rc=0; $(UV) run --env-file docker/local.env usage-reporter || rc=$$?; echo "exit code $$rc"

.PHONY: up
up: ## Start the local stack (Rucio + seeded history, Keycloak) and wait until healthy
	$(COMPOSE) up -d --wait

.PHONY: down
down: ## Stop the local stack and wipe volumes
	$(COMPOSE) down -v

.PHONY: image
image: ## Build the container image (usage-reporter:dev)
	docker build -t usage-reporter:dev .

.PHONY: run-image
run-image: image ## One run of the container against `make up` (docker/local.env)
	@rc=0; docker run --rm --network host \
	  --env-file <(sed -E "s/^(REPORTER_PROJECTS=)'(.*)'$$/\1\2/" docker/local.env) \
	  usage-reporter:dev || rc=$$?; echo "exit code $$rc"

.PHONY: chart-lint
chart-lint: ## Helm lint (strict) and kubeconform on the rendered chart, default and ci/ values
	helm lint --strict $(CHART)
	helm template test $(CHART) | kubeconform -strict -summary -kubernetes-version $(KUBE_VERSION)
	for f in $(CHART)/ci/*-values.yaml; do \
	  helm lint --strict $(CHART) -f $$f; \
	  helm template test $(CHART) -f $$f | kubeconform -strict -summary -kubernetes-version $(KUBE_VERSION); \
	done
