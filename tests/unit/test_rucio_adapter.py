"""Rucio REST adapter against httpx.MockTransport (Design-001, "Testing").

Response shapes mirror rucio-server 41.2.1: NDJSON streams, RFC 1123 times,
404 for unknown accounts. Authentication is an OIDC client-credentials token
in X-Rucio-Auth-Token (Design-001, step 6), fetched from a fake IdP through
the real token adapter.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from usage_reporter.adapters.rucio import (
    RucioAttributeMapping,
    RucioClient,
    RucioError,
    RucioRestSource,
    rucio_token_auth,
)
from usage_reporter.adapters.token import ClientCredentials, TokenError
from usage_reporter.core.model import Group, Transfer

START = datetime(2026, 11, 22, tzinfo=UTC)
END = datetime(2026, 11, 23, tzinfo=UTC)
KNOWN = frozenset({"RI-SCALE_ENES"})


def _ndjson(rows: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(200, text="".join(json.dumps(r) + "\n" for r in rows))


def _row(rid: str, account: str, nbytes: int | None, at: str | None) -> dict[str, object]:
    return {"id": rid, "account": account, "bytes": nbytes, "transferred_at": at, "state": "DONE"}


class FakeRucio:
    """Routes requests like rucio-server and records what was asked."""

    def __init__(self, history: dict[tuple[str, str], list[dict[str, object]]]) -> None:
        self.history = history
        self.rses = sorted({rse for pair in history for rse in pair} | {"CERN_DATADISK"})
        self.attributes: dict[str, list[dict[str, object]]] = {}
        self.calls: list[httpx.Request] = []
        self.rejected: set[str] = set()  # tokens answered with 401

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        token = request.headers.get("X-Rucio-Auth-Token", "")
        assert "X-Rucio-Username" not in request.headers  # no userpass any more
        if not token.startswith("jwt-") or token in self.rejected:
            return httpx.Response(401)
        # Like rucio-server: streams need NDJSON, the attribute list needs JSON.
        wants = "application/json" if path.endswith("/attr/") else "application/x-json-stream"
        if request.headers.get("Accept") != wants:
            return httpx.Response(406)
        if path == "/rses/":
            return _ndjson([{"rse": r} for r in self.rses])
        if path == "/requests/history/list":
            p = request.url.params
            assert p["request_states"] == "D"
            rows = self.history.get((p["src_rse"], p["dst_rse"]), [])
            offset, limit = int(p["offset"]), int(p["limit"])
            return _ndjson(rows[offset : offset + limit])
        if path.startswith("/accounts/") and path.endswith("/attr/"):
            account = path.split("/")[2]
            if account not in self.attributes:
                return httpx.Response(404, json={"ExceptionClass": "AccountNotFound"})
            return httpx.Response(200, json=self.attributes[account])
        return httpx.Response(500)


class FakeIdP:
    """Client-credentials token endpoint issuing jwt-1, jwt-2, ..."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.issued = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert b"grant_type=client_credentials" in request.content
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "invalid_client"})
        self.issued += 1
        return httpx.Response(200, json={"access_token": f"jwt-{self.issued}", "expires_in": 3600})


def _client(
    fake: Callable[[httpx.Request], httpx.Response], idp: FakeIdP | None = None
) -> RucioClient:
    credentials = ClientCredentials(
        "https://idp.example/token",
        "usage-reporter-rucio",
        "s3cret",
        transport=httpx.MockTransport(idp or FakeIdP()),
    )
    return RucioClient(
        host="https://rucio.example",
        auth=rucio_token_auth(credentials),
        transport=httpx.MockTransport(fake),
    )


