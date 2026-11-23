"""ARGO Accounting sink: one metric per UTC day, project and use case.

Upsert is search, then PATCH or POST. POST is not idempotent and ARGO has no
client-chosen metric ID, so a POST that may have landed (read or write
timeout) is followed by a new search, never by a blind retry.

Shapes follow the ARGO docs and OpenAPI 1.0.0. `group_id` is documented as
optional but missing from the spec; it is sent when set, and results that
lack it are treated as matching, so an unclear match fails instead of
overwriting another use case.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from usage_reporter.core.model import UpsertOutcome, UsageRecord
from usage_reporter.core.ports import AccountingSink

SEARCH = "/accounting-system/metrics/search"
MAY_HAVE_LANDED = (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError)


class ArgoError(RuntimeError):
    """ARGO rejected a call, or the record cannot be sent."""


class AmbiguousMetricError(ArgoError):
    """More than one stored metric matches a record; nothing was written."""


@dataclass(frozen=True)
class ArgoProject:
    """An accounting project's installation and the auth of its own client."""

    installation_id: str
    auth: httpx.Auth


def _period(day: date) -> tuple[str, str]:
    iso = day.isoformat()
    return f"{iso}T00:00:00Z", f"{iso}T23:59:59Z"


def _same_instant(a: str, b: str) -> bool:
    return datetime.fromisoformat(a) == datetime.fromisoformat(b)


class ArgoSink(AccountingSink):
    """AccountingSink over ARGO's search, POST and PATCH."""

    def __init__(
        self,
        endpoint: str,
        metric_definition_id: str,
        projects: Mapping[str, ArgoProject],
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(base_url=endpoint, timeout=timeout_seconds, transport=transport)
        self._definition = metric_definition_id
        self._projects = projects

    def close(self) -> None:
        self._http.close()

    def upsert(self, record: UsageRecord) -> UpsertOutcome:
        project = self._projects.get(record.project_id)
        if project is None:
            raise ArgoError(f"project {record.project_id} is not configured")
        existing = self._find(project, record)
        if existing is not None:
            self._call(
                "PATCH", f"{self._metrics(project)}/{existing}", project, {"value": record.bytes}
            )
            return UpsertOutcome.UPDATED
        try:
            self._post(project, record)
        except MAY_HAVE_LANDED:
            if self._find(project, record) is None:
                self._post(project, record)
        return UpsertOutcome.CREATED

    def _find(self, project: ArgoProject, record: UsageRecord) -> str | None:
        """ID of the stored metric for this record, None if there is none."""
        start, _ = _period(record.day)
        wanted = {
            "installation_id": project.installation_id,
            "metric_definition_id": self._definition,
            "time_period_start": start,
            "group_id": record.group_id,
        }
        criteria = [
            {"type": "query", "field": k, "values": v, "operand": "eq"} for k, v in wanted.items()
        ]
        body = {"type": "filter", "operator": "AND", "criteria": criteria}
        content = self._call("POST", SEARCH, project, body).get("content") or []
        # Search filters are loosely specified, so check results here as well.
        ids = [str(m.get("id") or m.get("metric_id")) for m in content if self._matches(m, wanted)]
        if len(ids) > 1:
            raise AmbiguousMetricError(f"{record}: several stored metrics match ({', '.join(ids)})")
        return ids[0] if ids else None

    @staticmethod
    def _matches(metric: Mapping[str, Any], wanted: Mapping[str, str]) -> bool:
        definitions = metric.get("metric_definition") or []
        found = {
            "installation_id": metric.get("installation_id"),
            "metric_definition_id": metric.get("metric_definition_id")
            or next((d.get("id") for d in definitions if isinstance(d, dict)), None),
            "group_id": metric.get("group_id"),
        }
        if any(v is not None and v != wanted[k] for k, v in found.items()):
            return False
        start = metric.get("time_period_start")
        return start is None or _same_instant(str(start), wanted["time_period_start"])

    def _post(self, project: ArgoProject, record: UsageRecord) -> None:
        start, end = _period(record.day)
        body: dict[str, Any] = {
            "metric_definition_id": self._definition,
            "time_period_start": start,
            "time_period_end": end,
            "value": record.bytes,
        }
        if record.group_id:
            body["group_id"] = record.group_id
        self._call("POST", self._metrics(project), project, body)

    @staticmethod
    def _metrics(project: ArgoProject) -> str:
        return f"/accounting-system/installations/{project.installation_id}/metrics"

    def _call(self, method: str, path: str, project: ArgoProject, body: object) -> dict[str, Any]:
        response = self._http.request(method, path, json=body, auth=project.auth)
        if response.is_error:
            raise ArgoError(f"{method} {path} returned {response.status_code}")
        payload = response.json() if response.content else {}
        return payload if isinstance(payload, dict) else {}
