"""Ports the core defines and adapters implement."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from usage_reporter.core.model import Group, ReportOutcome, Transfer, UsageRecord


class TransferSource(Protocol):
    def finished_transfers(self, start: datetime, end: datetime) -> Iterable[Transfer]:
        """Finished transfers with transferred_at in [start, end). May overshoot."""
        ...


class GroupMapping(Protocol):
    def resolve(self, account: str) -> Group | None:
        """Where an account reports, or None if it is not mapped."""
        ...


class AccountingSink(Protocol):
    def report(self, record: UsageRecord) -> ReportOutcome:
        """Create the record unless its day, project and group already exist."""
        ...
