# dep-dlm-usage-reporter

![Status: work in progress](https://img.shields.io/badge/status-work%20in%20progress-orange)

Daily job that reports DEP DLM data-transfer usage from Rucio to ARGO Accounting,
per DEP project and use case (RI-SCALE). Design: [Design-001](docs/design-doc-001-usage-reporter-implementation.md).

## Getting started

Needs [uv](https://docs.astral.sh/uv/) and, for integration tests, Docker.

```
make sync       # create .venv from uv.lock (Python 3.12)
make lint       # ruff and the import contracts
make typecheck  # mypy (strict)
make test-unit  # unit tests
make help       # all targets
```
