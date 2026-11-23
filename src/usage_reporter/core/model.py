"""Core data types. Standard library only (Design-001, "Layout")."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


@dataclass(frozen=True)
class Transfer:
    """One finished transfer request, as read from Rucio's history."""

    request_id: str
    account: str
    bytes: int | None
    transferred_at: datetime | None


@dataclass(frozen=True)
class Group:
    """Where an account's usage is reported: ARGO project and use case."""

    project_id: str
    group_id: str


@dataclass(frozen=True)
class UsageRecord:
    """Bytes transferred on one UTC day for one project and use case."""

    day: date
    project_id: str
    group_id: str
    bytes: int


@dataclass(frozen=True)
class AggregateResult:
    """Records to send, plus what could not be attributed."""

    records: tuple[UsageRecord, ...] = ()
    unmapped: Mapping[str, int] = field(default_factory=dict)  # account -> bytes
    skipped: int = 0  # rows without bytes or timestamp


class ReportOutcome(StrEnum):
    CREATED = "created"
    EXISTS = "exists"  # already reported; left as is, never patched
    DRY_RUN = "dry_run"
