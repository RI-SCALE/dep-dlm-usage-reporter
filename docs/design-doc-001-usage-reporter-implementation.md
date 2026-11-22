# Design-001: Usage reporter implementation

- **Status:** Proposed
- **Owner:** DEP DLM
- **Related ADR(s):** [ADR-010](https://github.com/RI-SCALE/dep-dlm-testbed/blob/main/docs/adrs/adr-010-report-transfer-usage-to-argo.md) (report daily transfer usage to ARGO) and [Design-009](https://github.com/RI-SCALE/dep-dlm-testbed/blob/main/docs/design/design-doc-009-dep-dlm-transfer-usage-reporter-for-argo-accounting.md)
  (the reporter's behaviour), both in the DEP DLM testbed docs. Those say *what* the job
  does; this doc says *how* this repository builds it.

## Problem

Design-009 defines a daily job that reads finished transfers from Rucio, maps
accounts to DEP and use case, and upserts daily totals into ARGO Accounting.
This repository is empty apart from the README. Before writing code we need to
fix:

- **Language and layout**, so the code stays small and testable.
- **Failure handling** against two external APIs. The ARGO metric POST
  (`POST /accounting-system/installations/{id}/metrics`) is not idempotent, so a
  blind retry after a timeout can create duplicates.
- **A local test stack.** There is no public ARGO image, and Rucio only moves
  requests into `requests_history` after real transfers (FTS), so integration
  tests need seeded data and a stub.
- **Development order.** ARGO prerequisites (service account, metric
  definition, installation IDs) are still pending, and should not block
  development.

## Goals

- Python 3.12, about 400–600 lines of source, with no web framework.
- A pure core (time window, aggregation, mapping rules) covered by unit tests
  written first.
- Bounded, observable failure: timeouts, retries on transient errors, and an
  abort that the next run's lookback recovers.
- One `make up` / `make test` stack that runs the whole job locally.

## Non-goals

- **A long-running service, HTTP API, or OpenAPI codegen.** It's a CronJob.
- **A full OpenTelemetry stack.** Structured logs and exit codes are enough for
  a daily job; add metrics later if operations need them.
- **A stateful circuit breaker.** There is no state that outlives one run; see
  Design.
- **Testing against a real ARGO instance locally.** That happens in staging
  against ARGO devel.

## Design

### Language

Python. Startup time and throughput don't matter for one run a day; the DLM
team and the sibling authz-service already use Python, ruff, mypy, pytest and
testcontainers, so tooling and hand-over carry over. Go would only buy a static
binary.

### Tooling

[uv](https://docs.astral.sh/uv/) manages Python 3.12, the virtual environment
and dependencies: runtime dependencies in `[project]`, tools in the `dev`
dependency group, all pinned in a committed `uv.lock`. The build backend is
`uv_build`. The Makefile is a thin index over `uv run` (lint, typecheck, test,
up/down), so the target names match authz-service. CI installs uv with
`astral-sh/setup-uv` and runs `make sync` (`uv sync --locked`).

### Layout

Follows the authz-service structure, without the web parts:

```
src/usage_reporter/
  core/
    model.py        # Transfer, UsageRecord, Window, RunResult (frozen dataclasses)
    ports.py        # TransferSource, GroupMapping, AccountingSink (Protocols)
    window.py       # window(today, lookback_days) -> list[date]
    aggregate.py    # aggregate(transfers, mapping, days) -> AggregateResult
  adapters/
    rucio.py        # RucioRestSource, RucioAttributeMapping (httpx)
    argo.py         # ArgoSink: search, POST, PATCH (httpx)
    token.py        # client-credentials token, refreshed on 401
    resilience.py   # retry policy and per-run failure budget
    stdout.py       # StdoutSink for dry-run
  settings.py       # pydantic-settings, secrets from env vars only
  main.py           # composition root and CLI entry point
tests/unit/  tests/integration/
docker/  docker-compose.yml  realm.json  argo-stubs/  bootstrap-db.py
Dockerfile  Makefile  pyproject.toml  uv.lock
```

Both APIs are called with `httpx` directly: Rucio needs three endpoints (auth,
history, account attributes) and ARGO four (token, search, POST, PATCH). The
Rucio client and `argo-acc-library` would add weight, and the library's
documented examples cover add and list but not search or update.

import-linter enforces `core` → nothing, `adapters` → `core`, `main` → all.

### Core signatures

```python
def window(today: date, lookback_days: int) -> list[date]: ...

def aggregate(
    transfers: Iterable[Transfer],
    mapping: Mapping[str, Group | None],
    days: Sequence[date],
) -> AggregateResult:  # records, unmapped bytes per account, skipped rows
    ...

class AccountingSink(Protocol):
    def upsert(self, record: UsageRecord) -> UpsertResult: ...
```

### Resilience

| Concern | Behaviour |
| --- | --- |
| Timeouts | Connect and read timeouts on every call (config) |
| Transient errors | Retry connection errors, 429, 502–504 with exponential backoff and jitter, honouring `Retry-After` (`tenacity`) |
| Per-run budget | After N consecutive failures to one dependency, abort with a distinct exit code. This is the circuit breaker, scoped to the run. |
| ARGO POST timeout | Never retry blindly: search for the record again, then PATCH or POST |
| 401 mid-run | Fetch a new token once, retry once |
| Other 4xx | Fail that record, continue, non-zero exit at the end |

Exit codes: `0` ok, `2` warnings (unmapped accounts), `3` some records failed,
`4` aborted (dependency down), `1` config error.

### Configuration

Non-secret settings in a ConfigMap, secrets as environment variables from a
Kubernetes Secret (synced from Vault where available):

```
REPORTER_RUCIO_HOST, REPORTER_RUCIO_ACCOUNT
REPORTER_ARGO_ENDPOINT, REPORTER_ARGO_METRIC_DEFINITION_ID
REPORTER_ARGO_TOKEN_URL, REPORTER_ARGO_CLIENT_ID, REPORTER_ARGO_CLIENT_SECRET
REPORTER_PROJECTS='{"enes": "<installation id>", ...}'
REPORTER_LOOKBACK_DAYS=2  REPORTER_DRY_RUN=true
REPORTER_TIMEOUT_SECONDS=10  REPORTER_MAX_CONSECUTIVE_FAILURES=5
```

### Local stack (`docker/docker-compose.yml`)

| Service | Purpose |
| --- | --- |
| `postgres`, `rucio-server`, `rucio-init` | Real Rucio API. Init bootstraps accounts and attributes, and seeds `requests_history` with SQL (`rucio-seed.sql`) |
| `keycloak` | Client-credentials tokens (`realm.json`) |
| `argo-stub` | WireMock with ARGO's search, POST and PATCH from the documented contract |
| `toxiproxy` | Latency, resets and timeouts between the reporter and both APIs |

Integration tests start the same images through testcontainers, as in
authz-service; the compose file is for `make up` and manual runs.

## Touch points

| File / component | Change |
| --- | --- |
| `src/usage_reporter/` | New package as above |
| `tests/` | Unit and integration suites |
| `docker/` | Compose stack, realm, ARGO stubs, Rucio seed |
| `Dockerfile` | Slim, non-root image running `usage-reporter` |
| `Makefile`, `pyproject.toml`, `uv.lock` | uv sync, lint, typecheck, test, up/down, image |
| `.github/workflows/ci.yml` | Lint, typecheck, unit and integration tests, image build |

## Fallback / safety behavior

- **Missing or invalid config:** exit `1` before any call.
- **Dry-run default:** `REPORTER_DRY_RUN=true` writes records to stdout only.
- **Unmapped account:** excluded, logged with its bytes, exit `2`.
- **More than one ARGO match for a day and group:** don't write, log, exit `3`.
- **Dependency down:** abort with exit `4`; the next run's lookback re-sends the
  missed days.
- **Timestamps:** Rucio times without a timezone are treated as UTC.

## Testing

Test-first. Each case is written before the code that passes it.

- **Unit (core):**
  - Time: 23:59:59.999 versus 00:00:00 the next day, naive timestamps as UTC,
    lookback overlap.
  - Data: null `transferred_at` or `bytes`, duplicate request IDs across pages,
    empty history, large byte values.
  - Mapping: one attribute missing, `project_id` not configured, several
    accounts summing into one group, one account across several days.
- **Unit (adapters, with `httpx.MockTransport`):** paging (final page exactly
  at the limit), PATCH when found, POST when not, multiple matches, POST
  timeout followed by search, 401 refresh, 429 `Retry-After`, retry exhaustion
  and abort.
- **Integration:** full run against the compose stack (seeded Rucio, Keycloak,
  ARGO stub), asserting the exact requests the stub received; toxiproxy cases
  for slow and dropped connections.
- **CI:** ruff, mypy (strict), import-linter, unit and integration tests, image
  build on every pull request.

## Sequencing

Development doesn't wait for ARGO.

1. Skeleton: `pyproject.toml` and `uv.lock` (uv), Makefile, CI, import-linter contracts.
2. Core, test-first: `window`, `aggregate`, mapping rules.
3. Compose stack and Rucio adapter, with integration tests on seeded history.
4. ARGO adapter against the stub, plus resilience and toxiproxy tests.
5. Dry-run against the real DEP Rucio (read-only); check totals against a
   manual query.
6. Testbed CronJob (dep-dlm-testbed) against ARGO devel once the service
   account exists; rehearse a backfill there.
7. Production CronJob (dep-dlm-deployment): a few days in dry-run, then live,
   then backfill from the agreed start date.

In parallel, outside this repository: ARGO service account and entitlements,
the data transfer metric definition, installation IDs, the Rucio account
attribute convention, and the time-filter question to Rucio developers.

## Open questions

- **ARGO search:** can it filter on installation, metric definition and
  `group_id` with equality? If not, the adapter lists the installation's
  metrics and filters client-side.
- **Installations:** one `CERN-Rucio` installation for all four DEPs, or one
  per DEP project? This decides whether `REPORTER_PROJECTS` maps to one ID or
  four.
- **Rucio authentication:** OIDC token from DEP IAM, or userpass for the
  reporter account?
- **Multi-hop transfers:** exclude intermediate hops, and how to recognise them
  in history?
- **ARGO stub fidelity:** does GRNET publish an OpenAPI spec or image we can
  generate the stub from, instead of hand-written mappings?
