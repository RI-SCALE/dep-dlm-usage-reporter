"""One reporting run over the ports: read, map, sum, report (Design-009)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from usage_reporter.core.aggregate import aggregate
from usage_reporter.core.model import ReportOutcome, UsageRecord
from usage_reporter.core.ports import AccountingSink, GroupMapping, TransferSource
from usage_reporter.core.window import day_bounds


class RecordError(Exception):
    """The sink rejected one record; the run continues with the others.

    Any other exception means a dependency is unusable and aborts the run.
    """


@dataclass(frozen=True)
class RunSummary:
    outcomes: Mapping[ReportOutcome, int] = field(default_factory=dict)
    failed: tuple[tuple[UsageRecord, str], ...] = ()
    unmapped: Mapping[str, int] = field(default_factory=dict)  # account -> bytes
    skipped: int = 0

    @property
    def exit_code(self) -> int:
        """3 some records failed, 2 unmapped accounts, 0 ok (Design-001)."""
        if self.failed:
            return 3
        return 2 if self.unmapped else 0


def report_usage(
    source: TransferSource,
    mapping: GroupMapping,
    sink: AccountingSink,
    days: Sequence[date],
) -> RunSummary:
    if not days:
        raise ValueError("at least one day is needed")
    start, end = day_bounds(min(days))[0], day_bounds(max(days))[1]
    transfers = list(source.finished_transfers(start, end))
    accounts = sorted({t.account for t in transfers})
    groups = {a: mapping.resolve(a) if a else None for a in accounts}
    result = aggregate(transfers, groups, days)

    outcomes: Counter[ReportOutcome] = Counter()
    failed: list[tuple[UsageRecord, str]] = []
    for record in result.records:
        try:
            outcomes[sink.report(record)] += 1
        except RecordError as exc:
            failed.append((record, str(exc)))
    return RunSummary(dict(outcomes), tuple(failed), result.unmapped, result.skipped)
