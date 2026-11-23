"""One reporting run over the ports, with in-memory fakes (Design-001, step 4)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest

from usage_reporter.core.model import Group, ReportOutcome, Transfer, UsageRecord
from usage_reporter.core.report import RecordError, report_usage

DAY = date(2026, 11, 22)
AT = datetime(2026, 11, 22, 9, tzinfo=UTC)
GROUPS = {
    "suc1-prod": Group("RI-SCALE_ENES", "suc1"),
    "suc2-prod": Group("RI-SCALE_ENES", "suc2"),
}


class Source:
    def __init__(self, *transfers: Transfer) -> None:
        self.transfers = transfers
        self.asked: list[tuple[datetime, datetime]] = []

    def finished_transfers(self, start: datetime, end: datetime) -> Iterator[Transfer]:
        self.asked.append((start, end))
        yield from self.transfers


class Mapping:
    def __init__(self) -> None:
        self.resolved: list[str] = []

    def resolve(self, account: str) -> Group | None:
        self.resolved.append(account)
        return GROUPS.get(account)


class Sink:
    def __init__(self, outcome: ReportOutcome = ReportOutcome.CREATED) -> None:
        self.outcome = outcome
        self.reported: list[UsageRecord] = []
        self.fail: dict[str, Exception] = {}  # group_id -> error

    def report(self, record: UsageRecord) -> ReportOutcome:
        if error := self.fail.get(record.group_id):
            raise error
        self.reported.append(record)
        return self.outcome


def _transfer(rid: str, account: str, nbytes: int) -> Transfer:
    return Transfer(rid, account, nbytes, AT)


def test_reports_each_group_and_exits_0() -> None:
    source = Source(_transfer("1", "suc1-prod", 100), _transfer("2", "suc2-prod", 7))
    sink = Sink()
    summary = report_usage(source, Mapping(), sink, [DAY])
    assert [(r.group_id, r.bytes) for r in sink.reported] == [("suc1", 100), ("suc2", 7)]
    assert summary.outcomes == {ReportOutcome.CREATED: 2}
    assert summary.exit_code == 0


def test_asks_the_source_for_the_whole_window() -> None:
    source = Source()
    report_usage(source, Mapping(), Sink(), [DAY, date(2026, 11, 23)])
    assert source.asked == [(AT.replace(hour=0), datetime(2026, 11, 24, tzinfo=UTC))]


def test_resolves_each_account_once_and_skips_empty_ones() -> None:
    mapping = Mapping()
    source = Source(
        _transfer("1", "suc1-prod", 1), _transfer("2", "suc1-prod", 1), _transfer("3", "", 5)
    )
    summary = report_usage(source, mapping, Sink(), [DAY])
    assert mapping.resolved == ["suc1-prod"]
    assert summary.unmapped == {"": 5}


def test_unmapped_accounts_exit_2() -> None:
    summary = report_usage(Source(_transfer("1", "ghost", 30)), Mapping(), Sink(), [DAY])
    assert summary.unmapped == {"ghost": 30}
    assert summary.exit_code == 2


def test_already_reported_days_are_counted_not_failed() -> None:
    sink = Sink(ReportOutcome.EXISTS)
    summary = report_usage(Source(_transfer("1", "suc1-prod", 1)), Mapping(), sink, [DAY])
    assert summary.outcomes == {ReportOutcome.EXISTS: 1}
    assert summary.exit_code == 0


def test_a_rejected_record_fails_alone_and_exits_3() -> None:
    sink = Sink()
    sink.fail["suc1"] = RecordError("400 from ARGO")
    source = Source(_transfer("1", "suc1-prod", 1), _transfer("2", "suc2-prod", 2))
    summary = report_usage(source, Mapping(), sink, [DAY])
    assert [r.group_id for r in sink.reported] == ["suc2"]
    assert [(r.group_id, reason) for r, reason in summary.failed] == [("suc1", "400 from ARGO")]
    assert summary.exit_code == 3


def test_failures_outrank_unmapped_accounts() -> None:
    sink = Sink()
    sink.fail["suc1"] = RecordError("nope")
    source = Source(_transfer("1", "suc1-prod", 1), _transfer("2", "ghost", 1))
    assert report_usage(source, Mapping(), sink, [DAY]).exit_code == 3


def test_other_errors_abort_the_run() -> None:
    sink = Sink()
    sink.fail["suc1"] = ConnectionError("ARGO down")
    with pytest.raises(ConnectionError):
        report_usage(Source(_transfer("1", "suc1-prod", 1)), Mapping(), sink, [DAY])


def test_needs_at_least_one_day() -> None:
    with pytest.raises(ValueError, match="day"):
        report_usage(Source(), Mapping(), Sink(), [])
