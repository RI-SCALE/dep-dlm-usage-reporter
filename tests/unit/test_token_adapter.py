"""Client-credentials tokens and the httpx auth that applies them (Design-001, step 4).

One adapter serves ARGO (one client per accounting project, Authorization:
Bearer) and later Rucio (X-Rucio-Auth-Token, step 6).
"""

from __future__ import annotations

import base64
from urllib.parse import parse_qs

import httpx
import pytest

from usage_reporter.adapters.token import ClientCredentials, TokenAuth, TokenError

TOKEN_URL = "https://idp.example/realms/dep/protocol/openid-connect/token"


class FakeIdP:
    """Token endpoint issuing tok-1, tok-2, ... and recording each request."""

    def __init__(self, expires_in: int | None = 3600, status: int = 200) -> None:
        self.expires_in = expires_in
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "invalid_client"})
        body: dict[str, object] = {
            "access_token": f"tok-{len(self.requests)}",
            "token_type": "Bearer",
        }
        if self.expires_in is not None:
            body["expires_in"] = self.expires_in
        return httpx.Response(200, json=body)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _credentials(idp: FakeIdP, clock: Clock | None = None, **kwargs: object) -> ClientCredentials:
    return ClientCredentials(
        TOKEN_URL,
        "usage-reporter-enes",
        "s3cret",
        transport=httpx.MockTransport(idp),
        clock=clock or Clock(),
        **kwargs,  # type: ignore[arg-type]
    )


class TestClientCredentials:
    def test_requests_a_token_with_the_client_credentials_grant(self) -> None:
        idp = FakeIdP()
        assert _credentials(idp, scope="accounting").token() == "tok-1"

        request = idp.requests[0]
        assert request.method == "POST"
        assert str(request.url) == TOKEN_URL
        form = parse_qs(request.content.decode())
        assert form == {"grant_type": ["client_credentials"], "scope": ["accounting"]}
        basic = base64.b64encode(b"usage-reporter-enes:s3cret").decode()
        assert request.headers["Authorization"] == f"Basic {basic}"

    def test_omits_scope_when_not_configured(self) -> None:
        idp = FakeIdP()
        _credentials(idp).token()
        assert parse_qs(idp.requests[0].content.decode()) == {"grant_type": ["client_credentials"]}

    def test_reuses_the_token_until_shortly_before_expiry(self) -> None:
        idp, clock = FakeIdP(expires_in=3600), Clock()
        credentials = _credentials(idp, clock)
        assert credentials.token() == "tok-1"
        clock.now += 3600 - 61
        assert credentials.token() == "tok-1"
        clock.now += 1  # inside the 60 s margin
        assert credentials.token() == "tok-2"

    def test_a_token_shorter_than_the_margin_is_used_once(self) -> None:
        idp = FakeIdP(expires_in=30)
        credentials = _credentials(idp)
        assert credentials.token() == "tok-1"
        assert credentials.token() == "tok-2"

    def test_without_expires_in_the_token_is_kept_until_invalidated(self) -> None:
        idp, clock = FakeIdP(expires_in=None), Clock()
        credentials = _credentials(idp, clock)
        credentials.token()
        clock.now += 86_400
        assert credentials.token() == "tok-1"
        credentials.invalidate()
        assert credentials.token() == "tok-2"

    @pytest.mark.parametrize("status", [400, 401, 500, 503])
    def test_an_error_response_raises_without_leaking_the_secret(self, status: int) -> None:
        with pytest.raises(TokenError, match=str(status)) as caught:
            _credentials(FakeIdP(status=status)).token()
        assert "s3cret" not in str(caught.value)

    def test_a_response_without_access_token_raises(self) -> None:
        body = {"token_type": "Bearer"}
        idp = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
        credentials = ClientCredentials(TOKEN_URL, "c", "s", transport=idp)
        with pytest.raises(TokenError, match="access_token"):
            credentials.token()

    def test_a_non_json_response_raises(self) -> None:
        idp = httpx.MockTransport(lambda request: httpx.Response(200, text="<html>"))
        credentials = ClientCredentials(TOKEN_URL, "c", "s", transport=idp)
        with pytest.raises(TokenError, match="JSON"):
            credentials.token()


class Api:
    """Protected API that answers 401 for tokens listed in `rejected`."""

    def __init__(self, header: str = "Authorization", rejected: set[str] | None = None) -> None:
        self.header = header
        self.rejected = rejected or set()
        self.seen: list[str] = []
        self.bodies: list[bytes] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        value = request.headers.get(self.header, "")
        self.seen.append(value)
        self.bodies.append(request.content)
        token = value.removeprefix("Bearer ")
        return httpx.Response(401 if token in self.rejected else 200)


def _api_client(api: Api, auth: TokenAuth) -> httpx.Client:
    transport = httpx.MockTransport(api)
    return httpx.Client(base_url="https://api.example", transport=transport, auth=auth)


class TestTokenAuth:
    def test_sends_a_bearer_token(self) -> None:
        api = Api()
        with _api_client(api, TokenAuth(_credentials(FakeIdP()))) as client:
            assert client.get("/metrics").status_code == 200
        assert api.seen == ["Bearer tok-1"]

    def test_refreshes_once_on_401_and_repeats_the_request_with_its_body(self) -> None:
        api = Api(rejected={"tok-1"})
        with _api_client(api, TokenAuth(_credentials(FakeIdP()))) as client:
            assert client.post("/metrics", json={"value": 151}).status_code == 200
        assert api.seen == ["Bearer tok-1", "Bearer tok-2"]
        assert api.bodies[0] == api.bodies[1] == b'{"value":151}'

    def test_a_second_401_is_returned_to_the_caller(self) -> None:
        api = Api(rejected={"tok-1", "tok-2", "tok-3"})
        with _api_client(api, TokenAuth(_credentials(FakeIdP()))) as client:
            assert client.get("/metrics").status_code == 401
        assert len(api.seen) == 2

    def test_403_is_not_retried(self) -> None:
        idp = FakeIdP()
        client = httpx.Client(
            base_url="https://api.example",
            transport=httpx.MockTransport(lambda request: httpx.Response(403)),
            auth=TokenAuth(_credentials(idp)),
        )
        assert client.get("/metrics").status_code == 403
        assert len(idp.requests) == 1

    def test_raw_token_in_a_custom_header_for_rucio(self) -> None:
        api = Api(header="X-Rucio-Auth-Token")
        auth = TokenAuth(_credentials(FakeIdP()), header="X-Rucio-Auth-Token", scheme=None)
        with _api_client(api, auth) as client:
            client.get("/rses/")
        assert api.seen == ["tok-1"]
