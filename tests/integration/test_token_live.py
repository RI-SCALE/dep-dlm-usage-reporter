"""Token adapter against the compose Keycloak (Design-001, steps 4 and 6).

Keycloak stands in for the IdPs behind ARGO's and Rucio's client credentials;
the realm (docker/realm.json) has one confidential client per accounting
project and one for the reporter's Rucio account.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator

import pytest

from usage_reporter.adapters.token import ClientCredentials, TokenError

pytestmark = pytest.mark.integration

CLIENT_ID = "usage-reporter-enes"
RUCIO_CLIENT_ID = "usage-reporter-rucio"


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


@pytest.fixture
def rucio_credentials(keycloak_url: str) -> Iterator[ClientCredentials]:
    credentials = ClientCredentials(
        _token_url(keycloak_url), RUCIO_CLIENT_ID, "rucio-reporter-secret"
    )
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


def test_the_rucio_client_token_carries_what_rucio_checks(
    rucio_credentials: ClientCredentials,
) -> None:
    # rucio.cfg [oidc]: rucio in aud, pep:rucio in scope; rucio-seed.py maps
    # this sub and iss to the reporter account.
    claims = _claims(rucio_credentials.token())
    aud = claims["aud"]
    assert "rucio" in (aud if isinstance(aud, list) else [aud])
    assert "pep:rucio" in str(claims["scope"]).split()
    assert claims["sub"] == "4b7d6f0e-2a51-4c8e-9a3f-1e5d7c9b2a60"
    assert claims["iss"] == "http://keycloak:8080/realms/dep"


def test_a_wrong_secret_is_rejected(keycloak_url: str) -> None:
    credentials = ClientCredentials(_token_url(keycloak_url), CLIENT_ID, "wrong")
    with pytest.raises(TokenError, match="401"):
        credentials.token()
