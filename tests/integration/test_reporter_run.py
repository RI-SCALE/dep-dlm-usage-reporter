"""End to end: `usage-reporter` against seeded Rucio, Keycloak and the ARGO
stub (Design-001, step 4).

Runs the real entry point in a subprocess with REPORTER_* settings, then reads
what the stub received from WireMock's admin API. The seed day has three
mapped groups and one unmapped account (`ghost`), so every run exits 2.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from tests.integration.conftest import SEED_DAY

pytestmark = pytest.mark.integration

INSTALLATION = "6afaff4e947efcc6dea636e2"
DEFINITION = "6afc3e7801adaea4c9c12777"
METRICS = f"/accounting-system/installations/{INSTALLATION}/metrics"
EXPECTED = {("suc1", 151), ("suc2", 7), ("suc3", 20)}


@pytest.fixture
def argo(argo_url: str) -> Iterator[httpx.Client]:
    """WireMock admin client; mappings back to the files and journal cleared."""
    with httpx.Client(base_url=argo_url) as admin:
        admin.post("/__admin/mappings/reset").raise_for_status()
        admin.delete("/__admin/requests").raise_for_status()
        yield admin


def _received(argo: httpx.Client, method: str) -> list[dict[str, Any]]:
    requests = argo.get("/__admin/requests").json()["requests"]
    return [r["request"] for r in requests if r["request"]["method"] == method]


def _run(
    rucio_url: str, keycloak_url: str, argo_url: str, **extra: str
) -> subprocess.CompletedProcess[str]:
    client = {
        "installation_id": INSTALLATION,
        "client_id": "usage-reporter-enes",
        "client_secret_env": "REPORTER_SECRET_ENES",
    }
    env = {
        "PATH": os.environ["PATH"],
        "REPORTER_RUCIO_HOST": rucio_url,
        "REPORTER_RUCIO_TOKEN_URL": f"{keycloak_url}/realms/dep/protocol/openid-connect/token",
        "REPORTER_RUCIO_CLIENT_ID": "usage-reporter-rucio",
        "REPORTER_RUCIO_CLIENT_SECRET": "rucio-reporter-secret",
        "REPORTER_ARGO_ENDPOINT": argo_url,
        "REPORTER_ARGO_METRIC_DEFINITION_ID": DEFINITION,
        "REPORTER_ARGO_TOKEN_URL": f"{keycloak_url}/realms/dep/protocol/openid-connect/token",
        "REPORTER_PROJECTS": json.dumps({"RI-SCALE_ENES": client, "RI-SCALE_EISCAT": client}),
        "REPORTER_SECRET_ENES": "enes-secret",
        "REPORTER_DAY": SEED_DAY.isoformat(),
        **extra,
    }
    return subprocess.run(
        [sys.executable, "-m", "usage_reporter.main"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_dry_run_prints_the_records_and_sends_nothing(
    rucio_url: str, keycloak_url: str, argo_url: str, argo: httpx.Client
) -> None:
    run = _run(rucio_url, keycloak_url, argo_url)
    assert run.returncode == 2, run.stderr  # ghost is unmapped
    lines = [json.loads(line) for line in run.stdout.splitlines()]
    assert {(r["group_id"], r["value"]) for r in lines} == EXPECTED
    assert "ghost" in run.stderr
    assert argo.get("/__admin/requests").json()["requests"] == []


def test_posts_one_metric_per_group_for_the_day(
    rucio_url: str, keycloak_url: str, argo_url: str, argo: httpx.Client
) -> None:
    run = _run(rucio_url, keycloak_url, argo_url, REPORTER_DRY_RUN="false")
    assert run.returncode == 2, run.stderr

    lookups = _received(argo, "GET")
    assert {r["url"].split("?")[0] for r in lookups} == {METRICS}
    headers = [{k.lower(): v for k, v in r["headers"].items()} for r in lookups]
    assert all(h["authorization"].startswith("Bearer ") for h in headers)
    posts = [json.loads(r["body"]) for r in _received(argo, "POST")]
    assert {(p["group_id"], p["value"]) for p in posts} == EXPECTED
    assert {(p["time_period_start"], p["time_period_end"]) for p in posts} == {
        (f"{SEED_DAY}T00:00:00Z", f"{SEED_DAY}T23:59:59Z")
    }
    assert {p["metric_definition_id"] for p in posts} == {DEFINITION}
    assert _received(argo, "PATCH") == []


def test_a_day_already_in_argo_is_left_as_is(
    rucio_url: str, keycloak_url: str, argo_url: str, argo: httpx.Client
) -> None:
    stored = [
        {
            "id": f"m-{group}",
            "installation_id": INSTALLATION,
            "metric_definition": {"id": DEFINITION},
            "time_period_start": f"{SEED_DAY}T00:00:00Z",
            "time_period_end": f"{SEED_DAY}T23:59:59Z",
            "value": float(value),
            "group_id": group,
        }
        for group, value in EXPECTED
    ]
    argo.post(
        "/__admin/mappings",
        json={
            "priority": 1,
            "request": {"method": "GET", "urlPath": METRICS},
            "response": {
                "status": 200,
                "jsonBody": {"total_pages": 1, "total_elements": len(stored), "content": stored},
            },
        },
    ).raise_for_status()

    run = _run(rucio_url, keycloak_url, argo_url, REPORTER_DRY_RUN="false")
    assert run.returncode == 2, run.stderr
    assert "'exists': 3" in run.stderr
    assert _received(argo, "POST") == []
    assert _received(argo, "PATCH") == []
