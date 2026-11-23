"""Dry-run sink: one JSON line per record on stdout, nothing sent."""

from __future__ import annotations

import json
from datetime import date

import pytest

from usage_reporter.adapters.stdout import StdoutSink
from usage_reporter.core.model import ReportOutcome, UsageRecord


def test_prints_the_metric_as_json_and_reports_a_dry_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    record = UsageRecord(date(2026, 11, 22), "RI-SCALE_ENES", "suc1", 151)
    assert StdoutSink().report(record) is ReportOutcome.DRY_RUN
    assert json.loads(capsys.readouterr().out) == {
        "project_id": "RI-SCALE_ENES",
        "group_id": "suc1",
        "time_period_start": "2026-11-22T00:00:00Z",
        "time_period_end": "2026-11-22T23:59:59Z",
        "value": 151,
    }