class TestRucioRestSource:
    def test_parses_rfc1123_times_and_keeps_rows_in_window(self) -> None:
        fake = FakeRucio(
            {
                ("CERN_DATADISK", "TUBITAK_DATADISK"): [
                    _row("r1", "suc1-prod", 100, "Sun, 22 Nov 2026 09:00:00 UTC"),
                    _row("r2", "suc1-prod", 5, "Sat, 21 Nov 2026 23:59:59 UTC"),
                    _row("r3", "suc1-prod", 9, "Mon, 23 Nov 2026 00:00:00 UTC"),
                ]
            }
        )
        transfers = list(RucioRestSource(_client(fake)).finished_transfers(START, END))
        assert transfers == [
            Transfer("r1", "suc1-prod", 100, datetime(2026, 11, 22, 9, tzinfo=UTC))
        ]

    def test_null_time_or_bytes_is_passed_on_for_the_core_to_skip(self) -> None:
        fake = FakeRucio(
            {
                ("CERN_DATADISK", "TUBITAK_DATADISK"): [
                    _row("r1", "a", None, "Sun, 22 Nov 2026 09:00:00 UTC"),
                    _row("r2", "a", 7, None),
                ]
            }
        )
        transfers = list(RucioRestSource(_client(fake)).finished_transfers(START, END))
        assert [(t.request_id, t.bytes, t.transferred_at) for t in transfers] == [
            ("r1", None, datetime(2026, 11, 22, 9, tzinfo=UTC)),
            ("r2", 7, None),
        ]

    def test_pages_until_a_short_page_including_an_exactly_full_last_page(self) -> None:
        rows = [_row(f"r{i}", "a", 1, "Sun, 22 Nov 2026 09:00:00 UTC") for i in range(4)]
        fake = FakeRucio({("CERN_DATADISK", "TUBITAK_DATADISK"): rows})
        source = RucioRestSource(_client(fake), page_size=2)
        assert len(list(source.finished_transfers(START, END))) == 4
        offsets = [
            c.url.params["offset"]
            for c in fake.calls
            if c.url.path == "/requests/history/list"
            and c.url.params["src_rse"] == "CERN_DATADISK"
            and c.url.params["dst_rse"] == "TUBITAK_DATADISK"
        ]
        assert offsets == ["0", "2", "4"]

    def test_asks_every_ordered_pair_of_distinct_rses(self) -> None:
        fake = FakeRucio({("A", "B"): [], ("B", "C"): []})
        list(RucioRestSource(_client(fake)).finished_transfers(START, END))
        pairs = {
            (c.url.params["src_rse"], c.url.params["dst_rse"])
            for c in fake.calls
            if c.url.path == "/requests/history/list"
        }
        rses = fake.rses
        assert pairs == {(s, d) for s in rses for d in rses if s != d}

    def test_sends_the_raw_token_and_fetches_it_once(self) -> None:
        fake, idp = FakeRucio({("A", "B"): []}), FakeIdP()
        list(RucioRestSource(_client(fake, idp)).finished_transfers(START, END))
        assert {c.headers["X-Rucio-Auth-Token"] for c in fake.calls} == {"jwt-1"}
        assert idp.issued == 1

    def test_refreshes_a_rejected_token_once(self) -> None:
        fake, idp = FakeRucio({}), FakeIdP()
        fake.rejected.add("jwt-1")
        list(RucioRestSource(_client(fake, idp)).finished_transfers(START, END))
        assert idp.issued == 2

    def test_a_token_rucio_never_accepts_raises(self) -> None:
        fake = FakeRucio({})
        fake.rejected.update({"jwt-1", "jwt-2"})
        with pytest.raises(RucioError, match="401"):
            list(RucioRestSource(_client(fake)).finished_transfers(START, END))

    def test_a_failing_token_endpoint_raises(self) -> None:
        with pytest.raises(TokenError, match="401"):
            list(
                RucioRestSource(_client(FakeRucio({}), FakeIdP(401))).finished_transfers(START, END)
            )

    def test_server_error_raises(self) -> None:
        with pytest.raises(RucioError, match="503"):
            list(
                RucioRestSource(_client(lambda request: httpx.Response(503))).finished_transfers(
                    START, END
                )
            )


class TestRucioAttributeMapping:
    def _mapping(self, fake: FakeRucio) -> RucioAttributeMapping:
        return RucioAttributeMapping(_client(fake), known_projects=KNOWN)

    def test_maps_from_account_attributes(self) -> None:
        fake = FakeRucio({})
        fake.attributes["suc1-prod"] = [
            {"key": "project_id", "value": "RI-SCALE_ENES"},
            {"key": "group_id", "value": "suc1"},
            {"key": "admin", "value": False},
        ]
        assert self._mapping(fake).resolve("suc1-prod") == Group("RI-SCALE_ENES", "suc1")

    def test_unknown_or_unattributed_account_is_unmapped(self) -> None:
        fake = FakeRucio({})
        fake.attributes["plain"] = []
        mapping = self._mapping(fake)
        assert mapping.resolve("plain") is None
        assert mapping.resolve("deleted-account") is None

    def test_looks_each_account_up_once_per_run(self) -> None:
        fake = FakeRucio({})
        fake.attributes["suc1-prod"] = [
            {"key": "project_id", "value": "RI-SCALE_ENES"},
            {"key": "group_id", "value": "suc1"},
        ]
        mapping = self._mapping(fake)
        mapping.resolve("suc1-prod")
        mapping.resolve("suc1-prod")
        attr_calls = [c for c in fake.calls if c.url.path.endswith("/attr/")]
        assert len(attr_calls) == 1
