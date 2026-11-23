"""Daily totals per (project, group) (Design-001, "Testing")."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

from usage_reporter.core.aggregate import aggregate
from usage_reporter.core.model import Group, Transfer, UsageRecord

DAY = date(2026, 11, 22)
NEXT = date(2026, 11, 23)
# ARGO project IDs and use cases as agreed with ARGO (RI-SCALE, Nov 2026)
ENES_SUC1 = Group(project_id="RI-SCALE_ENES", group_id="suc1")
ENES_SUC2 = Group(project_id="RI-SCALE_ENES", group_id="suc2")
EISCAT_SUC3 = Group(project_id="RI-SCALE_EISCAT", group_id="suc3")
EBI_SUC8 = Group(project_id="RI-SCALE_Euro-BioImaging", group_id="suc8")


def _t(rid: str, account: str, nbytes: int | None, at: datetime | None) -> Transfer:
    return Transfer(request_id=rid, account=account, bytes=nbytes, transferred_at=at)


def _at(day: date, hour: int = 12, **kw: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC) + timedelta(**kw)


def test_empty_history_gives_no_records() -> None:
    result = aggregate([], {}, [DAY])
    assert result.records == ()
    assert result.unmapped == {}
    assert result.skipped == 0


def test_sums_per_day_and_group() -> None:
    mapping = {"suc1-prod": ENES_SUC1, "alice": ENES_SUC1, "suc2-prod": ENES_SUC2}
    transfers = [
        _t("r1", "suc1-prod", 100, _at(DAY)),
        _t("r2", "alice", 50, _at(DAY)),
        _t("r3", "suc2-prod", 7, _at(DAY)),
        _t("r4", "suc1-prod", 1, _at(NEXT)),
    ]
    result = aggregate(transfers, mapping, [DAY, NEXT])
    assert result.records == (
        UsageRecord(day=DAY, project_id="RI-SCALE_ENES", group_id="suc1", bytes=150),
        UsageRecord(day=DAY, project_id="RI-SCALE_ENES", group_id="suc2", bytes=7),
        UsageRecord(day=NEXT, project_id="RI-SCALE_ENES", group_id="suc1", bytes=1),
    )


def test_day_boundary_last_microsecond_and_midnight() -> None:
    mapping = {"a": ENES_SUC1}
    transfers = [
        _t("late", "a", 1, datetime(2026, 11, 22, 23, 59, 59, 999_999, tzinfo=UTC)),
        _t("midnight", "a", 10, datetime(2026, 11, 23, 0, 0, 0, tzinfo=UTC)),
    ]
    result = aggregate(transfers, mapping, [DAY, NEXT])
    assert {(r.day, r.bytes) for r in result.records} == {(DAY, 1), (NEXT, 10)}


def test_naive_timestamps_are_utc_and_aware_ones_are_converted() -> None:
    mapping = {"a": ENES_SUC1}
    zurich = timezone(timedelta(hours=1))
    transfers = [
        _t("naive", "a", 1, datetime(2026, 11, 22, 23, 30)),  # UTC -> DAY
        _t("aware", "a", 2, datetime(2026, 11, 23, 0, 30, tzinfo=zurich)),  # 23:30Z -> DAY
    ]
    result = aggregate(transfers, mapping, [DAY, NEXT])
    assert result.records == (
        UsageRecord(day=DAY, project_id="RI-SCALE_ENES", group_id="suc1", bytes=3),
    )


def test_outside_window_is_ignored_not_skipped() -> None:
    result = aggregate([_t("old", "a", 5, _at(date(2026, 11, 1)))], {"a": ENES_SUC1}, [DAY])
    assert result.records == ()
    assert result.skipped == 0


def test_null_bytes_or_timestamp_is_skipped() -> None:
    transfers = [_t("r1", "a", None, _at(DAY)), _t("r2", "a", 5, None)]
    result = aggregate(transfers, {"a": ENES_SUC1}, [DAY])
    assert result.records == ()
    assert result.skipped == 2


def test_negative_bytes_is_skipped() -> None:
    result = aggregate([_t("r1", "a", -1, _at(DAY))], {"a": ENES_SUC1}, [DAY])
    assert result.records == ()
    assert result.skipped == 1


def test_duplicate_request_ids_count_once() -> None:
    transfers = [_t("r1", "a", 100, _at(DAY)), _t("r1", "a", 100, _at(DAY))]
    result = aggregate(transfers, {"a": ENES_SUC1}, [DAY])
    assert result.records[0].bytes == 100


def test_unmapped_accounts_are_reported_with_their_bytes() -> None:
    transfers = [
        _t("r1", "ghost", 30, _at(DAY)),
        _t("r2", "ghost", 12, _at(NEXT)),
        _t("r3", "service", 5, _at(DAY)),
    ]
    mapping: dict[str, Group | None] = {"service": None}
    result = aggregate(transfers, mapping, [DAY, NEXT])
    assert result.records == ()
    assert result.unmapped == {"ghost": 42, "service": 5}


def test_large_values_do_not_overflow() -> None:
    petabytes = 10**18
    transfers = [_t(f"r{i}", "a", petabytes, _at(DAY)) for i in range(10)]
    result = aggregate(transfers, {"a": ENES_SUC1}, [DAY])
    assert result.records[0].bytes == 10 * petabytes


def test_accepts_a_one_shot_iterator() -> None:
    transfers = iter([_t("r1", "a", 1, _at(DAY))])
    assert aggregate(transfers, {"a": ENES_SUC1}, [DAY]).records[0].bytes == 1


def test_projects_and_use_cases_stay_separate() -> None:
    mapping = {"suc1-prod": ENES_SUC1, "suc3-prod": EISCAT_SUC3, "suc8-prod": EBI_SUC8}
    transfers = [
        _t("r1", "suc1-prod", 10, _at(DAY)),
        _t("r2", "suc3-prod", 20, _at(DAY)),
        _t("r3", "suc8-prod", 30, _at(DAY)),
        _t("r4", "suc3-prod", 5, _at(DAY)),
    ]
    result = aggregate(transfers, mapping, [DAY])
    assert {(r.project_id, r.group_id, r.bytes) for r in result.records} == {
        ("RI-SCALE_ENES", "suc1", 10),
        ("RI-SCALE_EISCAT", "suc3", 25),
        ("RI-SCALE_Euro-BioImaging", "suc8", 30),
    }
