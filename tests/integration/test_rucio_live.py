"""Rucio adapter and core against a real rucio-server seeded by
docker/rucio-seed.py (Design-001, steps 3 and 6).

The `rucio_url` and `keycloak_url` fixtures (conftest.py) start
docker/docker-compose.yml through testcontainers, or reuse a running stack.
The client authenticates with an OIDC client-credentials token from Keycloak,
which Rucio maps to the `reporter` account by SUB/ISS.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.integration.conftest import SEED_DAY
from usage_reporter.adapters.rucio import (
    RucioAttributeMapping,
    RucioClient,
    RucioRestSource,
    rucio_token_auth,
)
from usage_reporter.adapters.token import ClientCredentials
from usage_reporter.core.aggregate import aggregate
from usage_reporter.core.window import day_bounds

pytestmark = pytest.mark.integration

KNOWN = frozenset({"RI-SCALE_ENES", "RI-SCALE_EISCAT"})


@pytest.fixture
def client(rucio_url: str, keycloak_url: str) -> Iterator[RucioClient]:
    credentials = ClientCredentials(
        f"{keycloak_url}/realms/dep/protocol/openid-connect/token",
        "usage-reporter-rucio",
        "rucio-reporter-secret",
    )
    client = RucioClient(rucio_url, rucio_token_auth(credentials))
    yield client
    client.close()
    credentials.close()


def test_seeded_day_aggregates_per_project_and_use_case(client: RucioClient) -> None:
    start, end = day_bounds(SEED_DAY)
    source = RucioRestSource(client, page_size=2)  # small pages to exercise paging
    mapping = RucioAttributeMapping(client, KNOWN)

    transfers = list(source.finished_transfers(start, end))
    accounts = {t.account for t in transfers}
    result = aggregate(transfers, {a: mapping.resolve(a) for a in accounts}, [SEED_DAY])

    assert {(r.project_id, r.group_id, r.bytes) for r in result.records} == {
        ("RI-SCALE_ENES", "suc1", 151),  # 100 + 50 + 1 at 23:59:59; next-day 999 excluded
        ("RI-SCALE_ENES", "suc2", 7),  # FAILED 500 excluded
        ("RI-SCALE_EISCAT", "suc3", 20),
    }
    assert result.unmapped == {"ghost": 30}
    assert result.skipped == 0
