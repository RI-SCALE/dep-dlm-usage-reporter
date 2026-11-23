"""ARGO Accounting adapter against httpx.MockTransport (Design-001, step 4).

Shapes follow ARGO devel's OpenAPI (3.1.0): the installation's metrics are
listed with `metric-definition-id`, `start`, `end`, `page` and `size`, and
returned as `content[]` with `total_pages`; POST returns `metric_id`. Each
day is reported once: an existing metric is left as is, never patched.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest

from usage_reporter.adapters.argo import (
    AmbiguousMetricError,
    ArgoError,
    ArgoProject,
    ArgoSink,
    ArgoUnavailableError,
)
from usage_reporter.core.model import ReportOutcome, UsageRecord
from usage_reporter.core.report import RecordError

INSTALLATION = "6afaff4e947efcc6dea636e2"
DEFINITION = "6afc3e7801adaea4c9c12777"
RECORD = UsageRecord(date(2026, 11, 22), "RI-SCALE_ENES", "suc1", 151)
METRICS = f"/accounting-system/installations/{INSTALLATION}/metrics"


def _stored(metric_id: str, group_id: str = "suc1", **overrides: Any) -> dict[str, Any]:
    return {
        "id": metric_id,
        "installation_id": INSTALLATION,
        "metric_definition_id": DEFINITION,
        "time_period_start": "2026-11-22T00:00:00Z",
        "time_period_end": "2026-11-22T23:59:59Z",
        "value": 100.0,
        "group_id": group_id,
        **overrides,
    }


class FakeArgo:
    """List (paged) and POST; records each request with its params and body.

    Like ARGO, the list is filtered by definition and dates but not by group,
    and returns every stored metric here, so the adapter must check results.
    """

    def __init__(self, stored: list[dict[str, Any]] | None = None, page_size: int = 100) -> None:
        self.stored = stored or []
        self.page_size = page_size
        self.calls: list[tuple[str, str, Any]] = []
        self.params: list[dict[str, str]] = []
        self.fail_post_with: Exception | None = None
        self.status: dict[str, int] = {}  # method (get, post) -> status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: Any = json.loads(request.content) if request.content else {}
        method, path = request.method, request.url.path
        self.calls.append((method, path, body))
        assert request.headers["Authorization"] == "Bearer enes-token"
        if status := self.status.get(method.lower()):
            return httpx.Response(status, json={"code": status, "message": "nope"})
        if method == "GET" and path == METRICS:
            params = dict(request.url.params)
            self.params.append(params)
            page, size = int(params["page"]), int(params["size"])
            pages = max(1, -(-len(self.stored) // self.page_size))
            content = self.stored[(page - 1) * self.page_size : page * self.page_size]
            assert size == 100
            return httpx.Response(
                200,
                json={
                    "size_of_page": len(content),
                    "number_of_page": page,
                    "total_elements": len(self.stored),
                    "total_pages": pages,
                    "content": content,
                },
            )
        if method == "POST" and path == METRICS:
            if self.fail_post_with:
                error, self.fail_post_with = self.fail_post_with, None
                self.stored.append(_stored("m-new", value=body["value"]))  # landed anyway
                raise error
            self.stored.append(_stored("m-new", value=body["value"]))
            return httpx.Response(201, json={"metric_id": "m-new", **body})
        return httpx.Response(405)  # anything else, PATCH included, is a bug

    def methods(self) -> list[str]:
        return [f"{m} {p.removeprefix(METRICS) or '/'}" for m, p, _ in self.calls]


class StaticToken(httpx.Auth):
    def auth_flow(self, request: httpx.Request):  # type: ignore[no-untyped-def]
        request.headers["Authorization"] = "Bearer enes-token"
        yield request


def _sink(fake: Callable[[httpx.Request], httpx.Response]) -> ArgoSink:
    return ArgoSink(
        "https://api.devel.acc.argo.grnet.gr",
        DEFINITION,
        {"RI-SCALE_ENES": ArgoProject(INSTALLATION, StaticToken())},
        transport=httpx.MockTransport(fake),
    )


class TestReport:
    def test_posts_a_new_metric_for_the_whole_utc_day(self) -> None:
        fake = FakeArgo()
        assert _sink(fake).report(RECORD) is ReportOutcome.CREATED
        assert fake.methods() == ["GET /", "POST /"]
        assert fake.calls[1][2] == {
            "metric_definition_id": DEFINITION,
            "time_period_start": "2026-11-22T00:00:00Z",
            "time_period_end": "2026-11-22T23:59:59Z",
            "value": 151,
            "group_id": "suc1",
        }

    def test_lists_the_installation_by_definition_and_day(self) -> None:
        fake = FakeArgo()
        _sink(fake).report(RECORD)
        assert fake.params == [
            {
                "metric-definition-id": DEFINITION,
                "start": "2026-11-22",
                "end": "2026-11-22",
                "page": "1",
                "size": "100",
            }
        ]

    def test_reads_every_page_before_deciding(self) -> None:
        others = [_stored(f"o-{i}", group_id="suc2") for i in range(3)]
        fake = FakeArgo([*others, _stored("m-1")], page_size=2)
        assert _sink(fake).report(RECORD) is ReportOutcome.EXISTS
        assert [p["page"] for p in fake.params] == ["1", "2"]

    def test_leaves_an_existing_metric_as_is(self) -> None:
        # Reported once: patching would change credit balances after the fact.
        fake = FakeArgo([_stored("m-1", value=100.0)])
        assert _sink(fake).report(RECORD) is ReportOutcome.EXISTS
        assert fake.methods() == ["GET /"]
        assert fake.stored[0]["value"] == 100.0

    def test_accepts_metric_id_as_the_key_in_results(self) -> None:
        stored = _stored("m-1")
        stored["metric_id"] = stored.pop("id")
        fake = FakeArgo([stored, _stored("m-2") | {"id": None, "metric_id": "m-2"}])
        with pytest.raises(AmbiguousMetricError, match="m-1, m-2"):
            _sink(fake).report(RECORD)

    def test_reads_the_definition_from_a_nested_object(self) -> None:
        stored = _stored("m-1")
        del stored["metric_definition_id"]
        stored["metric_definition"] = {"id": DEFINITION, "metric_name": "bytes"}
        other = _stored("m-2") | {"metric_definition": {"id": "elsewhere"}}
        del other["metric_definition_id"]
        fake = FakeArgo([stored, other])
        assert _sink(fake).report(RECORD) is ReportOutcome.EXISTS

    def test_keeps_only_results_for_this_record(self) -> None:
        fake = FakeArgo(
            [
                _stored("other-group", group_id="suc2"),
                _stored("other-day", time_period_start="2026-11-21T00:00:00Z"),
                _stored("other-installation", installation_id="elsewhere"),
                _stored("other-definition", metric_definition_id="elsewhere"),
            ]
        )
        assert _sink(fake).report(RECORD) is ReportOutcome.CREATED

    def test_matches_the_day_whatever_its_timestamp_precision(self) -> None:
        fake = FakeArgo([_stored("m-1", time_period_start="2026-11-22T00:00:00.000Z")])
        assert _sink(fake).report(RECORD) is ReportOutcome.EXISTS

    def test_several_matches_write_nothing(self) -> None:
        fake = FakeArgo([_stored("m-1"), _stored("m-2")])
        with pytest.raises(AmbiguousMetricError, match="m-1, m-2"):
            _sink(fake).report(RECORD)
        assert fake.methods() == ["GET /"]

    def test_a_result_without_group_id_counts_as_a_match(self) -> None:
        # Safety net: if a result lacks group_id, use cases look alike and the
        # record fails rather than overwriting another one.
        no_group = _stored("m-1")
        del no_group["group_id"]
        fake = FakeArgo([no_group, _stored("m-2", group_id="suc2") | {"group_id": None}])
        with pytest.raises(AmbiguousMetricError):
            _sink(fake).report(RECORD)


class TestPostTimeout:
    def test_looks_up_again_instead_of_posting_twice(self) -> None:
        fake = FakeArgo()
        fake.fail_post_with = httpx.ReadTimeout("slow")
        assert _sink(fake).report(RECORD) is ReportOutcome.CREATED
        assert fake.methods() == ["GET /", "POST /", "GET /"]

    def test_posts_once_more_if_the_timed_out_post_did_not_land(self) -> None:
        fake = FakeArgo()

        def dropping(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == METRICS and not fake.calls[2:]:
                fake.calls.append((request.method, request.url.path, None))
                raise httpx.ReadTimeout("slow")
            return fake(request)

        assert _sink(dropping).report(RECORD) is ReportOutcome.CREATED
        assert fake.methods() == ["GET /", "POST /", "GET /", "POST /"]

    def test_a_connect_timeout_is_not_ambiguous_and_propagates(self) -> None:
        def refusing(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("down")

        with pytest.raises(httpx.ConnectTimeout):
            _sink(refusing).report(RECORD)


class TestErrors:
    @pytest.mark.parametrize("operation", ["get", "post"])
    def test_a_rejected_record_fails_only_that_record(self, operation: str) -> None:
        fake = FakeArgo()
        fake.status[operation] = 400
        with pytest.raises(ArgoError, match="400") as caught:
            _sink(fake).report(RECORD)
        assert isinstance(caught.value, RecordError)

    @pytest.mark.parametrize("status", [401, 403, 500, 503])
    def test_server_or_auth_errors_abort_the_run(self, status: int) -> None:
        fake = FakeArgo()
        fake.status["get"] = status
        with pytest.raises(ArgoUnavailableError, match=str(status)) as caught:
            _sink(fake).report(RECORD)
        assert not isinstance(caught.value, RecordError)

    def test_unconfigured_project_raises_before_any_call(self) -> None:
        fake = FakeArgo()
        with pytest.raises(ArgoError, match="RI-SCALE_BBMRI"):
            _sink(fake).report(UsageRecord(date(2026, 11, 22), "RI-SCALE_BBMRI", "suc5", 1))
        assert fake.calls == []
