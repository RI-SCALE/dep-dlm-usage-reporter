"""Token adapter against the compose Keycloak (Design-001, step 4).

Keycloak stands in for the IdP behind ARGO's client credentials; the realm
(docker/realm.json) has one confidential client per accounting project.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator

import pytest

from usage_reporter.adapters.token import ClientCredentials, TokenError

pytestmark = pytest.mark.integration

CLIENT_ID = "usage-reporter-enes"


def _token_url(keycloak_url: str) -> str:
    return f"{keycloak_url}/realms/dep/protocol/openid-connect/token"


def _claims(jwt: str) -> dict[str, object]:
    payload = jwt.split(".")[1]
    decoded: dict[str, object] = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    return decoded


@pytest.fixture
def credentials(keycloak_url: str) -> Iterator[ClientCredentials]:
    credentials = ClientCredentials(_token_url(keycloak_url), CLIENT_ID, "enes-secret")
    yield credentials
    credentials.close()


def test_keycloak_issues_a_cached_client_credentials_token(
    credentials: ClientCredentials,
) -> None:
    token = credentials.token()
    assert credentials.token() == token  # cached, valid for an hour
    claims = _claims(token)
    assert claims["azp"] == CLIENT_ID
    assert str(claims["iss"]).endswith("/realms/dep")


def test_a_wrong_secret_is_rejected(keycloak_url: str) -> None:
    credentials = ClientCredentials(_token_url(keycloak_url), CLIENT_ID, "wrong")
    with pytest.raises(TokenError, match="401"):
        credentials.token()
