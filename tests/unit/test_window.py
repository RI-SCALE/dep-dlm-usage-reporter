"""Reporting window and UTC day boundaries (Design-001, "Core signatures")."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from usage_reporter.core.window import as_utc, day_bounds, window


class TestWindow:
    def test_no_lookback_is_yesterday_only(self) -> None:
        assert window(date(2026, 11, 23), lookback_days=0) == [date(2026, 11, 22)]

    def test_lookback_adds_earlier_days_oldest_first(self) -> None:
        assert window(date(2026, 11, 23), lookback_days=2) == [
            date(2026, 11, 20),
            date(2026, 11, 21),
            date(2026, 11, 22),
        ]

    def test_crosses_month_and_year(self) -> None:
        assert window(date(2027, 1, 1), lookback_days=1) == [
            date(2026, 12, 30),
            date(2026, 12, 31),
        ]

    def test_negative_lookback_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="lookback_days"):
            window(date(2026, 11, 23), lookback_days=-1)


class TestDayBounds:
    def test_half_open_utc_day(self) -> None:
        start, end = day_bounds(date(2026, 11, 22))
        assert start == datetime(2026, 11, 22, tzinfo=UTC)
        assert end == datetime(2026, 11, 23, tzinfo=UTC)


class TestAsUtc:
    def test_naive_is_treated_as_utc(self) -> None:
        assert as_utc(datetime(2026, 11, 22, 23, 59, 59)) == datetime(
            2026, 11, 22, 23, 59, 59, tzinfo=UTC
        )

    def test_aware_is_converted(self) -> None:
        zurich_winter = timezone(timedelta(hours=1))
        assert as_utc(datetime(2026, 11, 23, 0, 30, tzinfo=zurich_winter)) == datetime(
            2026, 11, 22, 23, 30, tzinfo=UTC
        )
