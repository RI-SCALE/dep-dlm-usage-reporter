"""ARGO Accounting adapter against httpx.MockTransport (Design-001, step 4).

Shapes follow the ARGO docs and OpenAPI 1.0.0: POST returns `metric_id`,
search returns `content[].id`. `group_id` is documented as optional on
metrics but missing from the spec, so it is sent only when set.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest

from usage_reporter.adapters.argo import AmbiguousMetricError, ArgoError, ArgoProject, ArgoSink
from usage_reporter.core.model import UpsertOutcome, UsageRecord

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
    """Search, POST and PATCH, recording each request and its JSON body."""

    def __init__(self, stored: list[dict[str, Any]] | None = None) -> None:
        self.stored = stored or []
        self.calls: list[tuple[str, str, Any]] = []
        self.fail_post_with: Exception | None = None
        self.status: dict[str, int] = {}  # operation (search, post, patch) -> status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: Any = json.loads(request.content) if request.content else {}
        method, path = request.method, request.url.path
        self.calls.append((method, path, body))
        assert request.headers["Authorization"] == "Bearer enes-token"
        operation = "search" if path.endswith("/search") else method.lower()
        if status := self.status.get(operation):
            return httpx.Response(status, json={"code": status, "message": "nope"})
        if operation == "search":
            return httpx.Response(
                200, json={"total_elements": len(self.stored), "content": self.stored}
            )
        if method == "POST" and path == METRICS:
            if self.fail_post_with:
                error, self.fail_post_with = self.fail_post_with, None
                self.stored.append(_stored("m-new", value=body["value"]))  # landed anyway
                raise error
            self.stored.append(_stored("m-new", value=body["value"]))
            return httpx.Response(201, json={"metric_id": "m-new", **body})
        if method == "PATCH" and path.startswith(f"{METRICS}/"):
            return httpx.Response(200, json={"metric_id": path.rsplit("/", 1)[1], **body})
        return httpx.Response(404)

    def methods(self) -> list[str]:
        return [
            f"{m} {'search' if p.endswith('/search') else p.removeprefix(METRICS) or '/'}"
            for m, p, _ in self.calls
        ]


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


class TestUpsert:
    def test_posts_a_new_metric_for_the_whole_utc_day(self) -> None:
        fake = FakeArgo()
        assert _sink(fake).upsert(RECORD) is UpsertOutcome.CREATED
        assert fake.methods() == ["POST search", "POST /"]
        assert fake.calls[1][2] == {
            "metric_definition_id": DEFINITION,
            "time_period_start": "2026-11-22T00:00:00Z",
            "time_period_end": "2026-11-22T23:59:59Z",
            "value": 151,
            "group_id": "suc1",
        }

    def test_searches_by_installation_definition_day_and_group(self) -> None:
        fake = FakeArgo()
        _sink(fake).upsert(RECORD)
        assert fake.calls[0][2] == {
            "type": "filter",
            "operator": "AND",
            "criteria": [
                {
                    "type": "query",
                    "field": "installation_id",
                    "values": INSTALLATION,
                    "operand": "eq",
                },
                {
                    "type": "query",
                    "field": "metric_definition_id",
                    "values": DEFINITION,
                    "operand": "eq",
                },
                {
                    "type": "query",
                    "field": "time_period_start",
                    "values": "2026-11-22T00:00:00Z",
                    "operand": "eq",
                },
                {"type": "query", "field": "group_id", "values": "suc1", "operand": "eq"},
            ],
        }

    def test_patches_the_value_of_an_existing_metric(self) -> None:
        fake = FakeArgo([_stored("m-1")])
        assert _sink(fake).upsert(RECORD) is UpsertOutcome.UPDATED
        assert fake.methods() == ["POST search", "PATCH /m-1"]
        assert fake.calls[1][2] == {"value": 151}

    def test_accepts_metric_id_as_the_key_in_search_results(self) -> None:
        stored = _stored("ignored")
        stored["metric_id"] = stored.pop("id")
        fake = FakeArgo([stored])
        _sink(fake).upsert(RECORD)
        assert fake.methods()[-1] == "PATCH /ignored"

    def test_ignores_results_the_search_should_not_have_returned(self) -> None:
        fake = FakeArgo(
            [
                _stored("other-group", group_id="suc2"),
                _stored("other-day", time_period_start="2026-11-21T00:00:00Z"),
                _stored("other-installation", installation_id="elsewhere"),
                _stored("other-definition", metric_definition_id="elsewhere"),
                _stored("m-1", time_period_start="2026-11-22T00:00:00.000Z"),
            ]
        )
        assert _sink(fake).upsert(RECORD) is UpsertOutcome.UPDATED
        assert fake.methods()[-1] == "PATCH /m-1"

    def test_several_matches_write_nothing(self) -> None:
        fake = FakeArgo([_stored("m-1"), _stored("m-2")])
        with pytest.raises(AmbiguousMetricError, match="m-1, m-2"):
            _sink(fake).upsert(RECORD)
        assert fake.methods() == ["POST search"]

    def test_a_result_without_group_id_counts_as_a_match(self) -> None:
        # If ARGO drops group_id from results, two use cases look alike and
        # the record fails rather than overwriting the other one.
        no_group = _stored("m-1")
        del no_group["group_id"]
        fake = FakeArgo([no_group, _stored("m-2", group_id="suc2") | {"group_id": None}])
        with pytest.raises(AmbiguousMetricError):
            _sink(fake).upsert(RECORD)


class TestPostTimeout:
    def test_searches_again_instead_of_posting_twice(self) -> None:
        fake = FakeArgo()
        fake.fail_post_with = httpx.ReadTimeout("slow")
        assert _sink(fake).upsert(RECORD) is UpsertOutcome.CREATED
        assert fake.methods() == ["POST search", "POST /", "POST search"]

    def test_posts_once_more_if_the_timed_out_post_did_not_land(self) -> None:
        fake = FakeArgo()

        def dropping(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == METRICS and not fake.calls[2:]:
                fake.calls.append((request.method, request.url.path, None))
                raise httpx.ReadTimeout("slow")
            return fake(request)

        assert _sink(dropping).upsert(RECORD) is UpsertOutcome.CREATED
        assert fake.methods() == ["POST search", "POST /", "POST search", "POST /"]

    def test_a_connect_timeout_is_not_ambiguous_and_propagates(self) -> None:
        def refusing(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("down")

        with pytest.raises(httpx.ConnectTimeout):
            _sink(refusing).upsert(RECORD)


class TestErrors:
    @pytest.mark.parametrize(
        ("operation", "stored"), [("search", []), ("post", []), ("patch", ["m-1"])]
    )
    def test_error_responses_raise_with_status(self, operation: str, stored: list[str]) -> None:
        fake = FakeArgo([_stored(m) for m in stored])
        fake.status[operation] = 400
        with pytest.raises(ArgoError, match="400"):
            _sink(fake).upsert(RECORD)

    def test_unconfigured_project_raises_before_any_call(self) -> None:
        fake = FakeArgo()
        with pytest.raises(ArgoError, match="RI-SCALE_BBMRI"):
            _sink(fake).upsert(UsageRecord(date(2026, 11, 22), "RI-SCALE_BBMRI", "suc5", 1))
        assert fake.calls == []
