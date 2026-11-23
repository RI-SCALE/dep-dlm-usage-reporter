"""Account attributes -> (project_id, group_id) (Design-009, "Account mapping")."""

from __future__ import annotations

import pytest

from usage_reporter.core.mapping import group_from_attributes
from usage_reporter.core.model import Group

KNOWN = frozenset(
    {"RI-SCALE_ENES", "RI-SCALE_EISCAT", "RI-SCALE_BBMRI", "RI-SCALE_Euro-BioImaging"}
)


def test_both_attributes_and_known_project_map() -> None:
    attrs = {"project_id": "RI-SCALE_ENES", "group_id": "suc1", "admin": "False"}
    assert group_from_attributes(attrs, KNOWN) == Group(project_id="RI-SCALE_ENES", group_id="suc1")


@pytest.mark.parametrize(
    "attrs",
    [
        {},
        {"project_id": "RI-SCALE_ENES"},
        {"group_id": "suc1"},
        {"project_id": "", "group_id": "suc1"},
        {"project_id": "RI-SCALE_ENES", "group_id": "  "},
    ],
)
def test_missing_or_blank_attribute_is_unmapped(attrs: dict[str, str]) -> None:
    assert group_from_attributes(attrs, KNOWN) is None


def test_project_not_configured_is_unmapped() -> None:
    attrs = {"project_id": "RI-SCALE_UNKNOWN", "group_id": "suc9"}
    assert group_from_attributes(attrs, KNOWN) is None


def test_values_are_trimmed() -> None:
    attrs = {"project_id": " RI-SCALE_ENES ", "group_id": " suc1 "}
    assert group_from_attributes(attrs, KNOWN) == Group(project_id="RI-SCALE_ENES", group_id="suc1")


def test_project_ids_are_case_sensitive() -> None:
    attrs = {"project_id": "ri-scale_enes", "group_id": "suc1"}
    assert group_from_attributes(attrs, KNOWN) is None
