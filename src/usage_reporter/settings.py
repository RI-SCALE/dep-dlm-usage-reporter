"""REPORTER_* configuration, validated at startup (Design-001, "Configuration").

Secrets come from environment variables only: the Rucio client secret, and
one ARGO client secret per project in the variable its `client_secret_env`
names.
"""

from __future__ import annotations

import os
from datetime import date

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(ValueError):
    """Configuration is incomplete; the job sends nothing (exit 1)."""


class ProjectSettings(BaseModel):
    installation_id: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret_env: str = Field(min_length=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REPORTER_", frozen=True)

    rucio_host: str
    rucio_token_url: str  # OIDC client credentials (Design-001, step 6)
    rucio_client_id: str
    rucio_client_secret: SecretStr
    rucio_scope: str | None = None

    argo_endpoint: str = "https://api.devel.acc.argo.grnet.gr"
    argo_metric_definition_id: str
    argo_token_url: str
    argo_scope: str | None = None
    projects: dict[str, ProjectSettings] = Field(min_length=1)

    lookback_days: int = Field(default=0, ge=0)
    day: date | None = None  # explicit day, for re-runs and backfills
    dry_run: bool = True
    timeout_seconds: float = Field(default=10.0, gt=0)

    def client_secret(self, project_id: str) -> str:
        name = self.projects[project_id].client_secret_env
        secret = os.environ.get(name)
        if not secret:
            raise ConfigError(f"{name} is not set (client secret for {project_id})")
        return secret
