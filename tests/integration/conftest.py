"""Rucio stack for integration tests: docker/docker-compose.yml through
testcontainers, or an already running server via REPORTER_TEST_RUCIO_URL."""

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
def rucio_url() -> Iterator[str]:
    if url := os.environ.get("REPORTER_TEST_RUCIO_URL"):
        yield url  # stack already up (make up with SEED_DAY=2026-11-22)
        return
    os.environ["SEED_DAY"] = SEED_DAY.isoformat()  # read by the compose file
    with DockerCompose(DOCKER_DIR, compose_file_name="docker-compose.yml", wait=True) as stack:
        host = stack.get_service_host("rucio-server", 80)
        port = stack.get_service_port("rucio-server", 80)
        yield f"http://{host}:{port}"
