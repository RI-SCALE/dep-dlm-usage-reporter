"""Daily byte totals per project and use case."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date

from usage_reporter.core.model import AggregateResult, Group, Transfer, UsageRecord
from usage_reporter.core.window import as_utc


def aggregate(
    transfers: Iterable[Transfer],
    mapping: Mapping[str, Group | None],
    days: Sequence[date],
) -> AggregateResult:
    """Sum bytes per (day, project, group) for transfers inside `days`.

    Duplicate request IDs count once. Rows without bytes or timestamp, or with
    negative bytes, are skipped. Accounts without a group are reported as
    unmapped, never guessed into one.
    """
    wanted = set(days)
    seen: set[str] = set()
    totals: dict[tuple[date, str, str], int] = defaultdict(int)
    unmapped: dict[str, int] = defaultdict(int)
    skipped = 0

    for transfer in transfers:
        if transfer.request_id in seen:
            continue
        seen.add(transfer.request_id)

        if transfer.bytes is None or transfer.transferred_at is None or transfer.bytes < 0:
            skipped += 1
            continue

        day = as_utc(transfer.transferred_at).date()
        if day not in wanted:
            continue

        group = mapping.get(transfer.account)
        if group is None:
            unmapped[transfer.account] += transfer.bytes
            continue
        totals[(day, group.project_id, group.group_id)] += transfer.bytes

    records = tuple(
        UsageRecord(day=day, project_id=project_id, group_id=group_id, bytes=total)
        for (day, project_id, group_id), total in sorted(totals.items())
    )
    return AggregateResult(records=records, unmapped=dict(unmapped), skipped=skipped)
