"""Rucio REST adapter: finished transfers and account attributes (Design-009).

Talks to rucio-server directly with httpx. Response shapes as served by
rucio-server 41.2.1: NDJSON streams, RFC 1123 timestamps
("Sun, 22 Nov 2026 09:00:00 UTC"). Authentication: an OIDC client-credentials
token in X-Rucio-Auth-Token (Design-001, step 6).
"""

from __future__ import annotations

import json
from collections.abc import Collection, Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from itertools import permutations
from typing import Any
from urllib.parse import quote

import httpx

from usage_reporter.adapters.token import ClientCredentials, TokenAuth
from usage_reporter.core.mapping import group_from_attributes
from usage_reporter.core.model import Group, Transfer
from usage_reporter.core.ports import GroupMapping, TransferSource

NDJSON = "application/x-json-stream"
JSON = "application/json"
DONE = "D"


class RucioError(RuntimeError):
    """Rucio answered with an error the adapter cannot handle."""


def rucio_token_auth(credentials: ClientCredentials) -> TokenAuth:
    """Rucio takes the raw JWT in X-Rucio-Auth-Token, not Authorization: Bearer."""
    return TokenAuth(credentials, header="X-Rucio-Auth-Token", scheme=None)


class RucioClient:
    """GETs against rucio-server with an OIDC token (refreshed once on 401 by `auth`).

    Rucio validates the JWT itself (issuer from idpsecrets.json, audience,
    scope) and maps `SUB=..., ISS=...` to the reporter's account.
    """

    def __init__(
        self,
        host: str,
        auth: httpx.Auth,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=host, auth=auth, timeout=timeout_seconds, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    def get(
        self, path: str, params: dict[str, Any] | None = None, accept: str = JSON
    ) -> httpx.Response | None:
        """GET a path; None for 404, RucioError for other failures."""
        response = self._http.get(path, params=params, headers={"Accept": accept})
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        if response.is_error:
            raise RucioError(f"GET {path} returned {response.status_code}")
        return response

    def ndjson(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        response = self.get(path, params, accept=NDJSON)
        if response is None:
            return []
        return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def parse_rucio_time(value: str | None) -> datetime | None:
    """RFC 1123 as rucio-server renders it; ISO 8601 accepted too. Always UTC."""
    if not value:
        return None
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        moment = datetime.fromisoformat(value)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


class RucioRestSource(TransferSource):
    """TransferSource over GET /requests/history/list.

    The endpoint has no time filter and takes one source/destination pair per
    call, so every ordered RSE pair is paged and rows are filtered here.
    """

    def __init__(self, client: RucioClient, page_size: int = 1000) -> None:
        self._client = client
        self._page_size = page_size

    def finished_transfers(self, start: datetime, end: datetime) -> Iterator[Transfer]:
        rses = [row["rse"] for row in self._client.ndjson("/rses/")]
        for src, dst in permutations(rses, 2):
            for row in self._history(src, dst):
                transfer = Transfer(
                    request_id=str(row["id"]),
                    account=str(row.get("account") or ""),
                    bytes=row.get("bytes"),
                    transferred_at=parse_rucio_time(row.get("transferred_at")),
                )
                at = transfer.transferred_at
                if at is None or start <= at < end:
                    yield transfer

    def _history(self, src: str, dst: str) -> Iterator[dict[str, Any]]:
        offset = 0
        while True:
            params = {
                "src_rse": src,
                "dst_rse": dst,
                "request_states": DONE,
                "offset": offset,
                "limit": self._page_size,
            }
            page = self._client.ndjson("/requests/history/list", params)
            yield from page
            if len(page) < self._page_size:
                return
            offset += self._page_size


class RucioAttributeMapping(GroupMapping):
    """GroupMapping over GET /accounts/{account}/attr/, one lookup per account."""

    def __init__(self, client: RucioClient, known_projects: Collection[str]) -> None:
        self._client = client
        self._known = known_projects
        self._cache: dict[str, Group | None] = {}

    def resolve(self, account: str) -> Group | None:
        if account not in self._cache:
            response = self._client.get(f"/accounts/{quote(account, safe='')}/attr/")
            rows = [] if response is None else response.json()
            attributes = {str(r["key"]): str(r["value"]) for r in rows}
            self._cache[account] = group_from_attributes(attributes, self._known)
        return self._cache[account]
