"""Rucio REST adapter against httpx.MockTransport (Design-001, "Testing").

Response shapes mirror rucio-server 41.2.1: NDJSON streams, RFC 1123 times,
the token in X-Rucio-Auth-Token, 404 for unknown accounts.
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
)
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
        self.tokens = 0
        self.expire_next = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path == "/auth/userpass":
            assert request.headers["X-Rucio-Username"] == "reporter"
            self.tokens += 1
            return httpx.Response(200, headers={"X-Rucio-Auth-Token": f"tok-{self.tokens}"})
        if self.expire_next:
            self.expire_next = False
            return httpx.Response(401)
        assert request.headers["X-Rucio-Auth-Token"].startswith("tok-")
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


def _client(fake: Callable[[httpx.Request], httpx.Response]) -> RucioClient:
    return RucioClient(
        host="https://rucio.example",
        account="reporter",
        username="reporter",
        password="secret",
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

    def test_refreshes_an_expired_token_once(self) -> None:
        fake = FakeRucio({})
        client = _client(fake)
        list(RucioRestSource(client).finished_transfers(START, END))
        fake.expire_next = True
        list(RucioRestSource(client).finished_transfers(START, END))
        assert fake.tokens == 2

    def test_server_error_raises(self) -> None:
        client = _client(
            lambda request: (
                httpx.Response(200, headers={"X-Rucio-Auth-Token": "tok-1"})
                if request.url.path == "/auth/userpass"
                else httpx.Response(503)
            )
        )
        with pytest.raises(RucioError, match="503"):
            list(RucioRestSource(client).finished_transfers(START, END))

    def test_failed_login_raises(self) -> None:
        client = _client(lambda request: httpx.Response(401))
        with pytest.raises(RucioError, match="401"):
            list(RucioRestSource(client).finished_transfers(START, END))


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
