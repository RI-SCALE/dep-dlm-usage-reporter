# Contributing

Lean on purpose: follow the standards below, keep changes small, and
prefer plain functions and dataclasses over new abstractions.

## Layout

```
src/usage_reporter/
  core/        pure logic, standard library only (no httpx, no pydantic)
    model.py       data types (frozen dataclasses)
    window.py      reporting days, UTC day bounds
    aggregate.py   bytes per (day, project, group)
    mapping.py     Rucio account attributes -> ARGO project and group
    ports.py       Protocols the adapters implement
    report.py      one run: read, map, sum, report -> RunSummary
  adapters/    I/O behind the ports: rucio.py, argo.py, token.py, stdout.py
  settings.py  REPORTER_* configuration (pydantic-settings)
  main.py      composition root: settings -> adapters -> run -> exit code
tests/
  unit/        one module per source module, no network
  integration/ against the local stack in docker/
docker/        local stack: Rucio, Keycloak, ARGO stubs (WireMock)
charts/        Helm chart for the CronJob (values.schema.json validates values)
docs/          Design-001, ARGO integration notes, this guide
```

Dependencies point inwards: `adapters` and `main` import `core`, never
the other way round ([ports and adapters][hexagonal]); the import
contracts (`make check`) enforce this.

## Rules worth knowing

- **Errors:** raise a `RecordError` subclass when one record fails and the
  others can still go out; any other exception aborts the run (exit 4).
- **ARGO: each day is reported once.** Look up, POST if missing, never
  PATCH or blindly retry a POST that may have landed (see `argo.py`).
- **Time is UTC**; days are half-open `[start, end)` (`core/window.py`).
- **Configuration** is `REPORTER_*` in `settings.py` plus the README table,
  in the same change (and the chart's values and schema if it's set
  there); secrets come from the environment as `SecretStr` and are never
  logged.

## Style

- [PEP 8] for layout (ruff), [PEP 257] for docstrings: one line saying
  what, more only when the why isn't obvious. Module docstrings name the
  design they implement ([Design-001], [Design-009]).
- Type hints everywhere ([PEP 484], mypy strict), ports as
  `typing.Protocol` ([PEP 544]), `from __future__ import annotations` at
  the top.
- Prefer frozen dataclasses and pure functions; inject I/O (httpx
  `transport`, clocks) so unit tests need no network.
- Log with `%`-style arguments (`log.info("x=%s", x)`), not f-strings
  ([logging HOWTO][logging]).
- Comments explain why, not what.

## Tests

- Unit tests for every behaviour change; fake HTTP through the adapters'
  `transport` argument and time through a fake clock.
- Integration tests when an adapter's contract with Rucio, the IdP or
  ARGO changes (`make test-integration`, needs Docker).
- Run `make hooks` once: ruff, the format check, the import contracts and
  mypy then run on every commit (`make format` fixes what ruff reports).
- CI (`.github/workflows/ci.yml`) runs `check`, `audit`, `test-unit`,
  `test-integration`, the image build and `chart-lint`; run the same make
  targets locally before opening a PR.

## Commits and releases

- [Conventional Commits][cc]: `feat:`, `fix:`, `refactor:`, `chore:`,
  `docs:`, `test:`, `ci:`. Squash-merge PRs with one message describing
  the end state.
- Releases: README, *Releasing*. `pyproject.toml` is the only version
  source besides the chart; don't add `__version__`.

[Design-001]: design-doc-001-usage-reporter-implementation.md
[Design-009]: https://github.com/RI-SCALE/dep-dlm-testbed/blob/main/docs/design/design-doc-009-dep-dlm-transfer-usage-reporter-for-argo-accounting.md
[hexagonal]: https://alistair.cockburn.us/hexagonal-architecture/
[PEP 8]: https://peps.python.org/pep-0008/
[PEP 257]: https://peps.python.org/pep-0257/
[PEP 484]: https://peps.python.org/pep-0484/
[PEP 544]: https://peps.python.org/pep-0544/
[logging]: https://docs.python.org/3/howto/logging.html#optimization
[cc]: https://www.conventionalcommits.org/en/v1.0.0/