"""Rucio account attributes -> ARGO project and use case (Design-009)."""

from __future__ import annotations

from collections.abc import Collection, Mapping

from usage_reporter.core.model import Group

PROJECT_KEY = "project_id"
GROUP_KEY = "group_id"


def group_from_attributes(
    attributes: Mapping[str, str], known_projects: Collection[str]
) -> Group | None:
    """Both attributes set and the project configured, else None (unmapped)."""
    project_id = attributes.get(PROJECT_KEY, "").strip()
    group_id = attributes.get(GROUP_KEY, "").strip()
    if not project_id or not group_id or project_id not in known_projects:
        return None
    return Group(project_id=project_id, group_id=group_id)
