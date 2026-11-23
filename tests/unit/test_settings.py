"""REPORTER_* settings: defaults, per-project clients and secrets."""

from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from usage_reporter.settings import ConfigError, Settings

PROJECTS = {
    "RI-SCALE_ENES": {
        "installation_id": "6afaff4e947efcc6dea636e2",
        "client_id": "usage-reporter-enes",
        "client_secret_env": "REPORTER_SECRET_ENES",
    }
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key, value in {
        "REPORTER_RUCIO_HOST": "http://rucio",
        "REPORTER_RUCIO_TOKEN_URL": "http://keycloak/token",
        "REPORTER_RUCIO_CLIENT_ID": "usage-reporter-rucio",
        "REPORTER_RUCIO_CLIENT_SECRET": "rucio-pw",
        "REPORTER_ARGO_METRIC_DEFINITION_ID": "6afc3e7801adaea4c9c12777",
        "REPORTER_ARGO_TOKEN_URL": "http://keycloak/token",
        "REPORTER_PROJECTS": json.dumps(PROJECTS),
    }.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_defaults_are_safe(env: pytest.MonkeyPatch) -> None:
    settings = Settings()
    assert settings.dry_run is True
    assert settings.lookback_days == 0
    assert settings.day is None
    assert settings.argo_endpoint == "https://api.devel.acc.argo.grnet.gr"
    assert settings.projects["RI-SCALE_ENES"].installation_id == "6afaff4e947efcc6dea636e2"


def test_an_explicit_day_for_re_runs(env: pytest.MonkeyPatch) -> None:
    env.setenv("REPORTER_DAY", "2026-11-20")
    assert Settings().day == date(2026, 11, 20)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("REPORTER_LOOKBACK_DAYS", "-1"),
        ("REPORTER_TIMEOUT_SECONDS", "0"),
        ("REPORTER_PROJECTS", "{}"),
    ],
)
def test_invalid_values_are_rejected(env: pytest.MonkeyPatch, key: str, value: str) -> None:
    env.setenv(key, value)
    with pytest.raises(ValidationError):
        Settings()


def test_a_missing_required_setting_is_rejected(env: pytest.MonkeyPatch) -> None:
    env.delenv("REPORTER_RUCIO_HOST")
    with pytest.raises(ValidationError):
        Settings()


def test_reads_each_project_secret_from_its_own_variable(env: pytest.MonkeyPatch) -> None:
    env.setenv("REPORTER_SECRET_ENES", "enes-secret")
    assert Settings().client_secret("RI-SCALE_ENES") == "enes-secret"


def test_a_missing_project_secret_is_a_config_error(env: pytest.MonkeyPatch) -> None:
    env.delenv("REPORTER_SECRET_ENES", raising=False)
    with pytest.raises(ConfigError, match="REPORTER_SECRET_ENES"):
        Settings().client_secret("RI-SCALE_ENES")


def test_secrets_are_not_shown_in_repr(env: pytest.MonkeyPatch) -> None:
    assert "rucio-pw" not in repr(Settings())
