"""Local stack for integration tests: docker/docker-compose.yml through
testcontainers, or an already running stack (`make up` with
SEED_DAY=2026-11-22) when REPORTER_TEST_RUCIO_URL and
REPORTER_TEST_KEYCLOAK_URL are both set."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from testcontainers.compose import DockerCompose

DOCKER_DIR = Path(__file__).resolve().parents[2] / "docker"
SEED_DAY = date(2026, 11, 22)  # fixed, so tests never race midnight


@pytest.fixture(scope="session")
def stack() -> Iterator[dict[str, str]]:
    rucio = os.environ.get("REPORTER_TEST_RUCIO_URL")
    keycloak = os.environ.get("REPORTER_TEST_KEYCLOAK_URL")
    if rucio and keycloak:
        yield {"rucio": rucio, "keycloak": keycloak}
        return
    os.environ["SEED_DAY"] = SEED_DAY.isoformat()  # read by the compose file
    with DockerCompose(DOCKER_DIR, compose_file_name="docker-compose.yml", wait=True) as compose:

        def url(service: str, port: int) -> str:
            host = compose.get_service_host(service, port)
            return f"http://{host}:{compose.get_service_port(service, port)}"

        yield {"rucio": url("rucio-server", 80), "keycloak": url("keycloak", 8080)}


@pytest.fixture(scope="session")
def rucio_url(stack: dict[str, str]) -> str:
    return stack["rucio"]


@pytest.fixture(scope="session")
def keycloak_url(stack: dict[str, str]) -> str:
    return stack["keycloak"]
