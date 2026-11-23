"""Smoke test so the unit suite and CI run from day one."""

import usage_reporter


def test_version_is_set() -> None:
    assert usage_reporter.__version__ == "0.1.0"
