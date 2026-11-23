"""Dry-run sink: prints each metric as one JSON line, sends nothing."""

from __future__ import annotations

import json
import sys
from typing import TextIO

from usage_reporter.core.model import ReportOutcome, UsageRecord
from usage_reporter.core.ports import AccountingSink


class StdoutSink(AccountingSink):
    def __init__(self, out: TextIO | None = None) -> None:
        self._out = out

    def report(self, record: UsageRecord) -> ReportOutcome:
        day = record.day.isoformat()
        line = {
            "project_id": record.project_id,
            "group_id": record.group_id,
            "time_period_start": f"{day}T00:00:00Z",
            "time_period_end": f"{day}T23:59:59Z",
            "value": record.bytes,
        }
        print(json.dumps(line), file=self._out or sys.stdout, flush=True)
        return ReportOutcome.DRY_RUN
