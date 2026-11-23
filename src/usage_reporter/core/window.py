"""Reporting window and UTC day boundaries."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta


def window(today: date, lookback_days: int) -> list[date]:
    """Yesterday plus `lookback_days` earlier days, oldest first."""
    if lookback_days < 0:
        raise ValueError(f"lookback_days must be >= 0, got {lookback_days}")
    return [today - timedelta(days=n) for n in range(lookback_days + 1, 0, -1)]


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """The UTC day as a half-open interval [start, end)."""
    start = datetime.combine(day, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def as_utc(moment: datetime) -> datetime:
    """Naive timestamps are UTC (Rucio's convention); aware ones are converted."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)
