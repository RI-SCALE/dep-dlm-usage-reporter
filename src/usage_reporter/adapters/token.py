"""OAuth2 client-credentials tokens for ARGO (and Rucio from step 6).

`ClientCredentials` fetches and caches one client's token; `TokenAuth` puts it
on every request of an httpx client and fetches a new one once on 401.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Generator

import httpx

EXPIRY_MARGIN_SECONDS = 60.0


class TokenError(RuntimeError):
    """The token endpoint did not issue a usable token."""


class ClientCredentials:
    """One client's access token, cached until shortly before it expires."""

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        scope: str | None = None,
        resource: str | None = None,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = token_url
        self._form = (
            {"grant_type": "client_credentials"}
            | ({"scope": scope} if scope else {})
            | ({"resource": resource} if resource else {})  # RFC 8707 audience
        )
        self._http = httpx.Client(
            auth=httpx.BasicAuth(client_id, client_secret),
            timeout=timeout_seconds,
            transport=transport,
        )
        self._clock = clock
        self._token: str | None = None
        self._valid_until = 0.0

    def token(self) -> str:
        if self._token is None or self._clock() >= self._valid_until:
            self._token, self._valid_until = self._fetch()
        return self._token

    def invalidate(self) -> None:
        self._token = None

    def close(self) -> None:
        self._http.close()

    def _fetch(self) -> tuple[str, float]:
        response = self._http.post(self._url, data=self._form)
        if response.is_error:
            raise TokenError(f"token endpoint returned {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise TokenError("token endpoint did not return JSON") from exc
        token = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise TokenError("token response has no access_token")
        expires_in = body.get("expires_in")
        if expires_in is None:  # lifetime unknown: keep it until a 401
            return token, float("inf")
        # A token shorter-lived than the margin is used for this request only.
        return token, self._clock() + float(expires_in) - EXPIRY_MARGIN_SECONDS


class TokenAuth(httpx.Auth):
    """Adds the token to each request; on 401 fetches a new one and retries once."""

    def __init__(
        self,
        credentials: ClientCredentials,
        header: str = "Authorization",
        scheme: str | None = "Bearer",
    ) -> None:
        self._credentials = credentials
        self._header = header
        self._scheme = scheme

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        self._apply(request)
        response = yield request
        if response.status_code == httpx.codes.UNAUTHORIZED:
            self._credentials.invalidate()
            self._apply(request)
            yield request

    def _apply(self, request: httpx.Request) -> None:
        token = self._credentials.token()
        request.headers[self._header] = f"{self._scheme} {token}" if self._scheme else token
